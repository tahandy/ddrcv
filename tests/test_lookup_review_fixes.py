"""Regression checks for portable builds, interrupted provisioning and failed Apply."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import unquote

import numpy as np

from ddrcv.jacket_lookup import catalog
from ddrcv.jacket_lookup.service import SplashService
from test_song_lookup_integration import Names, Processor, wait


class PortableDescriptorTests(unittest.TestCase):
    def test_identical_bytes_across_blas_and_opencv_dispatch(self):
        script = '''
import hashlib, sys
import cv2, numpy as np
from ddrcv.jacket_lookup.features import PortableEncoder
cv2.setUseOptimized(sys.argv[1] == '1')
e = PortableEncoder()
rng = np.random.default_rng(143)
images = [rng.integers(0, 256, (s, s, 3), dtype=np.uint8) for s in (128, 150, 256)]
images += [np.zeros((128,128,3),np.uint8), np.full((128,128,3),255,np.uint8)]
v = np.stack([e.encode(im) for im in images])
assert np.isfinite(v).all()
print(hashlib.sha256(v.tobytes()).hexdigest())
'''
        hashes = []
        for core, optimized, features in (('Haswell', '1', ''), ('Sandybridge', '1', ''),
                                           ('Sandybridge', '0', ''), ('Sandybridge', '0', 'AVX,AVX2,FMA3,F16C')):
            env = {**os.environ, 'OPENBLAS_CORETYPE': core, 'OPENBLAS_NUM_THREADS': '1',
                   'MKL_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'NPY_DISABLE_CPU_FEATURES': features}
            result = subprocess.run([sys.executable, '-B', '-c', script, optimized], env=env,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            hashes.append(result.stdout.strip())
        self.assertEqual(len(set(hashes)), 1, hashes)


class CacheRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.commit = 'a'*40
        self.cache = self.root/'cache'/self.commit
        self.metadata = json.dumps(dict(meta={}, songs=[dict(name='Song', artist='Artist',
            jacket='ddr_world/a.png', charts=[dict(style='single', diffClass='expert', lvl=10,
                                                maxScore=300)])])).encode()
        self.jacket = b'fixture artwork'

    def fetch(self, url):
        return self.metadata if '/src/songs/' in unquote(url) else self.jacket

    def prepare(self):
        return catalog.prepare(self.root, event='event', ref=self.commit)

    def test_uncommitted_metadata_and_artwork_refetched_then_reload_offline(self):
        for name, data in (('src/songs/event.json', b'{partial'),
                           ('src/assets/jackets/ddr_world/a.png', b'partial artwork')):
            path = self.cache/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        with patch.object(catalog, 'fetch', side_effect=self.fetch) as fetch:
            _, prepared = self.prepare()
        self.assertEqual(prepared['failures'], [])
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual((self.cache/'src/songs/event.json').read_bytes(), self.metadata)
        self.assertEqual((self.cache/'src/assets/jackets/ddr_world/a.png').read_bytes(), self.jacket)
        with patch.object(catalog, 'fetch', side_effect=AssertionError('Network')):
            self.assertEqual(self.prepare()[1], prepared)

    def test_known_checksum_mismatch_still_fails_closed(self):
        with patch.object(catalog, 'fetch', side_effect=self.fetch):
            self.prepare()
        (self.cache/'src/songs/event.json').write_bytes(b'{partial')
        with patch.object(catalog, 'fetch', side_effect=AssertionError('Redownload')):
            with self.assertRaisesRegex(ValueError, 'Cached source checksum mismatch'):
                self.prepare()

    def test_failed_atomic_publish_does_not_replace_or_trust_partial_file(self):
        path = self.cache/'src/songs/event.json'
        path.parent.mkdir(parents=True)
        path.write_bytes(b'previous interrupted download')
        original = Path.replace
        def replace(source, destination):
            if destination == path:
                raise OSError('interrupted publication')
            return original(source, destination)
        with patch.object(catalog, 'fetch', side_effect=self.fetch), patch.object(Path, 'replace', replace):
            with self.assertRaisesRegex(OSError, 'interrupted publication'):
                self.prepare()
        self.assertEqual(path.read_bytes(), b'previous interrupted download')
        self.assertEqual(list(self.cache.rglob('*.tmp')), [])
        self.assertNotIn('src/songs/event.json', catalog.read_json(self.cache/'checksums.json'))
        with patch.object(catalog, 'fetch', side_effect=self.fetch):
            self.assertEqual(self.prepare()[1]['failures'], [])

    def test_resume_after_process_terminated_between_download_and_manifest(self):
        script = '''
import sys, threading
from pathlib import Path
from ddrcv.jacket_lookup import catalog
root = Path(sys.argv[1]); count = 0
def fetch(url):
    global count
    count += 1
    if count == 2:
        (root/'ready').write_text('download published')
        threading.Event().wait(30)
    return sys.argv[2].encode()
catalog.fetch = fetch
catalog.prepare(root, event='event', ref='a'*40)
'''
        process = subprocess.Popen([sys.executable, '-B', '-c', script, str(self.root), self.metadata.decode()],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            wait(lambda: (self.root/'ready').exists() or process.poll() is not None, timeout=10)
            self.assertTrue((self.root/'ready').exists())
        finally:
            process.terminate()
            process.communicate(timeout=5)
        self.assertFalse((self.cache/'checksums.json').exists())
        with patch.object(catalog, 'fetch', side_effect=self.fetch) as fetch:
            self.assertEqual(self.prepare()[1]['failures'], [])
            self.assertEqual(fetch.call_count, 3)
        with patch.object(catalog, 'fetch', side_effect=AssertionError('Network')):
            self.assertEqual(self.prepare()[1]['failures'], [])


class BlockedNames(Names):
    def __init__(self):
        super().__init__()
        self.release = threading.Event()
        self.thread = threading.Thread(target=self.release.wait, daemon=True)
        self.thread.start()

    def snapshot(self):
        return dict(p1='OLDNAME', p2=None)

    def close(self, timeout=1):
        self.thread.join(timeout)
        return not self.thread.is_alive()

    def threads(self):
        return (self.thread,)


class FailedApplyTests(unittest.TestCase):
    def test_failed_apply_clears_published_values_and_later_retry_recovers(self):
        from ddrcv.ingest.file_source import FramePacket
        from ddrcv.workbench.controller import Workbench
        from test_workbench import make_engine
        names = BlockedNames()
        processor = Processor()
        service = SplashService({'enabled': True}, names=names, processor=processor)
        frame = np.full((720,1280,3), 20, np.uint8)
        with tempfile.TemporaryDirectory() as tmp:
            wb = Workbench(Path(tmp), engine=make_engine(), start_publisher=False)
            try:
                wb.splash.close(); wb.splash = service; wb.player_names = service.names; wb.kind = 'video'
                # Establish a real diagnostic result, then confirm the old song.
                wb._process(FramePacket(frame, 0, 0))
                for timestamp in (0, .2):
                    n = service.completed
                    service.submit(frame, timestamp, 'song_splash', 'song_splash', (True,True), 'old-song')
                    wait(lambda: service.completed > n)
                snapshot = service.snapshot()
                self.assertEqual(snapshot['song']['charts']['p1']['max_ex'], 300)
                with wb.lock:
                    wb.message.update(snapshot)
                    wb.result['published'].update(deepcopy(snapshot))
                close = service.close
                with patch.object(service, 'close', side_effect=lambda: close(timeout=.01)), patch.object(
                        wb.publisher, 'send_message') as publish:
                    with self.assertRaisesRegex(RuntimeError, 'Recognition stopped'):
                        wb.configure_song_lookup({'enabled': False})
                    # No next frame is needed to clear both wire and diagnostic snapshots.
                    self.assertIsNone(wb.message['song'])
                    self.assertIsNone(wb.result['published']['song'])
                    self.assertEqual(wb.message['player_names'], dict(p1=None,p2=None))
                    self.assertTrue(publish.called)
                    self.assertIsNone(publish.call_args.args[0]['song'])
                self.assertEqual(service.status()['phase'], 'closed')
                self.assertIn(names.thread, service.threads())
                wb.engine.matcher.match.return_value = ('song_select', None)
                for index, timestamp in enumerate((1.,1.1,1.2,1.3), 1):
                    wb._process(FramePacket(frame, timestamp, index))
                self.assertIsNone(wb.message['song'])
                self.assertEqual(service.generation, wb.engine.session.song_generation)
                # Scoring still runs while recognition is unavailable.
                wb.engine.matcher.match.return_value = ('song_playing', None)
                for index, timestamp in enumerate((2.,2.1,2.2,2.3), 5):
                    wb._process(FramePacket(frame, timestamp, index))
                self.assertEqual(wb.message['score']['p1_score'], 2000)
                self.assertIsNone(wb.message['song'])
                names.release.set()
                wait(lambda: not names.thread.is_alive())
                self.assertTrue(wb.configure_song_lookup({'enabled': False})['ok'])
                self.assertIsNot(wb.splash, service)
                self.assertFalse(any(t.is_alive() for t in service.threads()))
            finally:
                names.release.set()
                wb.close()
                service.close()

    def test_close_clears_confirmation_and_discards_late_completion(self):
        processor = Processor()
        service = SplashService({'enabled': True}, names=Names(), processor=processor)
        frame = np.zeros((720,1280,3), np.uint8)
        try:
            processor.result['players']['p2'] = dict(status='uncertain_chart',max_ex=None)
            for timestamp in (0,.2):
                n = service.completed
                service.submit(frame,timestamp,'song_splash','song_splash',(True,True),'song')
                wait(lambda: service.completed > n)
            self.assertIsNotNone(service.snapshot()['song'])
            processor.entered.clear()
            processor.release = threading.Event()
            service.submit(frame,.4,'song_splash','song_splash',(True,True),'song')
            self.assertTrue(processor.entered.wait(1))
            self.assertFalse(service.close(timeout=.01))
            self.assertTrue(service.has_changes())
            self.assertIsNone(service.snapshot()['song'])
            processor.error = True
            processor.release.set()
            wait(lambda: not service.worker.thread.is_alive())
            self.assertIsNone(service.error)
            self.assertEqual(service.status()['phase'],'closed')
            service.submit(frame,1,'song_select','song_select',(True,True),'next')
            self.assertEqual(service.generation, 'next')
            self.assertIsNone(service.snapshot()['song'])
            self.assertTrue(service.close())
        finally:
            if processor.release:
                processor.release.set()
            service.close()


if __name__ == '__main__':
    unittest.main()
