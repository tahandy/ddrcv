"""Results behavior with deterministic OCR, real persistence and mocked HTTP."""
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from ddrcv.ocr import OCRResult
from ddrcv.results.recognition import Evidence, ResultsReader, parse_number, outcome
from ddrcv.results.delivery import Outbox, DeliveryError, format_payload, send_record, redact_error, message_receipt
from ddrcv.results.service import ResultsService


def wait_for(predicate, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError('Timed out waiting for background result')


def players(a=1615, b=1632, name='XETA'):
    return [dict(present=True, name=name, score=a), dict(present=True, name='DANOOCT1', score=b)]


def record(a=1615, b=1632):
    p = players(a, b)
    return dict(event_id='abc123', source_id='video', interval=[10., 25.], timestamp=13.,
                frame_index=390, players=p, score_mode='ex', outcome=outcome(p, 'ex'),
                partial=False, screenshot_confirmed=True, rehearsal=True, auto_publish=True)


class ParseTests(unittest.TestCase):
    def test_strict_scores_zero_and_money_semantics(self):
        for text, expected in [('0',0), ('1,615',1615), ('00012',12), ('1632',1632)]:
            self.assertEqual(parse_number(text, 'ex'), expected)
        for text in ('-1', '1.615', '1,61', 'O', '', 'EX 1632', '1 632', 'NaN', '100000'):
            self.assertIsNone(parse_number(text, 'ex'))
        self.assertEqual(parse_number('1,000,000', 'money'), 1000000)
        self.assertIsNone(parse_number('1,000,001', 'money'))
        self.assertEqual(outcome(players(), 'money')['kind'], 'unavailable')

    def test_evidence_requires_fresh_time_and_resets_on_contradiction_or_gap(self):
        evidence = Evidence()
        for _ in range(20):
            self.assertFalse(evidence.observe(100, 0))
        for t in (.2,.4,.6,.8):
            self.assertFalse(evidence.observe(100,t))
        self.assertTrue(evidence.observe(100,1.))
        self.assertFalse(evidence.observe(101,1.2))
        self.assertFalse(evidence.observe(101,3.))
        self.assertFalse(evidence.observe(None,3.2))

    def test_reader_independent_fields_low_confidence_and_absence(self):
        backend = Mock()
        backend.recognize_many.return_value = [OCRResult('', .9), OCRResult('1,632',.99)]
        result = ResultsReader(recognizer=backend).read(np.zeros((720,1280,3),np.uint8),(False,True),'ex')
        self.assertEqual(result,[dict(name=None,score=None),dict(name=None,score=1632)])
        self.assertEqual(len(backend.recognize_many.call_args.args[0]),2)
        backend.recognize_many.return_value = [OCRResult('NAME',.79), OCRResult('1632',.79)]
        self.assertEqual(ResultsReader(recognizer=backend).read(np.zeros((720,1280,3),np.uint8),(False,True),'ex')[1],dict(name=None,score=None))

    def test_formatter_winner_tie_zero_partial_and_escaping(self):
        for a,b,expected in [(100,90,'XETA (+10 EX)'),(90,100,'DANOOCT1 (+10 EX)'),(0,0,'TIE')]:
            payload=format_payload(record(a,b)); self.assertIn(expected,payload['embeds'][0]['description'])
            self.assertEqual(payload['allowed_mentions'],{'parse':[]})
        r=record(None,0);r['partial']=True;r['screenshot_confirmed']=False
        r['players'][0]['name']='@everyone **bad**'
        text=format_payload(r)['embeds'][0]['description']
        self.assertIn('Winner unavailable',text);self.assertIn('unconfirmed',text)
        self.assertNotIn('**bad**',text);self.assertNotIn('**TIE**',text)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.frame=np.zeros((720,1280,3),np.uint8)
        self.reader=Mock()
        self.reader.read.return_value=[dict(name='XETA',score=1615),dict(name='DANOOCT1',score=1632)]
        self.service=ResultsService(self.temp.name,dict(enabled=True),reader=self.reader)
        self.service.reset('video',True,'ex')

    def tearDown(self):
        self.service.close();self.temp.cleanup()

    def feed(self,t,raw='song_result',state='song_result',presence=(True,True),flush=True):
        self.frame[:]=int(t*10)%256
        self.service.submit(self.frame,t,raw,state,presence,int(t*30))
        if flush:self.assertTrue(self.service.flush())

    def settled(self,start=0):
        for i in range(18):self.feed(start+i*.2)

    def test_complete_frame_and_record_share_evidence_and_interval(self):
        self.settled();records=self.service.status()['records'];self.assertEqual(len(records),1)
        r=records[0];self.assertFalse(r['partial']);self.assertTrue(r['screenshot_confirmed'])
        self.assertEqual(r['outcome'],dict(kind='winner',winner=1,margin=17))
        saved=cv2.imread(r['screenshot_path']);self.assertTrue((saved==int(r['timestamp']*10)%256).all())
        self.feed(4,state='total_result',raw='total_result')
        wait_for(lambda:self.service.status()['records'][0]['interval'][1]>=3.4-1e-6)
        self.service.reset('video',True,'ex');self.settled(1)
        self.assertEqual(len(self.service.status()['records']),1)
        self.assertGreater(self.service.status()['deduplicated'],0)

    def test_partial_read_publishes_only_confirmed_fields_without_false_winner(self):
        self.reader.read.return_value=[dict(name=None,score=0),dict(name='P2',score=None)]
        for i in range(52):self.feed(i*.2)
        r=self.service.status()['records'][0]
        self.assertTrue(r['partial']);self.assertFalse(r['screenshot_confirmed'])
        self.assertEqual(r['players'][0]['score'],0)
        self.assertIsNone(r['players'][0]['name']);self.assertIsNone(r['players'][1]['score'])
        self.assertEqual(r['outcome']['kind'],'unavailable')

    def test_contradiction_discards_previously_confirmed_field(self):
        self.reader.read.return_value=[dict(name=None,score=100),dict(name=None,score=200)]
        self.settled()
        self.reader.read.return_value=[dict(name=None,score=101),dict(name=None,score=200)]
        self.feed(3.6);self.service.finish();self.service.flush()
        r=self.service.status()['records'][0]
        self.assertIsNone(r['players'][0]['score']);self.assertEqual(r['players'][1]['score'],200)
        self.assertEqual(r['outcome']['kind'],'unavailable')

    def test_single_player_and_money_never_get_ex_outcome(self):
        for i in range(18):self.feed(i*.2,presence=(False,True))
        r=self.service.status()['records'][0]
        self.assertFalse(r['players'][0]['present']);self.assertEqual(r['outcome']['kind'],'unavailable')
        self.service.reset('moneyvideo',True,'money');self.settled()
        r=self.service.status()['records'][-1]
        self.assertEqual(r['score_mode'],'money');self.assertEqual(r['outcome']['kind'],'unavailable')
        self.assertIn('Money:',format_payload(r)['embeds'][0]['description'])

    def test_unknown_gaps_do_not_duplicate_or_confirm(self):
        self.feed(0)
        for i in range(10,14):self.feed(i*.2)
        self.feed(2.8,raw='unknown')
        self.feed(3.);self.feed(3.2)
        self.assertEqual(self.service.status()['records'],[])
        for i in range(17,23):self.feed(i*.2)
        self.assertEqual(len(self.service.status()['records']),1)
        self.feed(5,raw='unknown',state='unknown');self.feed(5.2)
        self.assertEqual(len(self.service.status()['records']),1)

    def test_slow_ocr_does_not_block_and_reset_invalidates_inflight(self):
        entered=threading.Event();release=threading.Event()
        def slow(*args):
            entered.set();release.wait(3)
            return [dict(name='OLD',score=1),dict(name='OLD',score=2)]
        self.reader.read.side_effect=slow
        self.feed(0);self.feed(2,flush=False);self.assertTrue(entered.wait(2))
        began=time.perf_counter()
        for i in range(11,25):self.feed(i*.2,flush=False)
        self.assertLess(time.perf_counter()-began,.25)
        self.assertGreater(self.service.replaced_frames,0)
        self.service.reset('new',True,'ex');release.set();self.service.flush()
        self.assertEqual(self.service.status()['records'],[])

    def test_deduplication_and_interval_persistence_during_network_stall(self):
        entered = threading.Event()
        release = threading.Event()
        calls = []
        def slow(*args):
            calls.append(args[1]['event_id'])
            entered.set()
            release.wait(5)
            return dict(message_id='123')
        self.service.outbox.sender = slow
        self.service.configure(discord=True, webhook='mock')
        try:
            self.settled()
            self.assertTrue(entered.wait(2))
            for i in range(18, 41):
                self.feed(i * .2)
            event = self.service.status()['records'][0]
            path = Path(event['screenshot_path']).with_name('result.json')
            self.assertEqual(event['interval'][1], 8.)
            self.assertGreaterEqual(json.loads(path.read_text())['interval'][1], 7.5)
            self.service.reset('video', True, 'ex')
            self.settled(5)
            self.assertEqual(len(self.service.status()['records']), 1)
            self.assertEqual(self.service.status()['deduplicated'], 1)
            release.set()
            wait_for(lambda: self.service.status()['records'][0]['delivery']['state'] == 'sent')
            self.assertEqual(json.loads(path.read_text())['interval'][1], 8.)
            self.assertEqual(calls, [event['event_id']])
        finally:
            release.set()

    def test_close_preserves_fallback_and_prevents_late_ocr_writes(self):
        entered = threading.Event()
        release = threading.Event()
        def slow(*args):
            entered.set()
            release.wait(5)
            return [dict(name='LATE', score=1), dict(name='LATE', score=2)]
        self.reader.read.side_effect = slow
        self.feed(0)
        self.feed(2, flush=False)
        self.assertTrue(entered.wait(2))
        replacement = None
        try:
            began = time.perf_counter()
            self.service.close(.5)
            self.assertLess(time.perf_counter() - began, .8)
            self.assertTrue(self.service.worker.is_alive())
            replacement = Outbox(self.temp.name)
            self.assertTrue(replacement.available)
            records = replacement.snapshot()['records']
            self.assertEqual(len(records), 1)
            self.assertTrue(records[0]['partial'])
            self.assertIsNone(records[0]['players'][0]['name'])
            path = Path(records[0]['screenshot_path']).with_name('result.json')
            before = path.read_bytes()
            release.set()
            self.service.worker.join(2)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(len(list(Path(self.temp.name).glob('*/result.json'))), 1)
            with self.assertRaises(OSError):
                self.service.outbox.save(record(), self.frame)
        finally:
            release.set()
            if replacement:
                replacement.close()

    def test_pending_eof_bundle_survives_reset_before_disk_save(self):
        entered = threading.Event()
        release = threading.Event()
        original = self.service.outbox.save
        def slow(*args):
            entered.set()
            release.wait(5)
            return original(*args)
        with patch.object(self.service.outbox, 'save', side_effect=slow):
            try:
                self.feed(0)
                self.feed(.2)
                self.service.finish()
                self.assertTrue(entered.wait(2))
                self.service.reset('video', True, 'ex')
                self.feed(0, flush=False)
                self.assertEqual(self.service.status()['deduplicated'], 1)
                # Disk is still working: bounded shutdown must retain ownership.
                self.service.close(.01)
                competing = Outbox(self.temp.name)
                try:
                    self.assertFalse(competing.available)
                finally:
                    competing.close()
                release.set()
                self.service.persistence_worker.join(2)
                self.service.outbox.worker.join(2)
                recovered = Outbox(self.temp.name)
                try:
                    self.assertTrue(recovered.available)
                    self.assertEqual(len(recovered.snapshot()['records']), 1)
                finally:
                    recovered.close()
            finally:
                release.set()

    def test_eof_before_settled_retains_unconfirmed_screenshot(self):
        self.feed(0);self.feed(.2);self.service.finish();self.service.flush()
        r=self.service.status()['records'][0]
        self.assertFalse(r['screenshot_confirmed']);self.assertTrue(r['partial'])
        self.assertTrue(Path(r['screenshot_path']).is_file())

    def test_model_error_preserves_partial_and_reports_failure(self):
        self.reader.read.side_effect=RuntimeError('model missing')
        self.feed(0);self.feed(2);self.service.finish();self.service.flush()
        self.assertIn('model missing',self.service.status()['error'])
        self.assertTrue(self.service.status()['records'][0]['partial'])

    def test_disk_failure_visible_and_no_false_saved_event(self):
        with patch.object(self.service.outbox,'save',side_effect=OSError('disk full')):
            self.settled()
        self.assertIn('disk full',self.service.status()['error'])
        self.assertEqual(self.service.status()['records'],[])

    def test_repeated_timestamps_do_not_advance(self):
        self.feed(0)
        for _ in range(30):self.feed(2)
        self.assertEqual(self.service.status()['records'],[])
        self.assertEqual(self.reader.read.call_count,1)


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.frame=np.zeros((20,20,3),np.uint8)
        self.boxes=[]

    def tearDown(self):
        for box in self.boxes:box.close()
        self.temp.cleanup()

    def box(self,sender=None,enabled=True):
        box=Outbox(self.temp.name,'https://discord.com/api/webhooks/1/secret',enabled,
                   sender=sender or Mock(return_value=dict(message_id='123',message_url='https://discord.com/channels/@me/1/123')))
        self.boxes.append(box);return box

    def test_success_durable_and_not_sent_on_restart(self):
        sender=Mock(return_value=dict(message_id='123',message_url='https://discord.com/channels/@me/1/123'))
        box=self.box(sender);box.save(record(),self.frame)
        wait_for(lambda:box.snapshot()['records'][0]['delivery']['state']=='sent')
        box.close();reopened=self.box(sender);time.sleep(.2)
        self.assertEqual(sender.call_count,1)
        self.assertEqual(reopened.snapshot()['records'][0]['delivery']['message_id'],'123')

    def test_ambiguous_timeout_retries_and_preserves_event_id(self):
        sender=Mock(side_effect=[DeliveryError('timeout',True,0),dict(message_id='123')])
        box=self.box(sender);box.save(record(),self.frame)
        wait_for(lambda:box.snapshot()['records'][0]['delivery']['state']=='sent')
        self.assertEqual(sender.call_count,2)
        self.assertEqual([call.args[1]['event_id'] for call in sender.call_args_list],['abc123']*2)

    def test_permanent_failure_manual_retry_and_redaction(self):
        sender=Mock(side_effect=DeliveryError('https://discord.com/api/webhooks/1/secret HTTP 401'))
        box=self.box(sender);box.save(record(),self.frame)
        wait_for(lambda:box.snapshot()['records'][0]['delivery']['state']=='failed')
        self.assertEqual(sender.call_count,1)
        self.assertNotIn('secret',json.dumps(box.snapshot()))
        sender.side_effect=None;sender.return_value=dict(message_id='1')
        box.command('retry','abc123')
        wait_for(lambda:box.snapshot()['records'][0]['delivery']['state']=='sent')

    def test_rate_limit_budget_and_pending_restart(self):
        sender=Mock(side_effect=DeliveryError('rate limited',True,0))
        box=self.box(sender);box.save(record(),self.frame)
        wait_for(lambda:box.snapshot()['records'][0]['delivery']['state']=='failed')
        self.assertEqual(sender.call_count,5)
        box.close()
        doc=json.loads((Path(self.temp.name)/'abc123/result.json').read_text())
        doc['delivery'].update(state='sending',attempts=1)
        (Path(self.temp.name)/'abc123/result.json').write_text(json.dumps(doc))
        resumed=self.box()
        wait_for(lambda:resumed.snapshot()['records'][0]['delivery']['state']=='sent')

    def test_saved_requires_explicit_send_and_replication_is_explicit(self):
        sender=Mock(return_value=dict(message_id='1'));box=self.box(sender)
        r=record();r['auto_publish']=False;box.save(r,self.frame);time.sleep(.2)
        sender.assert_not_called();box.command('retry','abc123')
        wait_for(lambda:sender.call_count==1)
        wait_for(lambda:box.snapshot()['records'][0]['delivery']['state']=='sent')
        with self.assertRaises(ValueError):box.command('retry','abc123')
        box.command('republish','abc123');wait_for(lambda:sender.call_count==2)

    def test_storage_error_does_not_send(self):
        sender=Mock();box=self.box(sender)
        with patch.object(box,'_write',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):box.save(record(),self.frame)
        sender.assert_not_called();self.assertEqual(box.snapshot()['records'],[])

    def test_network_stall_does_not_block_outbox_status_or_shutdown(self):
        entered=threading.Event();release=threading.Event()
        def slow(*args):entered.set();release.wait(3);return dict(message_id='1')
        box=self.box(slow);box.save(record(),self.frame);self.assertTrue(entered.wait(2))
        began=time.perf_counter();self.assertEqual(box.snapshot()['records'][0]['delivery']['state'],'sending')
        box.close(.01);self.assertLess(time.perf_counter()-began,.1)
        release.set();box.worker.join(2)

    def test_competing_outbox_owner_is_rejected_and_lock_recovers(self):
        first=self.box(enabled=False)
        second=self.box()
        self.assertFalse(second.available)
        self.assertIn('already in use',second.snapshot()['error'])
        with self.assertRaises(OSError):second.save(record(),self.frame)
        first.close()
        third=self.box(enabled=False)
        self.assertTrue(third.available)

    def test_inline_image_acknowledgement_is_success_without_top_level_attachment(self):
        body=dict(id='123',channel_id='456',attachments=[],embeds=[dict(image=dict(
            url='https://cdn.discordapp.com/attachments/456/789/results.png?signature=ignored',width=1280,height=720))])
        self.assertEqual(message_receipt(body)['message_id'],'123')
        body['embeds'][0]['image']['url']='https://example.com/results.png'
        with self.assertRaises(DeliveryError) as caught:message_receipt(body)
        self.assertFalse(caught.exception.retryable)
        self.assertEqual(caught.exception.receipt['message_id'],'123')
        with self.assertRaises(DeliveryError) as caught:message_receipt({})
        self.assertTrue(caught.exception.retryable)

    def test_command_saturation_is_visible(self):
        entered = threading.Event()
        release = threading.Event()
        def slow(*args):
            entered.set()
            release.wait(5)
            return dict(message_id='123')
        box = self.box(slow)
        try:
            box.save(record(), self.frame)
            self.assertTrue(entered.wait(2))
            for _ in range(32):
                box.command('interval', 'abc123', end=30)
            with self.assertRaisesRegex(ValueError, 'queue is full'):
                box.command('interval', 'abc123', end=31)
        finally:
            release.set()

    def test_http_contract_and_failure_classification(self):
        image=Path(self.temp.name)/'a.png';cv2.imwrite(str(image),self.frame)
        response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        response.status_code=200;response.json.return_value=dict(id='123',channel_id='456',guild_id='789',attachments=[dict(filename='results.png')])
        with patch('ddrcv.results.delivery.requests.post',return_value=response) as post:
            result=send_record('https://discord.com/api/webhooks/1/secret',record(),image)
            self.assertEqual(result['message_id'],'123');self.assertEqual(post.call_args.kwargs['timeout'],(3,10))
            self.assertEqual(post.call_args.kwargs['params'],{'wait':'true'})
            response.status_code=429;response.json.return_value={'retry_after':2.5}
            with self.assertRaises(DeliveryError) as caught:send_record('x',record(),image)
            self.assertEqual(caught.exception.retry_after,2.5)
            response.status_code=503
            with self.assertRaises(DeliveryError) as caught:send_record('x',record(),image)
            self.assertTrue(caught.exception.retryable)
            response.status_code=400
            with self.assertRaises(DeliveryError) as caught:send_record('x',record(),image)
            self.assertFalse(caught.exception.retryable)
            response.status_code=200;response.json.return_value={'id':'123','channel_id':'456','attachments':[]}
            with self.assertRaises(DeliveryError):send_record('x',record(),image)


@unittest.skipUnless(os.environ.get('DDRCV_RESULTS_VIDEO') and os.environ.get('DDRCV_TEST_OCR_MODEL'), 'Set local video/model paths')
class RealResultsTests(unittest.TestCase):
    def test_tab_independent_names_and_headline_ex(self):
        reader=ResultsReader(dict(ocr=dict(model_path=os.environ['DDRCV_TEST_OCR_MODEL'],allow_download=False)))
        cap=cv2.VideoCapture(os.environ['DDRCV_RESULTS_VIDEO'])
        cap.set(cv2.CAP_PROP_POS_MSEC,265000);ok,frame=cap.read();cap.release();self.assertTrue(ok)
        expected=[dict(name='XETA',score=1615),dict(name='DANOOCT1',score=1632)]
        self.assertEqual(reader.read(frame,(True,True),'ex'),expected)
        frame[430:640]=0
        self.assertEqual(reader.read(frame,(True,True),'ex'),expected)


if __name__=='__main__':unittest.main()
