"""Run with the tournament Python environment; no camera or OBS server required."""

import asyncio
import copy
import importlib.util
import json
import logging
import socket
import time
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

HAS_RUNTIME = all(importlib.util.find_spec(name) for name in
                  ('cv2', 'numpy', 'flask', 'websockets', 'obsws_python', 'discord_webhook'))


@unittest.skipUnless(HAS_RUNTIME, 'Requires the tournament runtime dependencies')
class DriverTests(unittest.TestCase):
    def run_driver(self, tags, shape=(720, 1280, 3)):
        import numpy as np
        from ddrcv.apps import driver_ddr_tbd5 as driver
        frame = np.zeros(shape, dtype=np.uint8)
        fetcher = Mock()
        fetcher.get_frame.side_effect = [frame] * len(tags) + [KeyboardInterrupt()]
        matcher = Mock()
        matcher.match.side_effect = [(tag, None) for tag in tags]
        extractor = Mock()
        extractor.extract.return_value = {'data': {'p1_score': 100, 'p2_score': 120}}
        publisher = Mock()
        messages = []
        publisher.send_message.side_effect = lambda message: messages.append(copy.deepcopy(message))
        clock = SimpleNamespace(monotonic=Mock(side_effect=[i * .04 for i in range(len(tags))]), sleep=Mock())
        config = {'state': {}, 'score_extractor': {'glyph_dir': None}, 'ingest': {},
                  'publish': {}, 'results': {'enabled': False}, 'driver_debug': {'render_frame': False}}
        with ExitStack() as stack:
            stack.enter_context(patch.object(driver, 'StateRotation', return_value=matcher))
            stack.enter_context(patch.object(driver, 'ScoreExtractor', return_value=extractor))
            stack.enter_context(patch.object(driver, 'create_frame_fetcher', return_value=fetcher))
            stack.enter_context(patch.object(driver, 'create_publisher', return_value=publisher))
            stack.enter_context(patch.object(driver, 'time', clock))
            try:
                driver.main(config, logging.getLogger('driver-test'))
            finally:
                fetcher.stop.assert_called_once()
                publisher.stop.assert_called_once()
        return messages, extractor

    def test_driver_publishes_confirmed_states_and_retains_final_score(self):
        messages, extractor = self.run_driver(['song_select'] * 10 + ['song_playing'] * 20 + ['song_result'] * 20)
        self.assertEqual(messages[0]['state'], 'unknown')
        self.assertEqual(messages[9]['state'], 'song_select')
        self.assertEqual(messages[29]['state'], 'song_playing')
        self.assertEqual(messages[-1]['state'], 'song_result')
        self.assertEqual(messages[-1]['score'], {'p1_score': 100, 'p2_score': 120})
        self.assertLess(extractor.extract.call_count, 20)

    def test_wrong_capture_size_fails_with_actionable_error(self):
        with self.assertRaisesRegex(ValueError, 'Expected 1280x720 capture'):
            self.run_driver(['song_playing'], (1080, 1920, 3))

    def test_both_entry_points_share_the_same_driver(self):
        from ddrcv.apps import driver_ddr_tbd5, driver_ddr_tbd5_v2
        self.assertIs(driver_ddr_tbd5.main, driver_ddr_tbd5_v2.main)

    def test_custom_glyph_directory_from_json(self):
        from pathlib import Path
        from ddrcv.score.score_extractor import ScoreExtractor
        glyph_dir = str(Path(__file__).resolve().parents[1] / 'ddrcv' / 'score' / 'fonts' / 'World2')
        extractor = ScoreExtractor(glyph_dir)
        self.assertEqual(len(extractor.p1_extractor.detector.glyphs), 10)


@unittest.skipUnless(HAS_RUNTIME, 'Requires the tournament runtime dependencies')
class DeskTests(unittest.TestCase):
    def setUp(self):
        from flask import Flask
        from apps.obs.app import obs_controller as controller
        from apps.obs.scene_policy import ScenePolicy
        self.controller = controller
        controller.manual_override = False
        controller.current_state = {'state': 'unknown'}
        self.obs = Mock()
        self.obs.get_current_program_scene.return_value = SimpleNamespace(current_program_scene_name='Commentator')
        app = Flask(__name__)
        app.config.update(OBS_HOST='localhost', OBS_PORT=4455, OBS_PASSWORD='',
                          STATE_SERVER_URI='ws://localhost:9000', state_handler=ScenePolicy())
        with patch.object(controller, 'ReqClient', return_value=self.obs), \
                patch.object(controller, 'start_polling'), patch.object(controller, 'start_websocket_connection'):
            app.register_blueprint(controller.obs_blueprint, url_prefix='/obs')
        self.client = app.test_client()

    def test_manual_scene_choice_pauses_automation_and_resume_converges(self):
        response = self.client.post('/obs/switch_scene', json={'scene_name': 'Break'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['manual_override'])
        self.controller.receive_state({'state': 'song_playing'})
        self.obs.set_current_program_scene.assert_called_once_with('Break')
        response = self.client.post('/obs/toggle_override')
        self.assertFalse(response.json['manual_override'])
        self.controller.receive_state({'state': 'song_playing'})
        self.assertEqual(self.obs.set_current_program_scene.call_args.args, ('Gameplay',))

    def test_status_contains_game_state_and_connection_intent(self):
        self.controller.receive_state({'state': 'song_result'})
        stream = self.controller.event_stream()
        event = json.loads(next(stream).removeprefix('data: '))
        stream.close()
        self.assertEqual(event['state'], 'song_result')
        self.assertIn('ws_enabled', event)

    def test_operator_page_renders(self):
        self.obs.get_scene_list.return_value = SimpleNamespace(scenes=[{'sceneName': 'Gameplay'}])
        response = self.client.get('/obs/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Pause automation', response.data)


@unittest.skipUnless(HAS_RUNTIME, 'Requires the tournament runtime dependencies')
class PublisherTests(unittest.TestCase):
    def test_late_clients_get_snapshot_without_another_frame(self):
        import websockets
        from ddrcv.publish.websocket_publisher import WebSocketPublisher
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        publisher = WebSocketPublisher(host='127.0.0.1', port=port, delay=.02)
        message = {'state': 'song_playing', 'score': {'p1_score': 123, 'p2_score': 456}}
        publisher.send_message(message)
        publisher.start()

        async def receive_late():
            deadline = time.monotonic() + 10
            while True:
                try:
                    async with websockets.connect(f'ws://127.0.0.1:{port}') as client:
                        self.assertEqual(json.loads(await asyncio.wait_for(client.recv(), 2)), message)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise
                    await asyncio.sleep(.05)
            # Let the broadcaster consume the version before a second client
            # connects. Neither connection should depend on a new frame.
            await asyncio.sleep(.1)
            async with websockets.connect(f'ws://127.0.0.1:{port}') as client:
                self.assertEqual(json.loads(await asyncio.wait_for(client.recv(), 2)), message)
        try:
            asyncio.run(receive_late())
        finally:
            publisher.stop()


if __name__ == '__main__':
    unittest.main()
