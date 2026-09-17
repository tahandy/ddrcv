"""CLI/panel results wiring, paused delivery feedback, and source lifetime."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import numpy as np

from ddrcv.apps import driver_ddr_tbd5 as driver
from ddrcv.results.service import ResultsService
from ddrcv.workbench.app import create_app
from ddrcv.workbench.controller import Workbench, redact
from test_workbench import make_engine, make_video
from test_results import wait_for, record


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.reader=Mock()
        self.reader.read.return_value=[dict(name='XETA',score=1615),dict(name='DANOOCT1',score=1632)]
        engine=make_engine();engine.matcher.match.return_value=('song_result',None)
        with patch('ddrcv.results.service.ResultsReader',return_value=self.reader):
            self.wb=Workbench(self.root/'panel',engine=engine,start_publisher=False)
        self.client=create_app(self.wb).test_client()

    def tearDown(self):
        self.wb.close();self.temp.cleanup()

    def test_panel_config_persistence_redaction_and_screenshot_endpoint(self):
        hook='https://discord.com/api/webhooks/123/private-token'
        response=self.client.post('/api/action',json=dict(action='results_config',enabled=True,discord=False,webhook=hook),headers={'X-Rehearsal':'1'})
        self.assertEqual(response.status_code,200)
        self.assertNotIn('private-token',self.client.get('/api/status').text)
        self.assertNotIn('private-token',json.dumps(redact(['request failed '+hook])))
        self.assertEqual(json.loads(self.wb.results_config_path.read_text())['webhook'],hook)
        r=record();r['auto_publish']=False
        self.wb.results.outbox.save(r,np.zeros((720,1280,3),np.uint8))
        with self.client.get('/api/results/abc123/screenshot') as screenshot:
            self.assertEqual(screenshot.status_code,200)
        self.assertEqual(self.client.get('/api/results/missing/screenshot').status_code,404)
        self.assertEqual(self.client.post('/api/action',json={'action':'results_retry','event_id':'abc123'}).status_code,403)
        response=self.client.post('/api/action',json={'action':'results_retry','event_id':'abc123'},headers={'X-Rehearsal':'1'})
        self.assertEqual(response.status_code,400) # Discord remains disabled

    def test_delivery_status_updates_paused_feed_and_controls_during_network_stall(self):
        entered=threading.Event();release=threading.Event()
        def sender(*args):entered.set();release.wait(3);return dict(message_id='123')
        self.wb.results.outbox.sender=sender
        self.wb.results.configure(enabled=True,discord=True,webhook='https://discord.com/api/webhooks/1/test')
        try:
            self.wb.results.outbox.save(record(),np.zeros((720,1280,3),np.uint8))
            self.assertTrue(entered.wait(2))
            started=time.perf_counter();self.wb.submit('pause')
            self.assertLess(time.perf_counter()-started,.25)
            self.assertEqual(self.client.get('/api/status').json['published']['results']['latest']['delivery']['state'],'sending')
            release.set()
            wait_for(lambda:self.wb.message['results']['latest']['delivery']['state']=='sent')
            self.assertFalse(self.wb.playing)
        finally:release.set();self.wb.results.outbox.worker.join(.1)

    def test_eof_and_score_mode_reset_are_integrated(self):
        path=self.root/'short.avi';make_video(path,count=12,fps=20)
        self.wb.results.configure(enabled=True)
        self.wb.submit('score_mode',mode='ex')
        self.wb.submit('open',kind='video',path=str(path))
        for _ in range(13):self.wb.submit('step')
        self.assertTrue(self.wb.results.flush())
        r=self.wb.results.status()['records'][0]
        self.assertTrue(r['partial']);self.assertEqual(r['score_mode'],'ex')
        generation=self.wb.results.generation
        self.wb.submit('score_mode',mode='money')
        self.assertGreater(self.wb.results.generation,generation)
        self.assertEqual(self.wb.results.mode,'money')
        self.assertIsNone(self.wb.engine.session.trackers[0].max_per_frame)

    def test_looping_eof_finalizes_partial_once_and_keeps_controls_responsive(self):
        path = self.root / 'loop.avi'
        make_video(path, count=12, fps=20)
        self.wb.results.configure(enabled=True)
        self.wb.submit('open', kind='video', path=str(path))
        self.wb.submit('playback', loop=True, speed=2)
        epoch = self.wb.epoch
        self.wb.submit('play')
        wait_for(lambda: self.wb.epoch >= epoch + 2)
        self.wb.submit('pause')
        self.assertTrue(self.wb.results.flush())
        records = self.wb.results.status()['records']
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0]['partial'])
        self.assertFalse(records[0]['screenshot_confirmed'])
        self.assertTrue(Path(records[0]['screenshot_path']).is_file())
        self.assertGreaterEqual(self.wb.results.status()['deduplicated'], 1)

    def test_loop_eof_seals_retained_frame_while_ocr_is_blocked(self):
        entered = threading.Event()
        release = threading.Event()
        def slow(*args):
            entered.set()
            release.wait(5)
            return [dict(name='LATE', score=1), dict(name='LATE', score=2)]
        self.reader.read.side_effect = slow
        path = self.root / 'ocr-loop.avi'
        make_video(path, count=12, fps=20)
        self.wb.results.configure(enabled=True, settling_seconds=.01)
        self.wb.submit('open', kind='video', path=str(path))
        self.wb.submit('playback', loop=True, speed=2)
        epoch = self.wb.epoch
        try:
            self.wb.submit('play')
            self.assertTrue(entered.wait(2))
            wait_for(lambda: self.wb.epoch > epoch)
            began = time.perf_counter()
            self.wb.submit('pause')
            self.assertLess(time.perf_counter() - began, .25)
            wait_for(lambda: len(self.wb.results.status()['records']) == 1)
            event = self.wb.results.status()['records'][0]
            self.assertIsNone(event['players'][0]['name'])
            release.set()
            self.assertTrue(self.wb.results.flush())
            self.assertEqual(self.wb.results.status()['records'][0], event)
        finally:
            release.set()

    def test_cli_result_branch_submits_frames_without_legacy_parser(self):
        frame=np.zeros((720,1280,3),np.uint8)
        fetcher=Mock();fetcher.get_frame.side_effect=[frame]*10+[KeyboardInterrupt()]
        matcher=Mock();matcher.match.return_value=('song_result',None)
        extractor=Mock();publisher=Mock();service=Mock()
        service.feed_status.return_value={'phase':'confirming'}
        config=dict(state={},score_extractor={'glyph_dir':None},ingest={'simple':{'uri':0}},publish={},
                    score_mode='ex',results={'enabled':True},driver_debug={'render_frame':False})
        with patch.object(driver,'StateRotation',return_value=matcher),patch.object(driver,'ScoreExtractor',return_value=extractor),patch.object(driver,'create_frame_fetcher',return_value=fetcher),patch.object(driver,'create_publisher',return_value=publisher),patch.object(driver,'ResultsService',return_value=service):
            driver.main(config,Mock())
        self.assertEqual(service.submit.call_count,10)
        service.close.assert_called_once();fetcher.stop.assert_called_once();publisher.stop.assert_called_once()
        self.assertIn('results',publisher.send_message.call_args.args[0])


if __name__=='__main__':unittest.main()
