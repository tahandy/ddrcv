"""Controlled overlap, bounded backpressure, and stale-song rejection."""
from copy import deepcopy
import threading
import time
import unittest
from unittest.mock import Mock

import numpy as np

from experiments.jacket_lookup.threaded import LatestSplashService, ThreadedSplashLookup


def wait_for(predicate, timeout=2):
    end = time.monotonic()+timeout
    while not predicate():
        if time.monotonic() >= end:
            raise AssertionError('Timed out waiting for worker')
        time.sleep(.002)


def fake_lookup():
    lookup=Mock()
    lookup._get_splash_detector.return_value.match.return_value=(True,dict(p1_present=True,p2_present=False))
    lookup.lookup.side_effect=lambda image:dict(accepted=True,song=dict(song_id='song'),timings_ms={})
    lookup._charts.resolve.return_value=dict(status='matched',max_ex=100)
    return lookup


class ParallelStagesTests(unittest.TestCase):
    def test_jacket_and_difficulty_overlap_and_join_correctly(self):
        lookup=fake_lookup();started=threading.Event();jacket=threading.Event()
        reader=Mock()
        def read(image):
            started.set()
            if not jacket.wait(1): raise AssertionError('Jacket did not run concurrently')
            return dict(accepted=True,difficulty='expert')
        def identify(image):
            if not started.wait(1): raise AssertionError('Difficulty did not start concurrently')
            jacket.set()
            return dict(accepted=True,song=dict(song_id='song'),timings_ms={})
        reader.recognize.side_effect=read;lookup.lookup.side_effect=identify
        with ThreadedSplashLookup(lookup,difficulty_reader=reader) as processor:
            result=processor.analyze(np.zeros((720,1280,3),np.uint8))
        self.assertEqual(result['players']['p1']['max_ex'],100)
        lookup._get_recognizer.assert_not_called()
        self.assertFalse(processor._difficulty.thread.is_alive())

    def test_non_splash_does_not_schedule_difficulty(self):
        lookup=fake_lookup();lookup._get_splash_detector.return_value.match.return_value=(False,None)
        reader=Mock()
        with ThreadedSplashLookup(lookup,difficulty_reader=reader) as processor:
            result=processor.analyze(np.zeros((720,1280,3),np.uint8))
        self.assertEqual(result['reason'],'not_splash')
        reader.recognize.assert_not_called();lookup.lookup.assert_not_called()

    def test_errors_are_drained_and_next_request_recovers(self):
        lookup=fake_lookup();reader=Mock()
        reader.recognize.side_effect=[RuntimeError('bad read'),dict(accepted=True,difficulty='expert')]
        with ThreadedSplashLookup(lookup,difficulty_reader=reader) as processor:
            frame=np.zeros((720,1280,3),np.uint8)
            with self.assertRaisesRegex(RuntimeError,'bad read'):processor.analyze(frame)
            self.assertEqual(processor.analyze(frame)['players']['p1']['max_ex'],100)


class LatestServiceTests(unittest.TestCase):
    def setUp(self):
        self.processor=Mock()
        self.processor.analyze.side_effect=lambda frame,**kwargs:dict(pixel=int(frame[0,0,0]),style=kwargs['style'])
        self.processor.close.return_value=True
        self.service=LatestSplashService(self.processor)
        self.addCleanup(self.service.close)
        self.frame=np.zeros((720,1280,3),np.uint8)

    def test_submit_copies_frame_and_snapshot_owns_result(self):
        entered,release=threading.Event(),threading.Event()
        def blocked(frame,**kwargs):
            entered.set();release.wait(2)
            return dict(pixel=int(frame[0,0,0]))
        self.processor.analyze.side_effect=blocked
        try:
            sequence=self.service.submit(self.frame,1,'a')
            self.assertTrue(entered.wait(1));self.frame[:]=99;release.set()
            wait_for(lambda:self.service.snapshot() is not None)
            result=self.service.snapshot()
            self.assertEqual(result['sequence'],sequence);self.assertEqual(result['result']['pixel'],0)
            result['result']['pixel']=17
            self.assertEqual(self.service.snapshot()['result']['pixel'],0)
        finally:release.set()

    def test_backpressure_keeps_only_latest_pending_without_blocking_submit(self):
        entered,release=threading.Event(),threading.Event();seen=[]
        def blocked(frame,**kwargs):
            seen.append(int(frame[0,0,0]));entered.set();release.wait(2)
            return dict(pixel=seen[-1])
        self.processor.analyze.side_effect=blocked
        try:
            self.service.submit(self.frame,0,'a');self.assertTrue(entered.wait(1))
            for i in range(1,20):
                self.frame[:]=i;self.service.submit(self.frame,i,'a')
            self.assertEqual(self.service.status()['pending'],1)
            self.assertEqual(self.service.status()['replaced'],18)
            self.assertFalse(release.is_set())
            release.set();wait_for(lambda:self.service.snapshot() and self.service.snapshot()['timestamp']==19)
            self.assertEqual(seen,[0,19])
        finally:release.set()

    def test_reset_discards_late_result_and_error(self):
        for fail in (False,True):
            entered,release=threading.Event(),threading.Event()
            def blocked(frame,**kwargs):
                entered.set();release.wait(2)
                if fail:raise RuntimeError('old song error')
                return dict(pixel=1)
            self.processor.analyze.side_effect=blocked
            try:
                self.service.reset('old');self.service.submit(self.frame,0,'old')
                self.assertTrue(entered.wait(1));self.service.reset('new');release.set()
                wait_for(lambda:not self.service.status()['busy'])
                self.assertIsNone(self.service.snapshot())
            finally:release.set()

    def test_timestamp_generation_style_and_recovery(self):
        self.service.submit(self.frame,2,'a',style='double')
        wait_for(lambda:self.service.snapshot() is not None)
        self.assertEqual(self.service.snapshot()['result']['style'],'double')
        self.assertIsNone(self.service.submit(self.frame,2,'a'))
        self.assertIsNone(self.service.submit(self.frame,1,'a'))
        self.processor.analyze.side_effect=RuntimeError('one failed sample')
        self.service.submit(self.frame,0,'b')
        wait_for(lambda:self.service.snapshot() and self.service.snapshot()['generation']=='b')
        self.assertEqual(self.service.snapshot()['error'],'one failed sample')
        self.processor.analyze.side_effect=lambda *a,**k:dict(ok=True)
        self.service.submit(self.frame,1,'b')
        wait_for(lambda:self.service.snapshot()['timestamp']==1)
        self.assertIsNone(self.service.snapshot()['error'])

    def test_chart_results_do_not_wait_for_existing_name_worker(self):
        from ddrcv.state.player_names import PlayerNameService
        entered,release=threading.Event(),threading.Event()
        reader=Mock()
        def blocked(crops):
            entered.set();release.wait(2)
            return {0:'ZERO.',1:'PLAYER2'}
        reader.read.side_effect=blocked
        names=PlayerNameService(dict(enabled=True),reader=reader)
        try:
            wait_for(lambda:names.ready)
            names.submit(self.frame,0,'song_splash','song_splash',(True,True),'a')
            self.assertTrue(entered.wait(1))
            self.service.submit(self.frame,0,'a')
            wait_for(lambda:self.service.snapshot() is not None)
            self.assertTrue(names.status()['busy'])
            self.assertEqual(names.snapshot(),dict(p1=None,p2=None))
            self.assertIsNone(self.service.snapshot()['error'])
        finally:
            release.set();names.close()

    def test_close_is_bounded_and_blocks_late_publication(self):
        entered,release=threading.Event(),threading.Event()
        def blocked(frame,**kwargs):entered.set();release.wait(2);return dict(ok=True)
        self.processor.analyze.side_effect=blocked
        try:
            self.service.submit(self.frame,0,'a');self.assertTrue(entered.wait(1))
            started=time.monotonic();self.assertFalse(self.service.close(timeout=.01))
            self.assertLess(time.monotonic()-started,.2)
            with self.assertRaises(RuntimeError):self.service.submit(self.frame,1,'a')
            release.set();self.service._worker.thread.join(1)
            self.assertFalse(self.service._worker.thread.is_alive());self.assertIsNone(self.service.snapshot())
        finally:release.set()


if __name__=='__main__':unittest.main()
