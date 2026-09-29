"""Independent name workers keep parsing, ownership and error handling intact."""
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

import numpy as np

from experiments.jacket_lookup.names import PerPlayerNameReader


class ParallelNameTests(unittest.TestCase):
    def setUp(self):
        self.readers = [Mock(), Mock()]
        for i, reader in enumerate(self.readers):
            reader.read.side_effect = lambda crops: {key:str(key) for key in crops}
            reader.read_login.side_effect = reader.read.side_effect
        self.reader = PerPlayerNameReader(reader_factory=Mock(side_effect=self.readers))
        self.addCleanup(self.reader.close)
        self.crop = np.zeros((34, 212, 3), np.uint8)

    def test_players_overlap_and_keep_input_order(self):
        barrier = threading.Barrier(2)
        def read(crops):
            barrier.wait(timeout=1)
            return {key:'P'+str(key+1) for key in crops}
        for reader in self.readers: reader.read.side_effect = read
        result = self.reader.read({1:self.crop, 0:self.crop})
        self.assertEqual(list(result), [1, 0])
        self.assertEqual(result, {0:'P1', 1:'P2'})

    def test_empty_and_one_player_skip_other_worker(self):
        self.assertEqual(self.reader.read({}), {})
        self.assertEqual(self.reader.read({1:self.crop}), {1:'1'})
        self.readers[0].read.assert_not_called()
        self.readers[1].read.assert_called_once()

    def test_login_uses_existing_login_reader(self):
        self.assertEqual(self.reader.read_login({0:self.crop}), {0:'0'})
        self.readers[0].read_login.assert_called_once()
        self.readers[0].read.assert_not_called()

    def test_warmup_reuses_reader_instances(self):
        self.reader.warmup(); self.reader.warmup()
        for reader in self.readers: self.assertEqual(reader.warmup.call_count, 2)
        self.assertEqual(self.reader.config['ocr']['num_threads'], 1)

    def test_worker_cannot_mutate_input(self):
        def read(crops):
            crops[0][:] = 99
            return {0:'TEST'}
        self.readers[0].read.side_effect = read
        self.reader.read({0:self.crop})
        self.assertFalse(self.crop.any())

    def test_error_drains_other_player_and_recovers(self):
        done = threading.Event()
        self.readers[0].read.side_effect = RuntimeError('bad sample')
        def read(crops):
            time.sleep(.02); done.set(); return {1:'OK'}
        self.readers[1].read.side_effect = read
        with self.assertRaisesRegex(RuntimeError, 'bad sample'):
            self.reader.read({0:self.crop, 1:self.crop})
        self.assertTrue(done.is_set())
        self.readers[0].read.side_effect = lambda crops: {0:None}
        self.assertEqual(self.reader.read({0:self.crop, 1:self.crop}), {0:None, 1:'OK'})

    def test_missing_optional_engine_is_reported_and_workers_close(self):
        with PerPlayerNameReader(dict(ocr=dict(allow_download=False))) as reader:
            with patch('ddrcv.ocr.rapid._build_engine', side_effect=ImportError('OCR optional dependency missing')):
                with self.assertRaisesRegex(ImportError, 'optional dependency'):
                    reader.warmup()
        self.assertTrue(all(not w.thread.is_alive() for w in reader._workers))

    def test_existing_service_confirms_and_clears_names(self):
        from ddrcv.state.player_names import PlayerNameService
        def wait_for(predicate):
            end = time.monotonic()+2
            while not predicate():
                if time.monotonic() > end: self.fail('Timed out waiting for name service')
                time.sleep(.002)
        service = PlayerNameService(dict(enabled=True), reader=self.reader)
        try:
            wait_for(lambda: service.ready)
            frame = np.zeros((720,1280,3), np.uint8)
            for stamp in (0, .2, .4):
                before = self.readers[0].read.call_count
                service.submit(frame, stamp, 'song_splash', 'song_splash', (True,True), 'a')
                wait_for(lambda: self.readers[0].read.call_count > before and not service.busy)
            self.assertEqual(service.snapshot(), dict(p1='0',p2='1'))
            service.reset('b')
            self.assertEqual(service.snapshot(), dict(p1=None,p2=None))
        finally:
            service.close()

    def test_invalid_keys_fail_before_scheduling(self):
        for key in (-1, 2, 'p1', True):
            with self.assertRaises(ValueError): self.reader.read({key:self.crop})
        for reader in self.readers: reader.read.assert_not_called()

    def test_rejects_shared_recognizer(self):
        self.readers[1].ocr = self.readers[0].ocr
        with self.assertRaisesRegex(ValueError, 'independent OCR'):
            PerPlayerNameReader(reader_factory=Mock(side_effect=self.readers))

    def test_close_is_bounded_and_rejects_reads(self):
        started, release = threading.Event(), threading.Event()
        def read(crops):
            started.set(); release.wait(2); return {0:'OK'}
        self.readers[0].read.side_effect = read
        try:
            with ThreadPoolExecutor(1) as pool:
                future = pool.submit(self.reader.read, {0:self.crop})
                self.assertTrue(started.wait(1))
                before = time.monotonic()
                self.assertFalse(self.reader.close(.01))
                self.assertLess(time.monotonic()-before, .2)
                release.set(); self.assertEqual(future.result(1), {0:'OK'})
            with self.assertRaises(RuntimeError): self.reader.read({})
            self.assertTrue(self.reader.close(1))
        finally: release.set()


class RealParallelNameTests(unittest.TestCase):
    def test_real_splash_and_login_match_existing_reader(self):
        import os
        from pathlib import Path
        import cv2
        from ddrcv.state.player_names import PlayerNameReader, NAME_BOXES, LOGIN_BOXES, validate_config
        options = dict(allow_download=False, num_threads=2)
        if os.environ.get('DDRCV_TEST_OCR_MODEL'):
            options['model_path'] = os.environ['DDRCV_TEST_OCR_MODEL']
        cfg = validate_config(dict(ocr=options))
        baseline = PlayerNameReader(cfg)
        root = Path(__file__).resolve().parents[1]
        with PerPlayerNameReader(cfg, high_qos=True) as reader:
            reader.warmup()
            for filename, expected in [('song_splash.png', {0:'ZERO.', 1:'WOLF.'}),
                                       ('song_splash_updated.png', {0:'ZERO.', 1:'PLAYER2'}),
                                       ('song_splash_updated_p2.png', {1:'N.NATURE'})]:
                frame = cv2.imread(str(root/'state_images'/filename))
                crops = {i:frame[y:y+h,x:x+w] for i,(x,y,w,h) in enumerate(NAME_BOXES) if i in expected}
                self.assertEqual(reader.read(crops), expected)
                self.assertEqual(reader.read(crops), baseline.read(crops))
            for filename in ('vlcsnap-2025-03-19-22h20m04s788.png', 'vlcsnap-2025-03-19-22h21m28s838.png'):
                frame = cv2.imread(str(root/'state_images/mar2025/english'/filename))
                crops = {i:frame[y:y+h,x:x+w] for i,(x,y,w,h) in enumerate(LOGIN_BOXES)}
                self.assertEqual(reader.read_login(crops), {0:'ZVIDUN', 1:'EVILDAVE'})
                self.assertEqual(reader.read_login(crops), baseline.read_login(crops))
            for filename in ('login_league_bands.png', 'login_card_bands.png'):
                bands = cv2.imread(str(root/'tests/fixtures'/filename))
                self.assertEqual(reader.read_login({0:bands[:50], 1:bands[50:]}), {0:None, 1:None})


if __name__ == '__main__': unittest.main()
