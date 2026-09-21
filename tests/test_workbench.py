"""Rehearsal acceptance checks; uses temporary media and fake OBS, no hardware."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

HAS_RUNTIME = all(importlib.util.find_spec(name) for name in ('cv2', 'numpy', 'flask', 'websockets', 'obsws_python'))
ROOT = Path(__file__).resolve().parents[1]


def wait_until(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError('Timed out waiting for playback')
        time.sleep(.01)


def make_video(path, count=8, fps=20, size=(1280, 720)):
    import cv2
    import numpy as np
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), fps, size)
    if not writer.isOpened():
        raise RuntimeError('Test video encoder unavailable')
    for i in range(count):
        frame = np.full((size[1], size[0], 3), (i * 20) % 256, dtype=np.uint8)
        writer.write(frame)
    writer.release()


def make_engine():
    from ddrcv.apps.recognition_engine import RecognitionEngine
    matcher = Mock()
    matcher.match.return_value = ('song_playing', None)
    extractor = Mock()
    def extract(frame, debug=False):
        value = int(frame[0, 0, 0]) * 100
        return {'data': {'p1_score': value, 'p2_score': value + 3}, 'debug': {'p1_debug': [], 'p2_debug': []}}
    extractor.extract.side_effect = extract
    return RecognitionEngine({'score_filter': {'max_per_frame': None}}, matcher=matcher, extractor=extractor)


@unittest.skipUnless(HAS_RUNTIME, 'Requires rehearsal dependencies')
class SourceTests(unittest.TestCase):
    def test_sequential_read_seek_and_eof(self):
        from ddrcv.ingest.file_source import FileSource
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'clip.avi'
            make_video(path)
            source = FileSource(path)
            packets = []
            while (packet := source.read()) is not None:
                packets.append(packet)
            self.assertEqual([p.index for p in packets], list(range(8)))
            self.assertTrue(source.ended)
            self.assertAlmostEqual(packets[4].timestamp, .2, places=3)
            source.seek(.1)
            packet = source.read()
            self.assertEqual(packet.index, 2)
            self.assertAlmostEqual(packet.timestamp, .1, places=3)
            self.assertLess(abs(int(packet.image[0, 0, 0]) - 40), 3)
            source.stop()

    def test_resize_is_explicit_and_wrong_aspect_fails(self):
        import numpy as np
        from ddrcv.ingest.file_source import normalize_frame
        original = np.zeros((720, 1280, 3), dtype=np.uint8)
        self.assertIs(normalize_frame(original), original)
        with self.assertRaisesRegex(ValueError, 'Enable resize'):
            normalize_frame(np.zeros((1080, 1920, 3), dtype=np.uint8))
        self.assertEqual(normalize_frame(np.zeros((90, 160, 3), dtype=np.uint8), True).shape, original.shape)
        with self.assertRaisesRegex(ValueError, '16:9'):
            normalize_frame(np.zeros((480, 640, 3), dtype=np.uint8), True)

    def test_missing_or_invalid_files_are_actionable(self):
        from ddrcv.ingest.file_source import FileSource
        with self.assertRaisesRegex(ValueError, 'does not exist'):
            FileSource('/does/not/exist.mp4')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bad.png'
            path.write_text('not an image')
            with self.assertRaisesRegex(ValueError, 'cannot be decoded'):
                FileSource(path, 'image')

@unittest.skipUnless(HAS_RUNTIME, 'Requires rehearsal dependencies')
class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        from ddrcv.workbench.controller import Workbench
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'clip.avi'
        make_video(self.path)
        self.wb = Workbench(Path(self.temp.name) / 'settings', engine=make_engine(), start_publisher=False)

    def tearDown(self):
        self.wb.close()
        self.temp.cleanup()

    def open(self):
        self.wb.submit('open', kind='video', path=str(self.path))

    def test_pause_step_seek_and_end_hold(self):
        self.open()
        self.assertEqual(self.wb.status()['diagnostics']['frame_index'], 0)
        time.sleep(.1)
        self.assertEqual(self.wb.status()['diagnostics']['frame_index'], 0)
        self.wb.submit('step')
        self.assertEqual(self.wb.status()['diagnostics']['frame_index'], 1)
        epoch = self.wb.epoch
        self.wb.submit('seek', seconds=.25)
        self.assertEqual(self.wb.epoch, epoch + 1)
        self.assertEqual(self.wb.status()['published']['state'], 'unknown')
        self.assertIsNone(self.wb.status()['published']['score'])
        self.wb.submit('play')
        wait_until(lambda: self.wb.status()['phase'] == 'Ended')
        sequence = self.wb.sequence
        time.sleep(.1)
        self.assertEqual(sequence, self.wb.sequence)
        self.assertEqual(self.wb.packet.index, 7)

    def test_loop_resets_history_and_speed_is_preserved(self):
        self.open()
        self.wb.submit('playback', speed=2, loop=True)
        epoch = self.wb.epoch
        self.wb.submit('play')
        wait_until(lambda: self.wb.epoch > epoch)
        self.wb.submit('pause')
        self.assertEqual(self.wb.status()['speed'], 2)
        self.assertIsNone(self.wb.status()['published']['score'])

    def test_playback_paces_every_frame_and_results_do_not_depend_on_speed(self):
        results, durations = [], []
        original = self.wb.engine.process
        for speed in (.25, .5, 1, 2):
            observations = []
            def record(*args, **kwargs):
                result = original(*args, **kwargs)
                observations.append(result)
                return result
            self.wb.engine.process = record
            self.open()
            self.wb.submit('playback', speed=speed)
            started = time.monotonic()
            self.wb.submit('play')
            wait_until(lambda: self.wb.status()['phase'] == 'Ended', timeout=5)
            durations.append(time.monotonic() - started)
            self.assertEqual([item['frame_index'] for item in observations], list(range(8)))
            results.append(observations)
        self.assertGreater(durations[0], durations[-1] * 2)
        self.assertGreater(durations[0], 1.2)
        for result in results[1:]:
            self.assertEqual(result, results[0])

    def test_image_is_stateless_and_does_not_publish_scores(self):
        import cv2
        import numpy as np
        path = Path(self.temp.name) / 'still.png'
        cv2.imwrite(str(path), np.zeros((720, 1280, 3), dtype=np.uint8))
        self.wb.submit('open', kind='image', path=str(path))
        status = self.wb.status()
        self.assertTrue(status['diagnostics']['stateless'])
        self.assertEqual(status['published']['state'], 'unknown')
        self.assertIsNone(status['published']['score'])
        self.assertEqual(status['diagnostics']['decisions']['p1_score'], 'diagnostic_only')

    def test_normal_speed_sustains_30fps_without_skipping_frames(self):
        make_video(self.path, count=45, fps=30)
        observations = []
        original = self.wb.engine.process
        def record(*args, **kwargs):
            result = original(*args, **kwargs)
            observations.append(result['frame_index'])
            return result
        self.wb.engine.process = record
        self.open()
        started = time.perf_counter()
        self.wb.submit('play')
        wait_until(lambda: self.wb.status()['phase'] == 'Ended')
        elapsed = time.perf_counter() - started
        self.assertEqual(observations, list(range(45)))
        # Allow scheduling noise, but catch the former Windows ~21 fps cadence.
        self.assertGreater(elapsed, 1.35)
        self.assertLess(elapsed, 1.85)

    def test_rgb_conversion_preserves_recognition_pixels(self):
        import numpy as np
        frame = np.random.default_rng(0).integers(0, 256, (720, 1280, 3), dtype=np.uint8)
        original = frame.copy()
        self.wb.engine.process(frame, 0, diagnostics=True)
        passed_rgb = self.wb.engine.matcher.match.call_args.args[0]
        np.testing.assert_array_equal(passed_rgb, frame[..., ::-1])
        np.testing.assert_array_equal(frame, original)

    def test_money_and_ex_modes_use_the_same_session(self):
        self.open()
        for _ in range(6):
            self.wb.submit('step')
        money = self.wb.status()['published']['score']['p1_score']
        self.assertGreater(money, 0)
        self.wb.submit('score_mode', mode='ex')
        self.assertIsNone(self.wb.status()['published']['score'])
        self.assertEqual(self.wb.engine.session.trackers[0].max_per_frame, 12)
        self.wb.submit('score_mode', mode='money')
        self.assertIsNone(self.wb.engine.session.trackers[0].max_per_frame)

    def test_simulation_excludes_source_and_can_reopen_video(self):
        self.open()
        self.wb.submit('simulate', state='song_playing', p1_score=1000000, p2_present=False)
        self.assertIsNone(self.wb.source)
        self.assertIsNone(self.wb.frame)
        self.assertEqual(self.wb.message['score'], {'p1_score': 1000000, 'p2_score': None})
        self.open()
        self.assertEqual(self.wb.message['state'], 'unknown')

    def test_camera_switch_keeps_integrations_and_resets_file_history(self):
        import numpy as np
        self.open()
        for _ in range(6):
            self.wb.submit('step')
        self.assertIsNotNone(self.wb.message['score'])
        publisher, obs, old_source = self.wb.publisher, self.wb.obs, self.wb.source
        camera = Mock()
        frames = [np.zeros((720, 1280, 3), dtype=np.uint8)]
        camera.get_frame.side_effect = lambda: frames.pop() if frames else None
        with patch('ddrcv.workbench.controller.SimpleFrameFetcher', return_value=camera):
            self.wb.submit('open', kind='camera', path='2')
            wait_until(lambda: self.wb.status()['source'].get('width') == 1280)
        self.assertIs(self.wb.publisher, publisher)
        self.assertIs(self.wb.obs, obs)
        self.assertIsNone(old_source.capture)
        self.assertIsNone(self.wb.message['score'])
        self.assertEqual(self.wb.message['state'], 'unknown')
        self.wb.submit('stop')
        camera.stop.assert_called_once()

    def test_invalid_source_leaves_open_video_usable(self):
        self.open()
        source = self.wb.source
        with self.assertRaisesRegex(ValueError, 'does not exist'):
            self.wb.submit('open', kind='video', path=str(self.path.with_name('missing.avi')))
        self.assertIs(self.wb.source, source)
        self.wb.submit('step')
        self.assertEqual(self.wb.packet.index, 1)
        self.assertIsNone(self.wb.error)

    def test_snapshot_frame_and_metadata_are_atomic_and_redacted(self):
        import cv2
        self.open()
        self.wb.submit('step')
        self.wb.settings['obs']['password'] = 'never-export-this'
        folder = Path(self.wb.submit('snapshot')['path'])
        doc = (folder / 'diagnostics.json').read_text()
        self.assertNotIn('never-export-this', doc)
        data = json.loads(doc)
        self.assertEqual(data['sequence'], self.wb.sequence)
        self.assertEqual(data['diagnostics']['frame_index'], 1)
        self.assertTrue((cv2.imread(str(folder / 'frame.png')) == self.wb.frame).all())
        self.assertEqual(cv2.imread(str(folder / 'p1_crop.png')).shape, (45, 240, 3))
        self.assertEqual(self.wb.image('clean')[1], self.wb.image('annotated')[1])

    def test_http_controls_and_clean_view(self):
        from ddrcv.workbench.app import create_app
        app = create_app(self.wb)
        client = app.test_client()
        self.assertEqual(client.get('/').status_code, 200)
        self.assertIn(b'/stream.mjpg', client.get('/video').data)
        self.assertEqual(client.post('/api/action', json={'action': 'pause'}).status_code, 403)
        response = client.post('/api/action', json={'action':'open','kind':'video','path':str(self.path)}, headers={'X-Rehearsal':'1'})
        self.assertEqual(response.status_code, 200, response.json)
        image = client.get('/frame.jpg')
        self.assertEqual(image.mimetype, 'image/jpeg')
        self.assertEqual(int(image.headers['X-Frame-Sequence']), self.wb.sequence)
        self.assertEqual(client.get('/api/status').json['settings']['score_mode'], 'money')

    def test_settings_survive_restart(self):
        from ddrcv.workbench.controller import Workbench
        self.open()
        self.wb.submit('score_mode', mode='ex')
        self.wb.close()
        self.wb = Workbench(Path(self.temp.name) / 'settings', engine=make_engine(), start_publisher=False)
        self.assertEqual(self.wb.settings['source']['path'], str(self.path))
        self.assertEqual(self.wb.settings['score_mode'], 'ex')
        self.assertFalse(self.wb.playing)

    def test_stream_views_follow_steps_without_advancing_paused_parser(self):
        from ddrcv.workbench.app import create_app
        self.open()
        client = create_app(self.wb).test_client()
        self.assertEqual(client.get('/stream.mjpg?view=invalid').status_code, 400)
        clean = client.get('/stream.mjpg', buffered=False)
        monitored = client.get('/stream.mjpg?view=monitored', buffered=False)
        try:
            sequence = self.wb.sequence
            header = b'X-Frame-Sequence: ' + str(sequence).encode() + b'\r\n'
            self.assertIn(header, next(clean.response))
            self.assertIn(header, next(monitored.response))
            self.assertFalse(self.wb.wait_for_frame(sequence, timeout=.05))
            self.wb.submit('step')
            header = b'X-Frame-Sequence: ' + str(self.wb.sequence).encode() + b'\r\n'
            self.assertIn(header, next(clean.response))
            self.assertIn(header, next(monitored.response))
            self.assertEqual(self.wb.packet.index, 1)
            self.assertFalse(self.wb.playing)
        finally:
            clean.close()
            monitored.close()

    def test_preview_clients_share_encoding_and_do_not_modify_source(self):
        import cv2
        import numpy as np
        from concurrent.futures import ThreadPoolExecutor
        self.open()
        original_frame = self.wb.frame.copy()
        encode = cv2.imencode
        def slow_encode(*args, **kwargs):
            time.sleep(.02)
            return encode(*args, **kwargs)
        with patch('ddrcv.workbench.controller.cv2.imencode', side_effect=slow_encode) as encoder:
            with ThreadPoolExecutor(max_workers=2) as pool:
                images = list(pool.map(lambda _: self.wb.image('clean'), range(2)))
            self.assertEqual(encoder.call_count, 1)
            self.assertEqual(images[0], images[1])
        for view in ('monitored', 'annotated', 'p1', 'p2'):
            self.wb.image(view)
        np.testing.assert_array_equal(self.wb.frame, original_frame)
        self.assertEqual(self.wb.image('clean'), images[0])

    def test_port_conflict_is_reported_without_killing_other_service(self):
        from ddrcv.publish.websocket_publisher import WebSocketPublisher
        # Use a socket reservation to force an actual bind failure.
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1', 0))
            occupied.listen()
            second = WebSocketPublisher('127.0.0.1', occupied.getsockname()[1])
            with self.assertRaisesRegex(RuntimeError, 'Stop the other driver'):
                second.start()
            second.stop()

    def test_close_releases_score_port_even_when_results_cleanup_fails(self):
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            self.wb.publisher.port = reservation.getsockname()[1]
        self.wb.publisher.start()
        close_results = self.wb.results.close

        def failed_cleanup():
            close_results()
            raise RuntimeError('results cleanup failed')

        with patch.object(self.wb.results, 'close', side_effect=failed_cleanup):
            with self.assertRaisesRegex(RuntimeError, 'results cleanup failed'):
                self.wb.close()
        self.assertFalse(self.wb.publisher.status['running'])
        with socket.socket() as probe:
            probe.settimeout(.2)
            self.assertNotEqual(probe.connect_ex(('127.0.0.1', self.wb.publisher.port)), 0)
        import logging
        logging.getLogger().removeHandler(self.wb.logs)


@unittest.skipUnless(HAS_RUNTIME, 'Requires rehearsal dependencies')
class OBSServiceTests(unittest.TestCase):
    def test_connection_check_mapping_and_pause_resume(self):
        from types import SimpleNamespace
        from ddrcv.publish.obs_service import OBSService
        obs = Mock()
        obs.get_scene_list.return_value = SimpleNamespace(scenes=[{'sceneName':'Gameplay'}, {'sceneName':'Commentator'}])
        obs.get_current_program_scene.return_value = SimpleNamespace(current_program_scene_name='Commentator')
        service = OBSService(client=obs)
        self.assertFalse(service.validate()['automation'])
        service.update({'state':'song_playing'})
        obs.set_current_program_scene.assert_not_called()
        service.automate(True)
        service.update({'state':'song_playing'})
        obs.set_current_program_scene.assert_called_with('Gameplay')
        service.manual_scene('Commentator')
        self.assertFalse(service.enabled)
        service.update({'state':'song_playing'})
        obs.set_current_program_scene.assert_called_with('Commentator')

    def test_invalid_scene_names_prevent_enabling_automation(self):
        from types import SimpleNamespace
        from ddrcv.publish.obs_service import OBSService
        obs=Mock()
        obs.get_scene_list.return_value=SimpleNamespace(scenes=[])
        service=OBSService(client=obs)
        with self.assertRaisesRegex(ValueError, 'Missing OBS scenes'):
            service.automate(True)
        self.assertFalse(service.enabled)


@unittest.skipUnless(HAS_RUNTIME and importlib.util.find_spec('pygame'), 'Requires renderer dependencies')
class RendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib.util
        root = ROOT.parent / 'ddr_score_render'
        if not (root / 'apps/tbd5.py').exists():
            raise unittest.SkipTest('Renderer checkout not present')
        sys.path.insert(0, str(root))
        spec = importlib.util.spec_from_file_location('rehearsal_renderer', root / 'apps/tbd5.py')
        cls.renderer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.renderer)

    def test_missing_scores_and_single_player_are_raw_numbers(self):
        values = self.renderer.score_values
        self.assertEqual(values({'state':'song_playing', 'score':None}), (None, None))
        self.assertEqual(values({'state':'song_playing', 'score':{'p1_score':1000000,'p2_score':None}}), (1000000,None))
        self.assertEqual(values({'state':'unknown', 'score':{'p1_score':100}}), (None,None))

    def test_money_text_fits_and_preserves_anchor(self):
        import pygame
        from score_render.elements import TextBox
        pygame.font.init()
        box = TextBox('0', self.renderer.ASSETS_DIR / 'fonts/ChangaOne-Regular.ttf', font_size=72, anchor='bottomright')
        box.set_position(268, 220)
        self.renderer.fit_text(box, '1000000', 258)
        self.assertLessEqual(box.text_surface.get_width(), 258)
        self.assertEqual(box.rect.bottomright, (268,220))
        pygame.font.quit()

    def test_feed_reconnect_and_bounded_shutdown(self):
        import threading
        from ddrcv.publish.websocket_publisher import WebSocketPublisher
        from score_render.ingest import WebSocketHandler
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1',0))
            port=reservation.getsockname()[1]
        publisher=WebSocketPublisher('127.0.0.1',port,delay=.02)
        received=[]
        handler=WebSocketHandler(f'ws://127.0.0.1:{port}',received.append,reconnect_delay=.05)
        thread=threading.Thread(target=handler.start,daemon=True)
        try:
            publisher.send_message({'state':'song_select'})
            publisher.start()
            thread.start()
            wait_until(lambda: len(received)>0)
            publisher.stop()
            publisher.send_message({'state':'song_result'})
            publisher.start()
            wait_until(lambda: any('song_result' in msg for msg in received),timeout=5)
        finally:
            handler.stop()
            thread.join(timeout=3)
            publisher.stop()
        self.assertFalse(thread.is_alive())


if __name__ == '__main__':
    unittest.main()
