"""Actual matcher traces, score-read roles, and overlays must agree with recognition."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

HAS_RUNTIME = all(importlib.util.find_spec(name) for name in ('cv2', 'numpy', 'flask', 'websockets', 'obsws_python'))
ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(HAS_RUNTIME, 'Requires rehearsal dependencies')
class RegionTests(unittest.TestCase):
    def marker(self, name, matched):
        import numpy as np
        from ddrcv.state.state_matcher import StateMatcher
        marker = StateMatcher(name, (10, 20, 30, 40), np.zeros((40, 30, 3), dtype=np.uint8))
        marker.hash_matcher.match_roi = Mock(return_value=matched)
        return marker

    def test_short_circuit_and_rotation_report_only_checks_actually_run(self):
        from ddrcv.state.tbd5_states import StateRotation, SongPlaying, SimpleState
        from ddrcv.state.region_monitor import collect_regions
        gameplay = SongPlaying.__new__(SongPlaying)
        gameplay.tag, gameplay.measure_gutters = 'song_playing', False
        gameplay.p1_matcher = self.marker('gameplay_1', True)
        gameplay.p2_matcher = self.marker('gameplay_2', True)
        select = SimpleState.__new__(SimpleState)
        select.tag, select.matcher = 'song_select', self.marker('select', False)
        results = SimpleState.__new__(SimpleState)
        results.tag, results.matcher = 'song_result', self.marker('results', True)
        rotation = StateRotation.__new__(StateRotation)
        rotation.states = [select, gameplay, results]
        with collect_regions() as checks:
            tag, _ = rotation.match(None)
        self.assertEqual(tag, 'song_playing')
        self.assertEqual([c['name'] for c in checks], ['select', 'gameplay_1'])
        self.assertEqual([c['matched'] for c in checks], [False, True])
        self.assertEqual(checks[1]['roi'], [10, 20, 30, 40])
        self.assertEqual(checks[1]['state'], 'song_playing')
        gameplay.p2_matcher.hash_matcher.match_roi.assert_not_called()
        results.matcher.hash_matcher.match_roi.assert_not_called()
        with collect_regions() as following:
            rotation.match(None)
        self.assertEqual([c['name'] for c in following], ['gameplay_1'])
        self.assertEqual(len(checks), 2)  # Earlier frame evidence is immutable.

    def test_splash_tracks_both_presence_checks_and_trace_does_not_leak(self):
        from ddrcv.state.tbd5_states import SongSplash, StateRotation
        from ddrcv.state.region_monitor import collect_regions
        splash = SongSplash.__new__(SongSplash)
        splash.tag = 'song_splash'
        splash.matcher_p1, splash.matcher_p2 = self.marker('p1', True), self.marker('p2', False)
        rotation = StateRotation.__new__(StateRotation)
        rotation.states = [splash]
        with collect_regions() as checks:
            tag, data = rotation.match(None)
        self.assertEqual([c['matched'] for c in checks], [True, False])
        self.assertEqual(data, {'p1_present': True, 'p2_present': False})
        rotation.match(None)
        self.assertEqual(len(checks), 2)
        with self.assertRaises(RuntimeError):
            with collect_regions() as interrupted:
                raise RuntimeError('test')
        rotation.match(None)
        self.assertEqual(interrupted, [])

    def test_real_frames_keep_recognition_identical_with_diagnostics(self):
        import cv2
        from ddrcv.apps.recognition_engine import RecognitionEngine
        frame = cv2.imread(str(ROOT / 'state_images/mar2025/gameplay_2.png'))
        if frame is None:
            self.skipTest('Optional reference frame missing')
        traced, production = RecognitionEngine(), RecognitionEngine()
        for i in range(12):
            observed = traced.process(frame, i / 30, i, diagnostics=True)
            ordinary = production.process(frame, i / 30, i)
            self.assertEqual(observed['published'], ordinary['published'])
            self.assertEqual(observed['raw_state'], ordinary['raw_state'])
            state_checks = [r for r in observed['monitored_regions'] if r['kind'] == 'state']
            self.assertTrue(any(r['matched'] and r['state'] == 'song_playing' for r in state_checks))
            scores = [r for r in observed['monitored_regions'] if r['kind'] == 'score']
            self.assertEqual(scores[0]['roi'], [160, 644, 240, 45])
            self.assertEqual(scores[0]['use'], 'diagnostic' if observed['confirmed_state'] == 'unknown' else 'production')
            self.assertFalse(ordinary['monitored_regions'])
        still = traced.process(frame, 0, 0, diagnostics=True, stateless=True)
        self.assertTrue(all(r['use'] == 'diagnostic' for r in still['monitored_regions'] if r['kind'] == 'score'))

    def test_absent_players_have_no_score_read_regions(self):
        import numpy as np
        from ddrcv.apps.recognition_engine import RecognitionEngine
        matcher, extractor = Mock(), Mock()
        matcher.match.return_value = ('song_splash', {'p1_present': True, 'p2_present': False})
        extractor.extract.return_value = {'data': {'p1_score': 10, 'p2_score': None}}
        engine = RecognitionEngine(matcher=matcher, extractor=extractor)
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        for i in range(12):
            engine.process(frame, i / 30, i, diagnostics=True)
        matcher.match.return_value = ('song_playing', None)
        for i in range(12, 24):
            observed = engine.process(frame, i / 30, i, diagnostics=True)
        scores = [r for r in observed['monitored_regions'] if r['kind'] == 'score']
        self.assertEqual([r['player'] for r in scores], ['p1'])
        self.assertEqual(scores[0]['use'], 'production')

    def test_overlay_and_snapshot_use_same_frame_without_changing_clean_image(self):
        import cv2
        import numpy as np
        from ddrcv.workbench.controller import Workbench
        from ddrcv.workbench.app import create_app
        with tempfile.TemporaryDirectory() as tmp:
            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            source = Path(tmp) / 'still.png'
            cv2.imwrite(str(source), frame)
            wb = Workbench(Path(tmp) / 'settings', start_publisher=False)
            try:
                wb.submit('open', kind='image', path=str(source))
                client = create_app(wb).test_client()
                before = client.get('/frame.jpg?view=clean')
                overlay = client.get('/frame.jpg?view=monitored')
                after = client.get('/frame.jpg?view=clean')
                self.assertEqual(before.data, after.data)
                self.assertNotEqual(before.data, overlay.data)
                self.assertEqual(before.headers['X-Frame-Sequence'], overlay.headers['X-Frame-Sequence'])
                self.assertTrue(np.array_equal(wb.frame, frame))
                folder = Path(wb.submit('snapshot')['path'])
                evidence = json.loads((folder / 'diagnostics.json').read_text())
                self.assertTrue(evidence['diagnostics']['monitored_regions'])
                self.assertTrue(np.array_equal(cv2.imread(str(folder / 'frame.png')), frame))
                self.assertFalse(np.array_equal(cv2.imread(str(folder / 'monitored.png')), frame))
                wb.submit('stop')
                self.assertIsNone(wb.status()['diagnostics'])
                self.assertIsNone(wb.image('monitored')[0])
            finally:
                wb.close()


if __name__ == '__main__':
    unittest.main()
