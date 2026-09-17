"""Splash OCR lifetime and nonblocking behavior; real model checks never skip."""
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import numpy as np

from ddrcv.ocr import OCRResult
from ddrcv.state.player_names import LOGIN_BOXES, PlayerNameService, SplashNameReader, validate_config


def wait_for(predicate, timeout=3):
    end = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= end:
            raise AssertionError('Timed out waiting for name worker')
        time.sleep(.005)


class NamesTests(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((720, 1280, 3), np.uint8)
        self.reader = Mock()
        self.reader.read.return_value = {0: 'ZERO.', 1: 'PLAYER2'}
        self.service = PlayerNameService(dict(enabled=True), reader=self.reader)
        wait_for(lambda: self.service.ready)

    def tearDown(self):
        self.service.close()

    def submit(self, t, generation='a', presence=(True, True), raw='song_splash', state='song_splash'):
        self.service.submit(self.frame, t, raw, state, presence, generation)

    def read(self, t, **kwargs):
        before = self.reader.read.call_count
        self.submit(t, **kwargs)
        wait_for(lambda: self.reader.read.call_count > before and not self.service.busy)

    def confirm(self):
        for t in (0, .2, .4):
            self.read(t)
        self.assertEqual(self.service.snapshot(), dict(p1='ZERO.', p2='PLAYER2'))

    def test_confirmation_latches_and_lives_through_same_song(self):
        self.confirm()
        self.submit(.6)
        self.submit(1, raw='unknown', state='unknown')
        self.submit(2, raw='song_playing', state='song_playing')
        self.submit(3, raw='song_result', state='song_result')
        self.assertEqual(self.reader.read.call_count, 3)
        self.assertEqual(self.service.snapshot()['p1'], 'ZERO.')
        self.submit(4, generation='b', raw='song_select', state='song_select')
        self.assertEqual(self.service.snapshot(), dict(p1=None, p2=None))

    def test_presence_and_crop_copies(self):
        for t in (0, .2, .4):
            self.read(t, presence=(False, True))
        crops = self.reader.read.call_args.args[0]
        self.assertEqual(set(crops), {1})
        self.assertEqual(crops[1].shape, (34, 212, 3))
        self.assertFalse(np.shares_memory(crops[1], self.frame))
        self.assertEqual(self.service.snapshot(), dict(p1=None, p2='PLAYER2'))
        self.submit(.6, presence=(True, False))
        self.assertIsNone(self.service.snapshot()['p2'])

    def test_missing_conflicting_and_interrupted_reads_reset_evidence(self):
        for i, value in enumerate(('A', 'A', None, 'A', 'B', 'A')):
            self.reader.read.return_value = {0: value}
            self.read(i * .2, presence=(True, False))
            self.assertIsNone(self.service.snapshot()['p1'])
        self.submit(1.1, raw='unknown')
        self.read(1.2, presence=(True, False))
        self.read(1.4, presence=(True, False))
        self.assertIsNone(self.service.snapshot()['p1'])
        self.read(1.6, presence=(True, False))
        self.assertEqual(self.service.snapshot()['p1'], 'A')

    def test_gaps_and_duplicate_timestamps_do_not_confirm(self):
        self.read(0)
        self.submit(0)
        self.read(.2)
        self.read(2)
        self.read(2.2)
        self.assertIsNone(self.service.snapshot()['p1'])
        self.assertEqual(self.reader.read.call_count, 4)
        self.read(2.4)
        self.assertEqual(self.service.snapshot()['p1'], 'ZERO.')

    def test_slow_read_bounded_mailbox_and_reset_rejects_stale(self):
        entered, release = threading.Event(), threading.Event()
        def blocked(crops):
            entered.set()
            release.wait(4)
            return {0: 'OLD', 1: 'OLD'}
        self.reader.read.side_effect = blocked
        try:
            self.submit(0)
            self.assertTrue(entered.wait(1))
            start = time.perf_counter()
            for i in range(1, 50):
                self.submit(i * .2)
            self.service.reset('b')
            self.assertLess(time.perf_counter() - start, .2)
            self.assertEqual(self.service.status()['pending'], 0)
            self.assertGreater(self.service.status()['replaced_samples'], 40)
            release.set()
            wait_for(lambda: not self.service.busy)
            self.assertEqual(self.service.snapshot(), dict(p1=None, p2=None))
        finally:
            release.set()

    def test_final_read_can_complete_in_gameplay_and_close_is_bounded(self):
        self.read(0)
        self.read(.2)
        entered, release = threading.Event(), threading.Event()
        def blocked(crops):
            entered.set()
            release.wait(4)
            return {0: 'ZERO.', 1: 'PLAYER2'}
        self.reader.read.side_effect = blocked
        try:
            self.submit(.4)
            self.assertTrue(entered.wait(1))
            self.submit(.5, raw='song_playing', state='song_playing')
            release.set()
            wait_for(lambda: self.service.snapshot()['p1'] == 'ZERO.')
            self.service.reset('b')
            entered.clear(); release.clear()
            self.submit(1, generation='b')
            self.assertTrue(entered.wait(1))
            start = time.perf_counter()
            self.service.close(timeout=.02)
            self.assertLess(time.perf_counter() - start, .2)
            release.set()
            self.service.worker.join(1)
            self.assertEqual(self.service.snapshot(), dict(p1=None, p2=None))
        finally:
            release.set()

    def test_old_generation_error_does_not_disable_new_song(self):
        entered, release = threading.Event(), threading.Event()
        def blocked(crops):
            entered.set(); release.wait(4)
            raise RuntimeError('old crop failed')
        self.reader.read.side_effect = blocked
        try:
            self.submit(0)
            self.assertTrue(entered.wait(1))
            self.service.reset('b')
            release.set()
            wait_for(lambda: not self.service.busy)
            self.assertIsNone(self.service.status()['error'])
            self.reader.read.side_effect = None
            for t in (1, 1.2, 1.4):
                self.read(t, generation='b')
            self.assertEqual(self.service.snapshot()['p1'], 'ZERO.')
        finally:
            release.set()

    def test_warmup_and_read_failure_are_reported_without_raising_on_driver(self):
        self.reader.read.side_effect = RuntimeError('model unavailable')
        self.submit(0)
        wait_for(lambda: self.service.status()['phase'] == 'failed')
        self.submit(.2)
        self.assertEqual(self.service.snapshot(), dict(p1=None, p2=None))
        reader = Mock(); reader.warmup.side_effect = ImportError('missing dependency')
        service = PlayerNameService(dict(enabled=True), reader=reader)
        try:
            wait_for(lambda: service.status()['phase'] == 'failed')
            self.assertIn('missing dependency', service.status()['error'])
        finally:
            service.close()

    def test_reader_preserves_punctuation_and_abstains(self):
        recognizer = Mock()
        reader = SplashNameReader(validate_config(), recognizer)
        for text, confidence, expected in [('ZERO.', .99, 'ZERO.'), ('N.NATURE', .99, 'N.NATURE'),
                                            ('guess', .79, None), ('', .99, None), ('a\nb', .99, None)]:
            recognizer.recognize_many.return_value = [OCRResult(text, confidence)]
            self.assertEqual(reader.read({1: self.frame[:34, :212]})[1], expected)

    def test_disabled_does_not_start_model(self):
        reader = Mock()
        service = PlayerNameService(reader=reader)
        try:
            service.submit(self.frame, 0, 'song_splash', 'song_splash', (True, True), 'a')
            self.assertIsNone(service.worker)
            reader.warmup.assert_not_called()
        finally:
            service.close()

    def test_live_toggle_reuses_worker_and_rejects_old_read(self):
        self.read(0); self.read(.2)
        worker = self.service.worker
        entered, release = threading.Event(), threading.Event()
        def blocked(crops):
            entered.set(); release.wait(3)
            return {0:'OLD', 1:'OLD'}
        self.reader.read.side_effect = blocked
        try:
            self.submit(.4); self.assertTrue(entered.wait(1))
            before = time.perf_counter()
            self.service.configure_enabled(False)
            self.service.configure_enabled(True)
            self.assertLess(time.perf_counter() - before, .1)
            self.assertIs(self.service.worker, worker)
            release.set(); wait_for(lambda: not self.service.busy)
            self.assertEqual(self.service.snapshot(), dict(p1=None, p2=None))
            self.reader.read.side_effect = None
            for t in (1, 1.2, 1.4): self.read(t)
            self.assertEqual(self.service.snapshot()['p1'], 'ZERO.')
            self.reader.warmup.assert_called_once()
        finally: release.set()

    def test_live_toggle_can_retry_failed_initialization(self):
        reader = Mock(); reader.warmup.side_effect = RuntimeError('offline')
        service = PlayerNameService(dict(enabled=True), reader=reader)
        try:
            wait_for(lambda: service.error is not None)
            worker = service.worker
            service.configure_enabled(False)
            reader.warmup.side_effect = None
            service.configure_enabled(True)
            wait_for(lambda: service.ready)
            self.assertIsNone(service.error)
            self.assertIs(service.worker, worker)
        finally: service.close()

    def login_read(self, t, **kwargs):
        before = self.reader.read_login.call_count
        self.submit(t, raw='login', state='login', **kwargs)
        wait_for(lambda: self.reader.read_login.call_count > before and not self.service.busy)

    def test_login_confirms_each_side_and_select_retains_names(self):
        self.reader.read_login.return_value = {0: 'ZVIDUN', 1: None}
        for t in (0, .2, .4):
            self.login_read(t)
        self.assertEqual(self.service.snapshot(), dict(p1='ZVIDUN', p2=None))
        self.assertEqual(self.reader.read_login.call_args.args[0][1].shape, (50, 338, 3))
        self.reader.read.assert_not_called()
        self.reader.read_login.return_value = {1: 'EVILDAVE'}
        for t in (.6, .8, 1.):
            self.login_read(t)
        self.assertEqual(set(self.reader.read_login.call_args.args[0]), {1})
        self.submit(1.2, raw='song_select', state='song_select')
        self.assertEqual(self.service.snapshot(), dict(p1='ZVIDUN', p2='EVILDAVE'))
        self.submit(1.4, raw='song_playing', state='song_playing')
        self.assertEqual(self.service.snapshot(), dict(p1=None, p2=None))

    def test_login_to_splash_requires_new_evidence_even_if_generation_same(self):
        self.reader.read_login.return_value = {0: 'ZVIDUN', 1: 'EVILDAVE'}
        for t in (0, .2, .4):
            self.login_read(t)
        self.read(.6)
        self.assertEqual(self.service.snapshot(), dict(p1=None, p2=None))
        self.read(.8)
        self.read(1.)
        self.assertEqual(self.service.snapshot(), dict(p1='ZERO.', p2='PLAYER2'))

    def test_stale_login_completion_cannot_overwrite_splash(self):
        entered, release = threading.Event(), threading.Event()
        def blocked(crops):
            entered.set(); release.wait(3)
            return {0: 'OLD', 1: 'OLD'}
        self.reader.read_login.side_effect = blocked
        try:
            self.submit(0, raw='login', state='login')
            self.assertTrue(entered.wait(1))
            self.submit(.2, generation='b')
            release.set()
            wait_for(lambda: self.reader.read.call_count == 1 and not self.service.busy)
            self.assertEqual(self.service.snapshot(), dict(p1=None, p2=None))
            self.read(.4, generation='b')
            self.read(.6, generation='b')
            self.assertEqual(self.service.snapshot(), dict(p1='ZERO.', p2='PLAYER2'))
        finally:
            release.set()

    def test_login_reader_requires_confident_dancer_name_label(self):
        recognizer = Mock()
        reader = SplashNameReader(validate_config(), recognizer)
        band = self.frame[:50, :338]
        for text, confidence, expected in [('DANCER NAME', .99, 'ZVIDUN'), ('DANCERNAME', .99, 'ZVIDUN'),
                                           ('In-game event now', .99, None), ('DANCER NAME', .79, None)]:
            recognizer.recognize_many.return_value = [OCRResult(text, confidence), OCRResult('ZVIDUN', .99)]
            self.assertEqual(reader.read_login({0: band}), {0: expected})


class NamesIntegrationTests(unittest.TestCase):
    def test_login_generation_survives_selection_but_not_splash_or_new_login(self):
        from ddrcv.apps.tournament_session import TournamentSession
        session = TournamentSession(dict(confirm_seconds=.1, min_frames=2))
        def observe(state, t):
            data = dict(p1_present=True, p2_present=True) if state == 'song_splash' else None
            for i in range(10):
                session.observe(state, data, t + i * .02)
        observe('login', 0)
        login_generation = session.song_generation
        observe('song_select', 1)
        self.assertEqual(session.song_generation, login_generation)
        observe('song_splash', 2)
        self.assertNotEqual(session.song_generation, login_generation)
        observe('login', 3)
        self.assertNotEqual(session.song_generation, login_generation)

    def test_session_generation_preserves_splash_to_play_and_resets_next_song(self):
        from ddrcv.apps.tournament_session import TournamentSession
        session = TournamentSession(dict(confirm_seconds=.1, min_frames=2))
        def observe(state, t):
            data = dict(p1_present=True, p2_present=True) if state == 'song_splash' else None
            for i in range(10):
                session.observe(state, data, t + i * .02)
        observe('song_splash', 0)
        generation = session.song_generation
        observe('song_playing', 1)
        observe('song_result', 2)
        self.assertEqual(session.song_generation, generation)
        observe('song_playing', 3)  # Missed select/splash must not retain names.
        self.assertNotEqual(session.song_generation, generation)

    def test_runtime_keeps_scoring_and_source_switching_while_ocr_blocked(self):
        from test_desktop import RuntimeTests
        entered, release = threading.Event(), threading.Event()
        reader = Mock()
        def blocked(crops):
            entered.set(); release.wait(5)
            return {0: 'OLD', 1: 'OLD'}
        reader.read.side_effect = blocked
        with tempfile.TemporaryDirectory() as tmp:
            service = PlayerNameService(dict(enabled=True), reader=reader)
            runtime = RuntimeTests().make_runtime(tmp)
            runtime.engine.matcher.match.return_value = ('song_splash', dict(p1_present=True, p2_present=True))
            with patch('ddrcv.apps.tournament_runtime.PlayerNameService', return_value=service):
                runtime.start()
                try:
                    self.assertTrue(entered.wait(2))
                    runtime.engine.matcher.match.return_value = ('song_playing', None)
                    wait_for(lambda: runtime.status()['published']['score'] is not None)
                    seq = runtime.sequence
                    wait_for(lambda: runtime.sequence > seq + 5)
                    candidate = Mock()
                    candidate.get_frame.return_value = np.zeros((720, 1280, 3), np.uint8)
                    with patch.object(runtime, '_create_fetcher', return_value=candidate):
                        runtime.switch_source({'simple': {'uri': 1}})
                    release.set()
                    wait_for(lambda: not service.busy)
                    self.assertEqual(runtime.status()['published']['player_names'], dict(p1=None, p2=None))
                finally:
                    release.set(); runtime.stop()

    def test_runtime_publishes_last_confirmation_during_capture_loss(self):
        from test_desktop import RuntimeTests
        entered, release = threading.Event(), threading.Event()
        reader = Mock(); count = [0]
        def read(crops):
            count[0] += 1
            if count[0] == 3:
                entered.set(); release.wait(5)
            return {0: 'ZERO.', 1: 'PLAYER2'}
        reader.read.side_effect = read
        with tempfile.TemporaryDirectory() as tmp:
            service = PlayerNameService(dict(enabled=True), reader=reader)
            runtime = RuntimeTests().make_runtime(tmp)
            runtime.engine.matcher.match.return_value = ('song_splash', dict(p1_present=True, p2_present=True))
            with patch('ddrcv.apps.tournament_runtime.PlayerNameService', return_value=service):
                runtime.start()
                try:
                    self.assertTrue(entered.wait(3))
                    runtime.fetcher.get_frame.side_effect = lambda: None
                    time.sleep(.05)
                    seq = runtime.sequence
                    release.set()
                    wait_for(lambda: runtime.publisher.send_message.call_args.args[0]['player_names']['p1'] == 'ZERO.')
                    self.assertEqual(runtime.sequence, seq)
                    self.assertEqual(runtime.status()['published']['player_names']['p2'], 'PLAYER2')
                    self.assertEqual(runtime.integrations.message['player_names']['p1'], 'ZERO.')
                finally:
                    release.set(); runtime.stop()

    def test_workbench_publication_and_reset(self):
        from test_workbench import make_engine
        from ddrcv.workbench.controller import Workbench
        from ddrcv.ingest.file_source import FramePacket
        reader = Mock(); reader.read.return_value = {0: 'ZERO.', 1: 'PLAYER2'}
        service = PlayerNameService(dict(enabled=True), reader=reader)
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine()
            engine.matcher.match.return_value = ('song_splash', dict(p1_present=True, p2_present=True))
            with patch('ddrcv.workbench.controller.PlayerNameService', return_value=service):
                wb = Workbench(tmp, engine=engine, start_publisher=False)
            try:
                wb.kind = 'video'
                for i in range(40):
                    wb._process(FramePacket(np.zeros((720, 1280, 3), np.uint8), i * .04, i))
                    time.sleep(.01)
                wait_for(lambda: wb.status()['published']['player_names']['p1'] == 'ZERO.')
                wb.submit('stop')
                self.assertEqual(wb.status()['published']['player_names'], dict(p1=None, p2=None))
            finally:
                wb.close()


class RealModelReadinessTests(unittest.TestCase):
    def test_real_login_names_and_non_name_subpages(self):
        import cv2
        model = os.environ.get('DDRCV_TEST_OCR_MODEL')
        options = dict(allow_download=False)
        if model:
            options['model_path'] = model
        reader = SplashNameReader(validate_config(dict(ocr=options)))
        root = Path(__file__).resolve().parents[1]
        for filename in ('vlcsnap-2025-03-19-22h20m04s788.png', 'vlcsnap-2025-03-19-22h21m28s838.png'):
            frame = cv2.imread(str(root / 'state_images/mar2025/english' / filename))
            bands = {i: frame[y:y+h,x:x+w] for i,(x,y,w,h) in enumerate(LOGIN_BOXES)}
            self.assertEqual(reader.read_login(bands), {0: 'ZVIDUN', 1: 'EVILDAVE'})
        for filename in ('login_league_bands.png', 'login_card_bands.png'):
            bands = cv2.imread(str(root / 'tests/fixtures' / filename))
            self.assertIsNotNone(bands)
            self.assertEqual(reader.read_login({0: bands[:50], 1: bands[50:]}), {0: None, 1: None})

    def test_real_names_on_dual_and_single_player_fixtures(self):
        import cv2
        from ddrcv.state.player_names import NAME_BOXES
        model = os.environ.get('DDRCV_TEST_OCR_MODEL')
        options = dict(allow_download=False)
        if model:
            options['model_path'] = model
        reader = SplashNameReader(validate_config(dict(ocr=options)))
        root = Path(__file__).resolve().parents[1]
        for filename, expected in [('song_splash.png', {0: 'ZERO.', 1: 'WOLF.'}),
                                   ('song_splash_updated.png', {0: 'ZERO.', 1: 'PLAYER2'}),
                                   ('song_splash_updated_p2.png', {1: 'N.NATURE'})]:
            with self.subTest(filename=filename):
                frame = cv2.imread(str(root / 'state_images' / filename))
                crops = {i: frame[y:y+h, x:x+w] for i, (x,y,w,h) in enumerate(NAME_BOXES) if i in expected}
                self.assertEqual(reader.read(crops), expected)

    def test_installed_model_recognizes_splash_without_network(self):
        from ddrcv.ocr.check import check_ocr
        with patch('socket.socket.connect', side_effect=AssertionError('Unexpected download')):
            model = os.environ.get('DDRCV_TEST_OCR_MODEL')
            result = check_ocr(dict(model_path=model) if model else None)
        self.assertTrue(result['ok'], result['detail'])

    def test_setup_installs_and_provisions_ocr(self):
        root = Path(__file__).resolve().parents[1]
        self.assertIn('-r requirements-ocr.txt', (root / 'requirements-tournament.txt').read_text())
        for app in ('desktop', 'workbench'):
            self.assertIn('-r requirements-tournament.txt', (root / f'requirements-{app}.txt').read_text())
            self.assertIn('-m ddrcv.ocr.check --provision', (root / f'setup_{app}.bat').read_text())


if __name__ == '__main__':
    unittest.main()
