"""Tournament desktop contract tests; no capture hardware, OBS, or webview needed."""
from copy import deepcopy
import json
import logging
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from ddrcv.apps.driver_config import load_config, normalize_config, validate_config
from ddrcv.desktop.controller import Desk, MASK
from ddrcv.desktop.app import create_app
from ddrcv.desktop.host import Instance, Panel, ExitConfirmation


def wait_for(predicate, timeout=4):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError('Condition timed out')
        time.sleep(.01)


class FakeRuntime:
    def __init__(self, config):
        self.config = deepcopy(config)
        self.finished = threading.Event()
        self.thread = None
        self.phase = 'Ready'
        self.stop_calls = 0
        self.integrations = Mock()

    def start(self):
        self.thread = True
        self.phase = 'Running'

    def stop(self):
        self.stop_calls += 1
        self.finished.set()
        self.phase = 'Stopped'

    def switch_source(self, ingest):
        self.config['ingest'] = deepcopy(ingest)

    def configure_results(self, settings):
        self.config['results'].update(settings)

    def control(self, action, value):
        if action == 'names':
            self.config['player_names']['enabled'] = value

    def status(self):
        return dict(phase=self.phase, error=None, obs={}, renderer={})


class DeskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.desk = Desk(self.root, FakeRuntime)

    def tearDown(self):
        self.desk.close()
        self.temp.cleanup()

    def test_launch_and_restore_never_start_capture(self):
        config = self.desk.config()['draft']
        config['publish']['websocket']['port'] = 19005
        self.desk.edit(config)
        self.desk.close()
        self.desk = Desk(self.root, FakeRuntime)
        self.assertIsNone(self.desk.runtime)
        self.assertEqual(self.desk.config()['draft']['publish']['websocket']['port'], 19005)
        self.assertTrue(self.desk.config()['pending'])

    def test_desktop_prepares_the_neutral_driver_runtime(self):
        self.desk.runtime_factory = None
        config = self.desk.config()['draft']
        with patch('ddrcv.apps.driver_ddr.create_runtime') as factory:
            self.assertIs(self.desk._prepare(config), factory.return_value)
        factory.assert_called_once_with(config, self.desk.log,
                                        data_dir=self.root, desktop=True)

    def test_live_name_switches_apply_only_their_setting(self):
        self.desk.start()
        runtime = self.desk.runtime
        original_port = runtime.config['publish']['websocket']['port']
        draft = self.desk.config()['draft']
        draft['publish']['websocket']['port'] = original_port + 1
        draft['results']['output_directory'] = 'pending folder'
        self.desk.edit(draft)
        self.desk.set_names('player_names', True)
        self.desk.set_names('results', False)
        self.assertEqual(runtime.stop_calls, 0)
        self.assertTrue(runtime.config['player_names']['enabled'])
        self.assertFalse(runtime.config['results']['parse_names'])
        self.assertEqual(runtime.config['publish']['websocket']['port'], original_port)
        self.assertNotEqual(runtime.config['results']['output_directory'], 'pending folder')
        self.assertEqual(self.desk.config()['draft']['results']['output_directory'], 'pending folder')
        self.assertEqual(self.desk.config()['draft']['publish']['websocket']['port'], original_port + 1)

    def test_screenshots_only_live_action_is_scoped_authenticated_and_persisted(self):
        self.assertFalse(self.desk.config()['draft']['results']['screenshots_only'])
        self.desk.start()
        runtime = self.desk.runtime
        draft = self.desk.config()['draft']
        draft['results']['output_directory'] = 'unapplied folder'
        draft['publish']['websocket']['port'] += 1
        self.desk.edit(draft)
        client = create_app(self.desk, 'test').test_client()
        args = dict(action='set_screenshots_only', enabled=True)
        self.assertEqual(client.post('/api/action', json=args).status_code, 403)
        self.assertEqual(client.post('/api/action', json=args, headers={'X-Desk-Token': 'test'}).status_code, 200)
        self.assertTrue(runtime.config['results']['screenshots_only'])
        self.assertTrue(runtime.config['results']['parse_names'])
        self.assertNotEqual(runtime.config['results']['output_directory'], 'unapplied folder')
        self.assertNotEqual(runtime.config['publish']['websocket']['port'], draft['publish']['websocket']['port'])
        self.assertEqual(runtime.stop_calls, 0)
        self.assertEqual(self.desk.config()['draft']['results']['output_directory'], 'unapplied folder')
        self.desk.close()
        self.desk = Desk(self.root, FakeRuntime)
        self.assertTrue(self.desk.config()['draft']['results']['screenshots_only'])
        self.desk.set_screenshots_only(False)
        self.assertFalse(self.desk.config()['draft']['results']['screenshots_only'])
        with self.assertRaises(ValueError):
            self.desk.set_screenshots_only('false')

    def test_results_history_images_and_recovery_use_authenticated_api(self):
        import numpy as np
        from ddrcv.results.service import ResultsService
        self.desk.start()
        service = ResultsService(self.root / 'outbox', reader=Mock())
        self.desk.runtime.results = service
        client = create_app(self.desk, 'test-token').test_client()
        headers = {'X-Desk-Token':'test-token'}
        players = [dict(present=True, name=None, score=100), dict(present=True, name=None, score=200)]
        record = dict(event_id='test-event', source_id='source', recorded=False, interval=[0,2],
                      timestamp=2, players=players, partial=True, screenshot_confirmed=True,
                      score_mode='ex', outcome=dict(kind='winner', winner=1, margin=100), auto_publish=False, created_at=1)
        try:
            service.outbox.save(record, np.zeros((20,20,3), np.uint8))
            self.assertEqual(client.get('/api/results').status_code, 403)
            self.assertEqual(len(client.get('/api/results', headers=headers).json['records']), 1)
            image = client.get('/api/results/test-event/screenshot', headers=headers)
            self.assertEqual(image.status_code, 200); image.close()
            self.assertEqual(client.get('/api/results/unknown/screenshot', headers=headers).status_code, 400)
            self.assertEqual(client.get('/api/results/test-event/result', headers=headers).status_code, 400)
            args = dict(action='results_command', command='republish', event_id='test-event')
            self.assertEqual(client.post('/api/action', json=args, headers=headers).status_code, 400)
            with patch.object(service.outbox, 'command') as command:
                args['command'] = 'retry'
                self.assertEqual(client.post('/api/action', json=args, headers=headers).status_code, 200)
                command.assert_called_once_with('retry', 'test-event')
            service.close()
            self.assertFalse(client.get('/api/results', headers=headers).json['delivery_available'])
            self.assertEqual(client.post('/api/action', json=args, headers=headers).status_code, 400)
        finally: service.close()

    def test_cli_roundtrip_preserves_unknown_fields_and_secrets(self):
        config = self.desk.config()['draft']
        config['future_feature'] = {'keep': [1, 2, 3]}
        config['score_filter']['max_per_frame'] = None
        config['obs']['password'] = 'test-secret'
        self.desk.edit(config)
        masked = self.desk.config()['draft']
        self.assertEqual(masked['obs']['password'], MASK)
        masked['publish']['websocket']['port'] = 19006
        self.desk.edit(masked)
        path = self.root / 'shared.json'
        self.desk.save(path)
        loaded = load_config(path)
        self.assertEqual(loaded, validate_config(self.desk.draft))
        self.assertEqual(loaded['obs']['password'], 'test-secret')
        self.assertEqual(loaded['future_feature'], {'keep': [1, 2, 3]})
        self.assertIsNone(loaded['score_filter']['max_per_frame'])

    def test_legacy_partial_config_uses_same_defaults(self):
        path = self.root / 'legacy.json'
        path.write_text('{"debounce":{"min_frames":4}}')
        self.desk.load(path)
        self.assertEqual(self.desk.draft, load_config(path))
        self.assertEqual(self.desk.draft['score_filter']['max_per_frame'], 12)
        self.assertFalse(self.desk.draft['obs']['enabled'])
        self.assertFalse(self.desk.draft['renderer']['enabled'])
        self.assertTrue(self.desk.draft['results']['enabled'])
        self.assertFalse(load_config(path)['results']['discord'])
        self.assertFalse(validate_config({'results': {'enabled': False}})['results']['enabled'])

    def test_edits_and_loads_leave_active_runtime_untouched(self):
        self.desk.start()
        runtime = self.desk.runtime
        config = self.desk.config()['draft']
        config['publish']['websocket']['port'] += 1
        self.desk.edit(config)
        path = self.root / 'next.json'
        path.write_text('{"score_filter":{"max_per_frame":null}}')
        self.desk.load(path)
        self.assertIs(self.desk.runtime, runtime)
        self.assertEqual(runtime.stop_calls, 0)
        self.assertTrue(self.desk.config()['pending'])
        self.desk.apply()
        self.assertEqual(runtime.stop_calls, 1)
        self.assertEqual(self.desk.runtime.phase, 'Running')
        self.assertIsNone(self.desk.runtime.config['score_filter']['max_per_frame'])

    def test_apply_while_stopped_never_starts(self):
        self.desk.apply()
        self.desk.apply()
        self.assertEqual(self.desk.runtime.phase, 'Ready')
        self.assertIsNone(self.desk.runtime.thread)

    def test_replay_duplicates_defaults_and_strict_profile_validation(self):
        self.assertFalse(normalize_config({})['results']['allow_replay_duplicates'])
        for value in ('false', 1, None):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'allow_replay_duplicates'):
                validate_config({'results': {'allow_replay_duplicates': value}})

    def test_results_controls_apply_live_preserve_other_edits_and_mask_webhook(self):
        self.desk.start()
        runtime = self.desk.runtime
        config = self.desk.config()['draft']
        config['results'].update(enabled=True, discord=True, parse_names=False, allow_replay_duplicates=True,
                                 webhook='https://discord.com/api/webhooks/1/desktop-test',
                                 output_directory=str(self.root / 'exports'), include_player_names=False)
        config['obs']['port'] = ''  # Unfinished unrelated edits must not block results controls.
        config['results']['outbox_directory'] = 'pending-outbox'
        self.desk.edit(config)
        client = create_app(self.desk, 'test').test_client()
        self.assertEqual(client.post('/api/action', json={'action': 'apply_results'}).status_code, 403)
        response = client.post('/api/action', json={'action': 'apply_results'}, headers={'X-Desk-Token': 'test'})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertIs(self.desk.runtime, runtime)
        self.assertEqual(runtime.stop_calls, 0)
        self.assertFalse(runtime.config['results']['parse_names'])
        self.assertTrue(runtime.config['results']['discord'])
        self.assertTrue(runtime.config['results']['allow_replay_duplicates'])
        self.assertEqual(runtime.config['results']['output_directory'], str(self.root / 'exports'))
        self.assertFalse(runtime.config['results']['include_player_names'])
        self.assertNotEqual(runtime.config['results']['outbox_directory'], 'pending-outbox')
        self.assertTrue(self.desk.status()['pending'])
        masked = self.desk.config()['draft']
        self.assertEqual(masked['results']['webhook'], MASK)
        masked['obs']['port'] = 4455
        self.desk.edit(masked)
        path = self.root / 'results-profile.json'
        self.desk.save(path)
        saved = load_config(path)['results']
        self.assertFalse(saved['parse_names'])
        self.assertEqual(saved['webhook'], runtime.config['results']['webhook'])
        self.assertEqual(saved['output_directory'], str(self.root / 'exports'))
        self.assertFalse(saved['include_player_names'])
        self.assertTrue(saved['allow_replay_duplicates'])

    def test_saved_credentials_reveal_only_through_authenticated_scoped_endpoint(self):
        config = self.desk.config()['draft']
        config['obs']['password'] = 'reveal-test-password'
        config['results']['webhook'] = 'https://discord.com/api/webhooks/1/reveal-test'
        self.desk.edit(config)
        self.desk.close()
        self.desk = Desk(self.root, FakeRuntime)
        client = create_app(self.desk, 'test').test_client()
        headers = {'X-Desk-Token': 'test'}
        before = deepcopy(self.desk.draft)
        for path in ('obs.password', 'results.webhook'):
            section, key = path.split('.')
            args = {'path': path}
            self.assertEqual(client.post('/api/config/secret', json=args).status_code, 403)
            response = client.post('/api/config/secret', json=args, headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json, {'value': config[section][key]})
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.assertEqual(client.get('/api/config', headers=headers).json['draft'][section][key], MASK)
            self.assertEqual(client.post('/api/config/secret', json=args,
                             headers={**headers, 'Origin': 'https://example.com'}).status_code, 403)
        for path in ('ingest.rtsp.rtsp_url', 'obs', 'results', 'unknown', None):
            self.assertEqual(client.post('/api/config/secret', json={'path': path}, headers=headers).status_code, 400)
        self.assertEqual(self.desk.draft, before)
        self.assertIsNone(self.desk.runtime)
        config['obs']['password'] = ''
        config['results']['webhook'] = None
        self.desk.edit(config)
        for path in ('obs.password', 'results.webhook'):
            self.assertEqual(client.post('/api/config/secret', json={'path': path}, headers=headers).json, {'value': ''})

    def test_webhook_probe_uses_masked_draft_without_capture_or_applying_settings(self):
        config = self.desk.config()['draft']
        hook = 'https://discord.com/api/webhooks/1/private-test-token'
        config['results'].update(webhook=hook, enabled=False, discord=False)
        config['obs']['port'] = ''  # An unfinished unrelated edit must not block the probe.
        self.desk.edit(config)
        self.desk.edit(self.desk.config()['draft'])  # Roundtrip the masked URL.
        applied = deepcopy(self.desk.applied)
        client = create_app(self.desk, 'test').test_client()
        args = {'action': 'test_discord_webhook'}
        with patch('ddrcv.results.delivery.send_test_message') as sender:
            self.assertEqual(client.post('/api/action', json=args).status_code, 403)
            sender.assert_not_called()
            response = client.post('/api/action', json=args, headers={'X-Desk-Token': 'test'})
            self.assertEqual(response.status_code, 200, response.json)
            self.assertTrue(response.json['ok'])
            sender.assert_called_once_with(hook)
        self.assertIsNone(self.desk.runtime)
        self.assertEqual(self.desk.applied, applied)
        self.assertFalse(self.desk.draft['results']['discord'])

    def test_webhook_probe_rejects_empty_url_and_redacts_failures(self):
        client = create_app(self.desk, 'test').test_client()
        args = {'action': 'test_discord_webhook'}
        headers = {'X-Desk-Token': 'test'}
        with patch('ddrcv.results.delivery.send_test_message') as sender:
            response = client.post('/api/action', json=args, headers=headers)
            self.assertEqual(response.status_code, 400)
            self.assertIn('webhook URL', response.json['error'])
            sender.assert_not_called()
            hook = 'https://discord.com/api/webhooks/1/private-test-token'
            config = self.desk.config()['draft']
            config['results']['webhook'] = hook
            self.desk.edit(config)
            sender.side_effect = RuntimeError(f'Failed {hook}: private-test-token')
            response = client.post('/api/action', json=args, headers=headers)
            self.assertEqual(response.status_code, 400)
            self.assertNotIn('private-test-token', response.json['error'])

    def test_webhook_probe_does_not_block_runtime_controls(self):
        self.desk.start()
        config = self.desk.config()['draft']
        config['results']['webhook'] = 'https://discord.com/api/webhooks/1/test'
        self.desk.edit(config)
        entered, release = threading.Event(), threading.Event()
        def send(_):
            entered.set()
            release.wait(5)
        with patch('ddrcv.results.delivery.send_test_message', side_effect=send):
            worker = threading.Thread(target=self.desk.test_discord_webhook)
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                self.assertTrue(self.desk.lock.acquire(timeout=.5))
                self.desk.lock.release()
                self.assertTrue(self.desk.operations.acquire(timeout=.5))
                self.desk.operations.release()
                self.desk.stop()
                self.assertEqual(self.desk.runtime.stop_calls, 1)
            finally:
                release.set()
                worker.join(2)

    def test_invalid_results_controls_preserve_running_config(self):
        self.desk.start()
        previous = deepcopy(self.desk.applied)
        config = self.desk.config()['draft']
        config['results']['discord'] = True
        self.desk.edit(config)
        with self.assertRaisesRegex(ValueError, 'webhook'):
            self.desk.apply_results()
        self.assertEqual(self.desk.applied, previous)
        self.assertEqual(self.desk.runtime.stop_calls, 0)

    def test_results_controls_while_stopped_persist_without_capture(self):
        config = self.desk.config()['draft']
        config['results']['parse_names'] = False
        self.desk.edit(config)
        self.desk.apply_results()
        self.assertIsNone(self.desk.runtime)
        self.desk.close()
        self.desk = Desk(self.root, FakeRuntime)
        self.assertFalse(self.desk.applied['results']['parse_names'])
        self.assertFalse(self.desk.draft['results']['parse_names'])

    def test_invalid_config_or_failed_preflight_preserves_active_run(self):
        self.desk.start()
        runtime = self.desk.runtime
        config = self.desk.config()['draft']
        config['publish']['websocket']['port'] = -1
        self.desk.edit(config)
        with self.assertRaises(ValueError):
            self.desk.apply()
        self.assertEqual(runtime.stop_calls, 0)
        config['publish']['websocket']['port'] = 19006
        self.desk.edit(config)
        with patch.object(self.desk, '_prepare', side_effect=ValueError('bad template')):
            with self.assertRaisesRegex(ValueError, 'bad template'):
                self.desk.apply()
        self.assertEqual(runtime.stop_calls, 0)

    def test_restart_cannot_overlap_a_failed_stop(self):
        self.desk.start()
        runtime = self.desk.runtime
        runtime.stop = Mock(side_effect=RuntimeError('pending shutdown'))
        try:
            with self.assertRaisesRegex(RuntimeError, 'pending shutdown'):
                self.desk.apply()
            self.assertIs(self.desk.runtime, runtime)
        finally:
            runtime.stop = Mock()

    def test_logs_redact_current_and_previous_secrets(self):
        config = self.desk.config()['draft']
        config['obs']['password'] = 'private-password'
        self.desk.edit(config)
        self.desk.logs.emit(logging.LogRecord('test', logging.ERROR, '', 0, 'OBS failed: private-password rtsp://u:p@host/live', (), None))
        line = self.desk.logs.lines[-1]
        self.assertNotIn('private-password', line)
        self.assertNotIn('u:p@', line)

    def test_api_authentication_origin_and_explicit_exit(self):
        opened, shutdown = Mock(), Mock()
        app = create_app(self.desk, 'test-token', opened, shutdown)
        client = app.test_client()
        headers = {'X-Desk-Token': 'test-token'}
        self.assertEqual(client.get('/api/status').status_code, 403)
        self.assertEqual(client.get('/api/config', headers={**headers, 'Origin': 'https://example.com'}).status_code, 403)
        self.assertEqual(client.get('/api/status', headers=headers).status_code, 200)
        self.assertEqual(client.get('/stream.mjpg').status_code, 404)
        self.assertEqual(client.get('/api/frame', headers=headers).status_code, 204)
        self.assertEqual(client.post('/api/action', headers=headers, json={'action': 'exit'}).status_code, 400)
        shutdown.assert_not_called()
        client.post('/api/action', headers=headers, json={'action': 'exit', 'confirmed': True})
        shutdown.assert_called_once()
        client.post('/api/action', headers=headers, json={'action': 'open'})
        opened.assert_called_once()

    def test_cli_source_override_and_utf8_bom_use_shared_loader(self):
        from ddrcv.apps import driver_ddr as driver
        image = self.root / 'test.png'
        image.write_bytes(b'fixture')
        profile = self.root / 'bom.json'
        profile.write_text('{"ingest":{"video":{"path":"missing.mp4"}}}', encoding='utf-8-sig')
        with patch('sys.argv', ['driver', '--config', str(profile), '--image', str(image)]), patch.object(driver, 'main') as main:
            driver.cli()
        cfg = main.call_args.args[0]
        self.assertEqual(cfg['ingest']['image']['path'], str(image))
        self.assertFalse(cfg['obs']['enabled'])

    def test_invalid_draft_structure_does_not_break_saved_editor(self):
        previous = self.desk.config()
        with self.assertRaises(ValueError):
            self.desk.edit({'obs': None})
        self.assertEqual(self.desk.config(), previous)

    def test_duplicate_start_does_not_reset_scores(self):
        self.desk.start()
        runtime = self.desk.runtime
        with self.assertRaises(ValueError):
            self.desk.start()
        self.assertIs(self.desk.runtime, runtime)
        self.assertEqual(runtime.stop_calls, 0)

    def test_camera_switch_applies_only_ingest_and_preserves_other_drafts(self):
        self.desk.start()
        runtime = self.desk.runtime
        draft = self.desk.config()['draft']
        draft['ingest']['simple']['uri'] = 2
        draft['publish']['websocket']['port'] = -1  # Unfinished unrelated edit.
        draft['obs']['password'] = 'pending-password'
        self.desk.edit(draft)
        client = create_app(self.desk, 'test-token').test_client()
        self.assertEqual(client.post('/api/action', json={'action': 'switch_source'}).status_code, 403)
        response = client.post('/api/action', headers={'X-Desk-Token': 'test-token'}, json={'action': 'switch_source'})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertIs(self.desk.runtime, runtime)
        self.assertEqual(runtime.stop_calls, 0)
        self.assertEqual(runtime.config['ingest']['simple']['uri'], 2)
        self.assertNotEqual(runtime.config['publish']['websocket']['port'], -1)
        self.assertEqual(self.desk.applied['ingest'], self.desk.draft['ingest'])
        self.assertTrue(self.desk.config()['pending'])
        saved = json.loads(self.desk.state_file.read_text())
        self.assertEqual(saved['applied']['ingest']['simple']['uri'], 2)
        self.assertEqual(saved['draft']['obs']['password'], 'pending-password')

    def test_desk_stop_cancels_a_serialized_camera_switch(self):
        runtime = RuntimeTests().make_runtime(self.root)
        self.desk.runtime_factory = lambda config: runtime
        self.desk.start()
        wait_for(lambda: runtime.sequence > 3)
        draft = self.desk.config()['draft']
        draft['ingest']['simple']['uri'] = 2
        self.desk.edit(draft)
        candidate = Mock()
        candidate.get_frame.return_value = None
        errors = []
        def switch():
            try:
                self.desk.switch_source()
            except RuntimeError as error:
                errors.append(str(error))
        with patch.object(runtime, '_create_fetcher', return_value=candidate):
            thread = threading.Thread(target=switch)
            thread.start()
            wait_for(lambda: candidate.start.called)
            before = time.monotonic()
            self.desk.stop()
            thread.join(1)
            self.assertLess(time.monotonic() - before, 2)
            self.assertFalse(thread.is_alive())
            self.assertTrue(errors)
            self.assertEqual(runtime.phase, 'Stopped')
            self.assertNotEqual(self.desk.applied['ingest']['simple']['uri'], 2)

    def test_failed_camera_switch_preserves_applied_config(self):
        self.desk.start()
        previous = deepcopy(self.desk.applied)
        draft = self.desk.config()['draft']
        draft['ingest']['simple']['uri'] = 2
        self.desk.edit(draft)
        self.desk.runtime.switch_source = Mock(side_effect=ValueError('no frame'))
        with self.assertRaisesRegex(ValueError, 'no frame'):
            self.desk.switch_source()
        self.assertEqual(self.desk.applied, previous)
        self.assertTrue(self.desk.config()['pending'])

    def test_results_score_mode_alias_keeps_custom_filters_and_gui_edits(self):
        self.assertIsNone(validate_config({'score_mode':'money'})['score_filter']['max_per_frame'])
        cfg = validate_config({'score_mode':'money', 'score_filter': {'max_per_frame':36}})
        self.assertEqual(cfg['score_filter']['max_per_frame'], 36)
        self.assertEqual(cfg['score_mode'], 'ex')
        cfg['score_filter']['max_per_frame'] = None
        self.assertEqual(validate_config(cfg)['score_mode'], 'money')
        with self.assertRaises(ValueError):
            validate_config({'score_mode':'invalid'})
        legacy = validate_config({'results': {'screenshot_directory':str(self.root), 'processing_delay':5}})
        self.assertEqual(legacy['results']['outbox_directory'], str(self.root))
        self.assertEqual(legacy['results']['settling_seconds'], 5)

    def test_cli_score_mode_flag_overrides_profile_filter(self):
        from ddrcv.apps import driver_ddr as driver
        profile = self.root / 'mode.json'
        profile.write_text('{"score_filter":{"max_per_frame":36}}')
        with patch('sys.argv', ['driver', '--config', str(profile), '--score-mode', 'money']), patch.object(driver, 'main') as main, patch.object(driver, 'load_results_config', return_value={}):
            driver.cli()
        cfg = main.call_args.args[0]
        self.assertIsNone(cfg['score_filter']['max_per_frame'])
        self.assertEqual(cfg['score_mode'], 'money')

    def test_invalid_values_are_rejected(self):
        for patch_config in ({'score_filter': {'game_fps': float('nan')}},
                             {'publish': {'websocket': {'port': True}}},
                             {'obs': {'enabled': 'yes'}}, {'ingest': {'simple': {'uri': 0, 'width': 1920}}}):
            with self.subTest(config=patch_config), self.assertRaises(ValueError):
                validate_config(patch_config)


class RuntimeTests(unittest.TestCase):
    def make_runtime(self, tmp, fetcher=None, config=None):
        import numpy as np
        from ddrcv.apps.recognition_engine import RecognitionEngine
        from ddrcv.apps.tournament_runtime import TournamentRuntime
        overrides = deepcopy(config or {})
        results = overrides.setdefault('results', {})
        results.setdefault('enabled', False)
        results.setdefault('outbox_directory', str(Path(tmp) / 'outbox'))
        results.setdefault('output_directory', str(Path(tmp) / 'screenshots'))
        cfg = validate_config(overrides)
        matcher = Mock()
        matcher.match.return_value = ('song_playing', None)
        extractor = Mock()
        extractor.extract.return_value = {'data': {'p1_score': 120, 'p2_score': 150}}
        engine = RecognitionEngine(cfg, matcher=matcher, extractor=extractor)
        if fetcher is None:
            fetcher = Mock()
            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            def next_frame():
                time.sleep(.01)
                return frame
            fetcher.get_frame.side_effect = next_frame
        publisher = Mock()
        publisher.status = dict(running=True, clients=0)
        runtime = TournamentRuntime(cfg, engine, fetcher, publisher, logging.getLogger('test'), data_dir=tmp, desktop=True)
        return runtime

    def test_snapshots_do_not_drive_recognition_or_encode_without_request(self):
        import cv2
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.make_runtime(tmp)
            with patch('ddrcv.apps.tournament_runtime.cv2.imencode', wraps=cv2.imencode) as encode:
                runtime.start()
                try:
                    wait_for(lambda: runtime.sequence >= 35)
                    self.assertEqual(encode.call_count, 0)
                    image, meta = runtime.snapshot()
                    self.assertTrue(image.startswith(b'\xff\xd8'))
                    self.assertGreater(meta['sequence'], 0)
                    self.assertEqual(encode.call_count, 1)
                    sequence = runtime.sequence
                    wait_for(lambda: runtime.sequence > sequence + 5)
                    self.assertEqual(encode.call_count, 1)
                    self.assertEqual(runtime.status()['published']['score']['p1_score'], 120)
                finally:
                    runtime.stop()
            runtime.fetcher.stop.assert_called_once()
            runtime.publisher.stop.assert_called_once()

    def test_processing_capacity_excludes_source_waits_and_expires(self):
        from ddrcv.ingest.file_source import FileSource
        with tempfile.TemporaryDirectory() as tmp:
            source = Mock(spec=FileSource)
            source.kind, source.fps = 'video', 30
            runtime = self.make_runtime(tmp, fetcher=source)
            runtime.phase = 'Running'
            runtime.frame_wall = 10
            runtime.frame_times.extend((9.9, 9.95, 10))
            runtime.processing_times.extend(((7, 1), (9.9, .01), (9.95, .03), (10, .02)))
            with patch('ddrcv.apps.tournament_runtime.time.perf_counter', return_value=10):
                status = runtime.status()
            self.assertEqual(status['fps'], 20)
            self.assertEqual(status['processing_fps'], 50)
            self.assertEqual(status['processing_avg_ms'], 20)
            self.assertEqual(status['source_fps'], 30)
            with patch('ddrcv.apps.tournament_runtime.time.perf_counter', return_value=12.1):
                status = runtime.status()
            self.assertEqual(status['fps'], 0)
            self.assertIsNone(status['processing_fps'])
            self.assertIsNone(status['processing_avg_ms'])

    def test_processing_measurement_ignores_capture_wait_in_running_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.make_runtime(tmp)
            runtime.start()
            try:
                wait_for(lambda: runtime.sequence >= 35)
                status = runtime.status()
                self.assertGreater(status['processing_fps'], status['fps'])
                self.assertGreater(status['processing_avg_ms'], 0)
                self.assertIsNone(status['source_fps'])
            finally:
                runtime.stop()
            self.assertEqual(runtime.status()['fps'], 0)
            self.assertIsNone(runtime.status()['processing_fps'])

    def test_live_name_control_and_individual_score_reset_preserve_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.make_runtime(tmp)
            runtime.start()
            try:
                wait_for(lambda: runtime.sequence > 30)
                # Hold capture so the immediate reset can be inspected before another read.
                runtime.fetcher.get_frame.side_effect = lambda: None
                time.sleep(.03)
                generation = runtime.engine.session.song_generation
                p2 = runtime.engine.session.trackers[1].value
                runtime.control('reset_score', 0)
                self.assertEqual(runtime.status()['published']['score']['p1_score'], -1)
                self.assertIsNone(runtime.status()['score_age'][0])
                self.assertEqual(runtime.engine.session.trackers[1].value, p2)
                self.assertEqual(runtime.engine.session.song_generation, generation)
                reader = Mock()
                runtime.player_names.reader = reader
                runtime.control('names', True)
                runtime.control('names', False)
                self.assertFalse(runtime.config['player_names']['enabled'])
                self.assertEqual(runtime.engine.session.trackers[1].value, p2)
                runtime.fetcher.start.assert_called_once()
                runtime.fetcher.stop.assert_not_called()
            finally: runtime.stop()

    def test_results_deadline_runs_without_live_capture_frames(self):
        from ddrcv.results.service import ResultsService
        import numpy as np
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.make_runtime(tmp, config={'results': {'enabled':True}})
            reader = Mock()
            reader.read.side_effect = RuntimeError('no OCR')
            runtime.results_factory = lambda directory, config, notify: ResultsService(directory, config, reader=reader, notify=notify)
            runtime.start()
            try:
                wait_for(lambda: runtime.sequence > 3)
                runtime.fetcher.get_frame.side_effect = lambda: None
                time.sleep(.04)
                timestamp = time.monotonic()
                runtime.results.submit(np.zeros((720,1280,3), np.uint8), timestamp, 'song_result', 'song_result')
                runtime.results.active.config['deadline_seconds'] = .03
                wait_for(lambda: bool(runtime.results.status()['records']))
                self.assertTrue(runtime.results.status()['records'][0]['partial'])
            finally: runtime.stop()

    def test_capture_loss_marks_stale_without_resetting_scores(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.make_runtime(tmp)
            runtime.start()
            try:
                wait_for(lambda: runtime.sequence >= 35)
                runtime.fetcher.get_frame.side_effect = lambda: None
                wait_for(lambda: runtime.status()['capture_stale'], timeout=3)
                self.assertEqual(runtime.status()['published']['score']['p1_score'], 120)
                self.assertGreater(runtime.status()['score_age'][0], 1)
            finally:
                runtime.stop()

    def test_live_camera_handoff_keeps_session_services_and_resets_tracking(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.make_runtime(tmp)
            candidate = Mock()
            ready = threading.Event()
            new_frame = np.ones((720, 1280, 3), dtype=np.uint8)
            candidate.get_frame.side_effect = lambda: new_frame if ready.is_set() else None
            errors = []
            def switch():
                try:
                    runtime.switch_source({'simple': {'uri': 2}})
                except Exception as error:
                    errors.append(error)
            with patch.object(runtime, '_create_fetcher', return_value=candidate), patch.object(runtime.engine, 'reset', wraps=runtime.engine.reset) as reset:
                runtime.start()
                try:
                    wait_for(lambda: runtime.sequence >= 35)
                    old = runtime.fetcher
                    services = runtime.integrations.thread
                    thread = threading.Thread(target=switch)
                    thread.start()
                    wait_for(lambda: candidate.start.called)
                    before = runtime.sequence
                    wait_for(lambda: runtime.sequence > before + 5)
                    old.stop.assert_not_called()
                    self.assertEqual(runtime.status()['published']['score']['p1_score'], 120)
                    ready.set()
                    thread.join(3)
                    self.assertFalse(thread.is_alive())
                    self.assertFalse(errors)
                    self.assertIs(runtime.fetcher, candidate)
                    self.assertIs(runtime.integrations.thread, services)
                    self.assertEqual(runtime.phase, 'Running')
                    runtime.publisher.start.assert_called_once()
                    runtime.publisher.stop.assert_not_called()
                    old.stop.assert_called_once()
                    reset.assert_called_once()
                    self.assertEqual(runtime.source_revision, 1)
                    self.assertEqual(runtime.config['ingest']['simple']['uri'], 2)
                    messages = [c.args[0] for c in runtime.publisher.send_message.call_args_list]
                    self.assertTrue(any(m['state'] == 'unknown' and m.get('score') is None for m in messages[35:]))
                    wait_for(lambda: runtime.frame is new_frame)
                finally:
                    ready.set()
                    runtime.stop()
                candidate.stop.assert_called_once()

    def test_failed_camera_probe_keeps_old_capture_and_history(self):
        import numpy as np
        for frame in (None, np.zeros((480, 640, 3), dtype=np.uint8)):
            with self.subTest(valid_frame=frame is not None), tempfile.TemporaryDirectory() as tmp:
                runtime = self.make_runtime(tmp)
                candidate = Mock()
                candidate.get_frame.return_value = frame
                with patch.object(runtime, '_create_fetcher', return_value=candidate), patch.object(runtime.engine, 'reset', wraps=runtime.engine.reset) as reset:
                    runtime.start()
                    try:
                        wait_for(lambda: runtime.sequence >= 35)
                        old = runtime.fetcher
                        with self.assertRaises(ValueError):
                            runtime.switch_source({'simple': {'uri': 2}}, timeout=.1)
                        self.assertIs(runtime.fetcher, old)
                        old.stop.assert_not_called()
                        candidate.stop.assert_called_once()
                        reset.assert_not_called()
                        self.assertEqual(runtime.status()['published']['score']['p1_score'], 120)
                        self.assertTrue(runtime.status()['source_error'])
                        self.assertEqual(runtime.source_revision, 0)
                    finally:
                        runtime.stop()

    def test_stop_cancels_camera_probe_and_releases_both_captures(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.make_runtime(tmp)
            candidate = Mock()
            candidate.get_frame.return_value = None
            errors = []
            def switch():
                try:
                    runtime.switch_source({'simple': {'uri': 2}}, timeout=30)
                except RuntimeError as error:
                    errors.append(str(error))
            with patch.object(runtime, '_create_fetcher', return_value=candidate):
                runtime.start()
                wait_for(lambda: runtime.sequence > 3)
                old = runtime.fetcher
                thread = threading.Thread(target=switch)
                thread.start()
                wait_for(lambda: candidate.start.called)
                before = time.monotonic()
                runtime.stop()
                thread.join(1)
                self.assertLess(time.monotonic() - before, 2)
                self.assertFalse(thread.is_alive())
                self.assertTrue(errors)
                old.stop.assert_called_once()
                candidate.stop.assert_called_once()
                runtime.publisher.stop.assert_called_once()

    def test_blocked_candidate_cleanup_prevents_capture_worker_accumulation(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.make_runtime(tmp)
            release = threading.Event()
            worker = threading.Thread(target=release.wait, daemon=True)
            candidate = Mock()
            candidate.thread = worker
            candidate.start.side_effect = worker.start
            candidate.get_frame.return_value = None
            with patch.object(runtime, '_create_fetcher', return_value=candidate) as factory:
                runtime.start()
                try:
                    wait_for(lambda: runtime.sequence > 3)
                    with self.assertRaises(ValueError):
                        runtime.switch_source({'simple': {'uri': 2}}, timeout=.05)
                    with self.assertRaisesRegex(RuntimeError, 'still cleaning up'):
                        runtime.switch_source({'simple': {'uri': 3}})
                    factory.assert_called_once()
                    self.assertEqual(len(runtime.retired_captures), 1)
                    with self.assertRaisesRegex(RuntimeError, 'cleanup is still pending'):
                        runtime.stop()
                finally:
                    release.set()
                    worker.join(1)
                    runtime.stop()

    def test_reselecting_current_camera_does_not_open_or_reset_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.make_runtime(tmp)
            with patch.object(runtime, '_create_fetcher') as factory, patch.object(runtime.engine, 'reset', wraps=runtime.engine.reset) as reset:
                runtime.start()
                try:
                    wait_for(lambda: runtime.sequence > 3)
                    runtime.switch_source(runtime.config['ingest'])
                    factory.assert_not_called()
                    reset.assert_not_called()
                finally:
                    runtime.stop()

    def test_optional_integration_failure_does_not_stop_recognition(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.make_runtime(tmp, config={'obs': {'enabled': True}, 'renderer': {'enabled': True}})
            with patch.object(runtime.integrations.obs, 'connect', side_effect=ValueError('offline')), patch.object(runtime.integrations, '_start_renderer', side_effect=ValueError('missing renderer')):
                runtime.start()
                try:
                    wait_for(lambda: runtime.sequence > 10)
                    self.assertEqual(runtime.phase, 'Running')
                    self.assertIn('missing renderer', runtime.status()['renderer']['error'])
                finally:
                    runtime.stop()

    def test_publisher_conflict_never_opens_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self.make_runtime(tmp)
            runtime.publisher.start.side_effect = RuntimeError('port occupied')
            runtime.start()
            wait_for(runtime.finished.is_set)
            self.assertEqual(runtime.phase, 'Error')
            runtime.fetcher.start.assert_not_called()
            runtime.fetcher.stop.assert_called_once()


class LifecycleTests(unittest.TestCase):
    def test_exit_confirmation_returns_to_tray_and_cancel_allows_retry(self):
        exiting, entered, answer = threading.Event(), threading.Event(), threading.Event()
        caller = threading.get_ident()
        worker_ids = []
        def confirm():
            worker_ids.append(threading.get_ident())
            entered.set()
            answer.wait(3)
            return False
        callback = ExitConfirmation(exiting, confirm)
        before = time.monotonic()
        callback()
        self.assertLess(time.monotonic() - before, .5)
        try:
            self.assertTrue(entered.wait(1))
            first = callback.thread
            callback()  # Repeated tray click cannot create another modal window.
            self.assertIs(callback.thread, first)
            self.assertNotEqual(worker_ids, [caller])
            self.assertFalse(exiting.is_set())
        finally:
            answer.set()
            callback.thread.join(1)
        self.assertFalse(exiting.is_set())
        callback.confirm = lambda: True
        callback()
        callback.thread.join(1)
        self.assertTrue(exiting.is_set())
        confirmed = callback.thread
        callback()
        self.assertIs(callback.thread, confirmed)

    def test_failed_exit_dialog_leaves_application_running_and_allows_retry(self):
        exiting = threading.Event()
        callback = ExitConfirmation(exiting, Mock(side_effect=OSError('dialog unavailable')))
        with self.assertLogs('ddrcv.desktop.host', level='ERROR'):
            callback()
            callback.thread.join(1)
        self.assertFalse(exiting.is_set())
        callback.confirm = lambda: False
        callback()
        callback.thread.join(1)
        self.assertFalse(callback.pending.locked())

    def test_instance_lock_releases_after_owner_closes(self):
        with tempfile.TemporaryDirectory() as tmp:
            owner, second = Instance(tmp), Instance(tmp)
            self.assertTrue(owner.acquire())
            self.assertFalse(second.acquire())
            owner.close()
            self.assertTrue(second.acquire())
            second.close()

    def test_panel_reuses_live_process_and_relaunches_after_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            p1, p2 = Mock(), Mock()
            p1.poll.return_value = None
            p2.poll.return_value = None
            panel = Panel('http://127.0.0.1:1234', 'token', tmp, {})
            with patch('ddrcv.desktop.host.subprocess.Popen', side_effect=[p1, p2]) as launch:
                panel.open()
                panel.open()
                self.assertEqual(launch.call_count, 1)
                self.assertIn('focus', p1.stdin.write.call_args.args[0])
                p1.poll.return_value = 1
                panel.open()
                self.assertEqual(launch.call_count, 2)
                panel.close()
                self.assertIn('exit', p2.stdin.write.call_args.args[0])
            self.assertTrue(panel.closed)

class RecoveryTests(unittest.TestCase):
    def test_retry_sleep_is_interruptible_for_live_sources(self):
        from ddrcv.ingest.simple_frame_fetcher import SimpleFrameFetcher
        from ddrcv.ingest.rtsp_frame_fetcher import RTSPFrameFetcher
        for factory in (lambda: SimpleFrameFetcher(0, reconnect_delay=30),
                        lambda: RTSPFrameFetcher('rtsp://invalid.test/stream', reconnect_delay=30)):
            with self.subTest(source=factory):
                source = factory()
                attempted = threading.Event()
                source.connect = lambda: attempted.set()
                source.start()
                self.assertTrue(attempted.wait(1))
                before = time.monotonic()
                source.stop()
                self.assertLess(time.monotonic() - before, 1)

    def test_results_save_and_delivery_do_not_stall_recognition(self):
        from ddrcv.results.service import ResultsService
        with tempfile.TemporaryDirectory() as tmp:
            runtime = RuntimeTests().make_runtime(tmp, config={'results': {
                'enabled': True, 'outbox_directory': str(Path(tmp) / 'outbox'),
                'discord': True, 'webhook': 'https://discord.com/api/webhooks/1/test',
                'settling_seconds': .01, 'min_frames': 1, 'confirmation_seconds': .01}})
            runtime.engine.matcher.match.return_value = ('song_result', None)
            entered, release = threading.Event(), threading.Event()
            reader = Mock()
            reader.read.return_value = [dict(name='P1', score=120), dict(name='P2', score=150)]
            def sender(*args):
                entered.set()
                release.wait(3)
                return dict(message_id='123')
            runtime.results_factory = lambda directory, config, notify: ResultsService(
                directory, config, reader=reader, sender=sender, notify=notify)
            runtime.start()
            try:
                self.assertTrue(entered.wait(2))
                before = runtime.sequence
                wait_for(lambda: runtime.sequence > before + 8)
                runtime.fetcher.get_frame.side_effect = lambda: None
                time.sleep(.05)
                before = runtime.sequence
                release.set()
                wait_for(lambda: runtime.publisher.send_message.call_args.args[0].get(
                    'results', {}).get('latest', {}).get('delivery', {}).get('state') == 'sent')
                self.assertEqual(runtime.sequence, before)
                record = runtime.results.status()['records'][0]
                self.assertTrue(Path(record['screenshot_path']).is_file())
            finally:
                release.set()
                runtime.stop()

    def test_results_start_lazily_and_reset_on_camera_switch_without_restarting(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as tmp:
            runtime = RuntimeTests().make_runtime(tmp, config={'results': {'enabled': True},
                                                             'score_filter': {'max_per_frame': None}})
            service = Mock()
            service.feed_status.return_value = {'phase': 'idle'}
            factory = Mock(return_value=service)
            runtime.results_factory = factory
            factory.assert_not_called()
            candidate = Mock()
            candidate.get_frame.return_value = np.zeros((720, 1280, 3), dtype=np.uint8)
            runtime.start()
            try:
                wait_for(lambda: runtime.sequence > 3)
                first_identity = service.reset.call_args.args[0]
                with patch.object(runtime, '_create_fetcher', return_value=candidate):
                    runtime.switch_source({'simple': {'uri': 2}})
                factory.assert_called_once()
                self.assertEqual(service.reset.call_count, 2)
                self.assertNotEqual(service.reset.call_args.args[0], first_identity)
                self.assertEqual(service.reset.call_args.args[2], 'money')
                service.finish.assert_called_once()
                service.close.assert_not_called()
            finally:
                runtime.stop()
            service.close.assert_called_once()

    def test_results_controls_start_lazily_and_reconfigure_without_gameplay_reset(self):
        from ddrcv.results.service import ResultsService
        with tempfile.TemporaryDirectory() as tmp:
            runtime = RuntimeTests().make_runtime(tmp, config={'results': {'outbox_directory': str(Path(tmp) / 'outbox')}})
            reader = Mock()
            reader.read.return_value = [dict(name='P1', score=120), dict(name='P2', score=150)]
            factory = Mock(side_effect=lambda directory, config, notify: ResultsService(
                directory, config, reader=reader, sender=Mock(), notify=notify))
            runtime.results_factory = factory
            runtime.start()
            try:
                wait_for(lambda: runtime.sequence > 30)
                before = runtime.sequence
                scores = deepcopy(runtime.engine.session.info['score'])
                with patch.object(runtime.engine, 'reset', wraps=runtime.engine.reset) as reset:
                    runtime.configure_results(dict(enabled=True, parse_names=False))
                    service = runtime.results
                    self.assertIsNotNone(service)
                    runtime.configure_results(dict(discord=True, webhook='https://discord.com/api/webhooks/1/test'))
                    self.assertTrue(service.outbox.enabled)
                    runtime.configure_results(dict(discord=False, parse_names=True))
                    self.assertIs(runtime.results, service)
                    self.assertFalse(service.outbox.enabled)
                    self.assertTrue(service.config['parse_names'])
                    runtime.configure_results(dict(screenshots_only=True))
                    self.assertTrue(service.config['screenshots_only'])
                    self.assertTrue(service.config['parse_names'])
                    runtime.configure_results(dict(screenshots_only=False))
                    self.assertFalse(service.config['screenshots_only'])
                    runtime.configure_results(dict(allow_replay_duplicates=True))
                    self.assertTrue(service.status()['allow_replay_duplicates'])
                    runtime.configure_results(dict(allow_replay_duplicates=False))
                    self.assertFalse(service.status()['allow_replay_duplicates'])
                    reset.assert_not_called()
                wait_for(lambda: runtime.sequence > before + 4)
                self.assertEqual(runtime.engine.session.info['score'], scores)
                factory.assert_called_once()
                runtime.publisher.start.assert_called_once()
                runtime.fetcher.start.assert_called_once()
                runtime.fetcher.stop.assert_not_called()
            finally:
                runtime.stop()

    def test_failed_live_results_start_keeps_capture_and_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = RuntimeTests().make_runtime(tmp)
            runtime.results_factory = Mock(side_effect=OSError('Outbox unavailable'))
            runtime.start()
            try:
                wait_for(lambda: runtime.sequence > 3)
                with self.assertRaisesRegex(OSError, 'Outbox unavailable'):
                    runtime.configure_results(dict(enabled=True))
                self.assertFalse(runtime.config['results']['enabled'])
                self.assertIsNone(runtime.results)
                before = runtime.sequence
                wait_for(lambda: runtime.sequence > before + 3)
                self.assertEqual(runtime.phase, 'Running')
            finally:
                runtime.stop()

    def test_renderer_service_controls_only_its_owned_process(self):
        from ddrcv.apps.tournament_integrations import Integrations
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'apps').mkdir()
            (root / 'apps/tbd5.py').write_text('')
            cfg = normalize_config({'renderer': {'path': str(root)}})
            service = Integrations(cfg, root / 'state')
            proc = Mock()
            proc.poll.return_value = None
            with patch('ddrcv.apps.tournament_integrations.subprocess.Popen', return_value=proc) as launch:
                service._start_renderer()
                service._start_renderer()
                self.assertEqual(launch.call_count, 1)
                self.assertIn('--stop-file', launch.call_args.args[0])
                service._stop_renderer()
                self.assertTrue(service.stop_file.exists())
                proc.wait.assert_called_once()
                proc.terminate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
