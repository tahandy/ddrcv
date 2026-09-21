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
from ddrcv.results.delivery import Outbox, DeliveryError, format_payload, send_record, edit_record, webhook_identity, redact_error, message_receipt, screenshot_filename
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
    def test_screenshot_filename_timestamp_safe_names_and_unique_event(self):
        r = record()
        r['created_at'] = 0
        r['players'][0]['name'] = '../A:B*?'
        r['players'][1]['name'] = 'CON / Player'
        name = screenshot_filename(r)
        self.assertTrue(name.startswith('1970-01-01_00-00-00_000000_UTC_'))
        self.assertIn('P1-A_B', name)
        self.assertIn('P2-CON___Player', name)
        self.assertTrue(name.endswith('_abc123.png'))
        self.assertNotRegex(name, r'[<>:"/\\|?*]')
        r['event_id'] = 'abc124'
        self.assertNotEqual(name, screenshot_filename(r))
        for option in ('include_player_names', 'parse_names'):
            r[option] = False
            self.assertNotIn('_P1-', screenshot_filename(r))
            self.assertNotIn('_P2-', screenshot_filename(r))
            r[option] = True
        r['players'][0]['name'] = None
        self.assertNotIn('_P1-', screenshot_filename(r))
        self.assertIn('_P2-', screenshot_filename(r))

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

    def test_names_disabled_omits_name_crops_for_both_score_modes(self):
        for mode, presence, texts, expected in (
                ('ex', (True, True), ('0', '1,632'), (0, 1632)),
                ('money', (False, True), ('1,000,000',), (None, 1000000))):
            backend = Mock()
            backend.recognize_many.return_value = [OCRResult(text, .99) for text in texts]
            reader = ResultsReader({'parse_names': False}, recognizer=backend)
            values = reader.read(np.zeros((720, 1280, 3), np.uint8), presence, mode)
            self.assertEqual([p['name'] for p in values], [None, None])
            self.assertEqual(tuple(p['score'] for p in values), expected)
            self.assertEqual(len(backend.recognize_many.call_args.args[0]), sum(presence))


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

    def test_replay_duplicates_save_and_send_fresh_results_across_restart(self):
        self.assertFalse(self.service.status()['allow_replay_duplicates'])
        sender = Mock(return_value=dict(message_id='123', message_url=None))
        self.service.outbox.sender = sender
        self.service.configure(allow_replay_duplicates=True, discord=True,
                               webhook='https://discord.com/api/webhooks/1/test',
                               output_directory=str(Path(self.temp.name) / 'exports'))
        for count in (1, 2):
            self.settled()
            self.feed(4, raw='song_select', state='song_select')
            wait_for(lambda: len(self.service.status()['records']) == count and
                     all(r['delivery']['state'] == 'sent' and r.get('screenshot_export_path')
                         for r in self.service.status()['records']))
            if count == 1:
                config = dict(self.service.config)
                self.service.close()
                self.service = ResultsService(self.temp.name, config, reader=self.reader, sender=sender)
                self.service.reset('video', True, 'ex')
        records = self.service.status()['records']
        self.assertEqual(sender.call_count, 2)
        for key in ('event_id', 'screenshot_path', 'screenshot_export_path'):
            self.assertEqual(len({r[key] for r in records}), 2)
        for r in records:
            self.assertTrue(Path(r['screenshot_export_path']).is_file())
            self.assertIsNotNone(cv2.imread(r['screenshot_path']))
        self.service.configure(allow_replay_duplicates=False)
        self.service.reset('video', True, 'ex')
        self.settled()
        self.assertEqual(self.service.status()['phase'], 'already_saved')
        self.assertEqual(len(self.service.status()['records']), 2)
        self.assertEqual(sender.call_count, 2)

    def test_replay_policy_toggle_preserves_evidence_and_one_result_per_screen(self):
        self.feed(0)
        self.feed(2)
        episode = self.service.active
        generation, run, evidence = episode.generation, episode.run, episode.evidence
        self.service.configure(allow_replay_duplicates=True)
        self.assertIs(self.service.active, episode)
        self.assertEqual((episode.generation, episode.run), (generation, run))
        self.assertIs(episode.evidence, evidence)
        self.settled(2.2)
        self.assertEqual(len(self.service.status()['records']), 1)
        self.service.configure(allow_replay_duplicates=False)
        self.service.configure(allow_replay_duplicates=True)
        self.settled(6)
        self.assertEqual(len(self.service.status()['records']), 1)

    def test_enabling_repeats_unlatches_an_already_saved_replay(self):
        self.settled()
        self.service.reset('video', True, 'ex')
        self.feed(0)
        self.assertEqual(self.service.status()['phase'], 'already_saved')
        self.service.configure(allow_replay_duplicates=True)
        self.settled(.2)
        self.assertEqual(len(self.service.status()['records']), 2)
        self.assertTrue(self.service.feed_status()['allow_replay_duplicates'])

    def test_replay_duplicates_requires_boolean(self):
        for value in ('false', 1, None):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'allow_replay_duplicates'):
                self.service.configure(allow_replay_duplicates=value)

    def test_names_disabled_confirms_scores_and_formats_player_labels(self):
        self.service.configure(parse_names=False)
        self.settled()
        r = self.service.status()['records'][0]
        self.assertFalse(r['partial'])
        self.assertTrue(r['screenshot_confirmed'])
        self.assertFalse(r['parse_names'])
        self.assertEqual([p['name'] for p in r['players']], [None, None])
        self.assertEqual(r['outcome'], dict(kind='winner', winner=1, margin=17))
        text = format_payload(r)['embeds'][0]['description']
        self.assertIn('**P1**', text)
        self.assertIn('Winner: P2 (+17 EX)', text)
        self.assertNotIn('name unread', text)
        self.assertNotIn('Partial result', text)

    def test_screenshots_only_skips_ocr_and_delivers_at_departure(self):
        sender = Mock(return_value=dict(message_id='123', message_url=None))
        self.service.outbox.sender = sender
        self.service.configure(screenshots_only=True, discord=True,
                               webhook='https://discord.com/api/webhooks/1/test')
        self.settled()
        self.assertEqual(self.service.status()['records'], [])
        self.reader.read.assert_not_called()
        self.feed(4, raw='song_select', state='song_select')
        wait_for(lambda: self.service.status()['records'][0]['delivery']['state'] == 'sent')
        saved = self.service.status()['records'][0]
        self.assertTrue(saved['screenshots_only'])
        self.assertFalse(saved['partial'])
        self.assertFalse(saved['screenshot_confirmed'])
        self.assertFalse(saved['parse_names'])
        self.assertTrue(all(p['name'] is None and p['score'] is None for p in saved['players']))
        self.assertEqual(saved['outcome']['kind'], 'unavailable')
        self.assertTrue((cv2.imread(saved['screenshot_path']) == int(saved['timestamp'] * 10)).all())
        payload = format_payload(saved)
        self.assertEqual(payload['allowed_mentions'], {'parse': []})
        self.assertEqual(payload['embeds'][0]['description'],
                         'Screenshots only — score and name parsing disabled.')
        self.assertEqual(payload['embeds'][0]['image']['url'], 'attachment://results.png')
        sender.assert_called_once()

    def test_screenshots_only_live_deadline_keeps_short_screen_and_reloads(self):
        self.service.configure(screenshots_only=True)
        self.service.reset('live', False, 'money')
        self.feed(0, presence=(False, True))
        self.service.tick(10)
        self.assertTrue(self.service.flush())
        saved = self.service.status()['records'][0]
        self.assertEqual(saved['timestamp'], 0)
        self.assertEqual([p['present'] for p in saved['players']], [False, True])
        self.reader.read.assert_not_called()
        self.service.close()
        self.service = ResultsService(self.temp.name, dict(enabled=True), reader=self.reader)
        reloaded = self.service.status()['records'][0]
        self.assertTrue(reloaded['screenshots_only'])
        self.assertEqual(reloaded['delivery']['state'], 'saved')

    def test_live_screenshots_only_preserves_candidates_deadline_and_rejects_blocked_ocr(self):
        entered, release = threading.Event(), threading.Event()
        def blocked(*args):
            entered.set()
            release.wait(3)
            return [dict(name='WRONG', score=999), dict(name='WRONG', score=999)]
        self.reader.read.side_effect = blocked
        self.feed(0)
        self.feed(2, flush=False)
        self.assertTrue(entered.wait(2))
        try:
            episode = self.service.active
            selected = episode.best
            self.service.configure(screenshots_only=True)
            self.assertIs(self.service.active, episode)
            self.assertIs(episode.best, selected)
            self.assertEqual(episode.start, 0)
            self.feed(3, flush=False)
            self.service.tick(10)
            wait_for(lambda: len(self.service.status()['records']) == 1)
            self.assertTrue(self.service.busy)  # Screenshot saved while OCR is still blocked.
        finally:
            release.set()
        self.assertTrue(self.service.flush())
        saved = self.service.status()['records'][0]
        self.assertTrue(saved['screenshots_only'])
        self.assertEqual(saved['timestamp'], 3)
        self.assertTrue(all(p['name'] is None and p['score'] is None for p in saved['players']))
        self.assertIsNone(self.service.status()['error'])

    def test_screenshots_only_roundtrip_rejects_old_ocr_success_and_error(self):
        for fails in (False, True):
            with self.subTest(fails=fails):
                self.service.reset('video', True, 'ex')
                entered, release = threading.Event(), threading.Event()
                def blocked(*args):
                    entered.set()
                    release.wait(3)
                    if fails:
                        raise RuntimeError('stale OCR failure')
                    return [dict(name='OLD', score=999), dict(name='OLD', score=999)]
                self.reader.read.side_effect = blocked
                self.feed(0)
                self.feed(2, flush=False)
                self.assertTrue(entered.wait(2))
                try:
                    self.service.configure(screenshots_only=True)
                    self.service.configure(screenshots_only=False)
                finally:
                    release.set()
                self.assertTrue(self.service.flush())
                self.assertIsNone(self.service.status()['error'])
                self.assertEqual(self.service.status()['records'], [])
                for pair in self.service.active.evidence:
                    self.assertTrue(all(e.value is None for e in pair))
                self.assertTrue(all(p['score'] is None for p in self.service.active.best.players))

    def test_screenshots_only_can_resume_parsing_without_duplicate_saved_result(self):
        self.service.configure(screenshots_only=True)
        self.feed(0); self.feed(2)
        episode = self.service.active
        self.service.configure(screenshots_only=False)
        self.assertIs(self.service.active, episode)
        for i in range(8):
            self.feed(2.2 + i * .2)
        saved = self.service.status()['records'][0]
        self.assertFalse(saved['screenshots_only'])
        self.assertEqual(saved['players'][0]['score'], 1615)
        self.service.configure(screenshots_only=True)
        self.service.configure(screenshots_only=False)
        self.settled(4)
        self.assertEqual(len(self.service.status()['records']), 1)
        self.assertEqual(self.service.status()['records'][0]['players'], saved['players'])
        with self.assertRaisesRegex(ValueError, 'screenshots_only'):
            self.service.configure(screenshots_only='true')

    def test_screenshots_export_to_selected_folder_and_change_live(self):
        output = Path(self.temp.name) / 'named screenshots'
        self.service.configure(output_directory=str(output))
        self.settled()
        first = self.service.status()['records'][0]
        exported = Path(first['screenshot_export_path'])
        self.assertEqual(exported.parent, output.resolve())
        self.assertIn('_P1-XETA_P2-DANOOCT1_', exported.name)
        self.assertEqual(exported.read_bytes(), Path(first['screenshot_path']).read_bytes())
        old_outbox = self.service.outbox
        self.feed(4, raw='song_select', state='song_select')
        next_output = Path(self.temp.name) / 'timestamps only'
        self.service.configure(output_directory=str(next_output), include_player_names=False)
        self.settled(5)
        records = self.service.status()['records']
        self.assertEqual(len(records), 2)
        second = Path(records[1]['screenshot_export_path'])
        self.assertEqual(second.parent, next_output.resolve())
        self.assertNotIn('_P1-', second.name)
        self.assertEqual(records[1]['players'][0]['name'], 'XETA')
        self.assertTrue(second.is_file())
        self.assertTrue(exported.is_file())
        self.assertIs(self.service.outbox, old_outbox)

    def test_screenshot_export_failure_does_not_block_durable_result(self):
        blocked = Path(self.temp.name) / 'not-a-directory'
        blocked.write_text('existing file')
        self.service.configure(output_directory=str(blocked))
        self.settled()
        saved = self.service.status()['records'][0]
        self.assertTrue(Path(saved['screenshot_path']).is_file())
        self.assertTrue(saved['export_error'])
        self.assertEqual(blocked.read_text(), 'existing file')

    def test_toggle_names_invalidates_inflight_read_and_can_be_reenabled(self):
        entered, release = threading.Event(), threading.Event()
        original = self.reader.read.return_value
        def blocked(*args):
            entered.set()
            release.wait(3)
            return original
        self.reader.read.side_effect = blocked
        self.feed(0)
        self.feed(2, flush=False)
        self.assertTrue(entered.wait(2))
        try:
            self.service.configure(parse_names=False)
            self.assertEqual(self.service.status()['records'], [])
        finally:
            release.set()
        self.assertTrue(self.service.flush())
        self.reader.read.side_effect = None
        self.settled(3)
        self.assertTrue(all(p['name'] is None for p in self.service.status()['records'][0]['players']))
        self.feed(7, raw='song_select', state='song_select')
        self.service.configure(parse_names=True)
        self.settled(8)
        records = self.service.status()['records']
        self.assertEqual(len(records), 2)
        self.assertEqual(records[1]['players'][0]['name'], 'XETA')

    def test_settings_changes_do_not_duplicate_a_saved_live_screen(self):
        self.service.reset('live', False, 'ex')
        self.settled()
        self.service.configure(parse_names=False)
        self.settled(4)
        self.assertEqual(len(self.service.status()['records']), 1)
        self.service.configure(enabled=False)
        self.feed(8, raw='song_select', state='song_select')
        self.service.configure(enabled=True)
        self.settled(9)
        self.assertEqual(len(self.service.status()['records']), 2)

    def test_invalid_name_toggle_is_rejected_without_changing_settings(self):
        with self.assertRaisesRegex(ValueError, 'parse_names'):
            self.service.configure(parse_names='false')
        self.assertTrue(self.service.config['parse_names'])

    def test_partial_read_publishes_only_confirmed_fields_without_false_winner(self):
        self.reader.read.return_value=[dict(name=None,score=0),dict(name='P2',score=None)]
        for i in range(50):self.feed(i*.2)
        self.service.finish(); self.service.flush()
        r=self.service.status()['records'][0]
        self.assertTrue(r['partial']);self.assertFalse(r['screenshot_confirmed'])
        self.assertEqual(r['players'][0]['score'],0)
        self.assertIsNone(r['players'][0]['name']);self.assertIsNone(r['players'][1]['score'])
        self.assertEqual(r['outcome']['kind'],'unavailable')

    def test_scores_are_frozen_when_names_are_still_missing(self):
        self.reader.read.return_value=[dict(name=None,score=100),dict(name=None,score=200)]
        self.settled()
        self.reader.read.return_value=[dict(name=None,score=101),dict(name=None,score=200)]
        self.feed(3.6);self.service.finish();self.service.flush()
        r=self.service.status()['records'][0]
        self.assertEqual(r['players'][0]['score'],100);self.assertEqual(r['players'][1]['score'],200)
        self.assertEqual(r['outcome']['kind'],'winner')

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

    def test_scores_post_first_then_names_enrich_independently(self):
        self.reader.read.return_value = [dict(name=None, score=1615), dict(name=None, score=1632)]
        self.settled()
        first = self.service.status()['records'][0]
        image = Path(first['screenshot_path']).read_bytes()
        self.assertTrue(first['screenshot_confirmed'])
        self.assertEqual(first['revision'], 1)
        self.reader.read.return_value[0]['name'] = 'XETA'
        for i in range(18, 25): self.feed(i*.2)
        second = self.service.status()['records'][0]
        self.assertEqual([p['name'] for p in second['players']], ['XETA', None])
        self.reader.read.return_value[1]['name'] = 'DANOOCT1'
        for i in range(25, 32): self.feed(i*.2)
        final = self.service.status()['records'][0]
        self.assertEqual(final['revision'], 3)
        self.assertFalse(final['partial'])
        self.assertEqual(final['timestamp'], first['timestamp'])
        self.assertEqual(final['outcome'], first['outcome'])
        self.assertEqual(Path(final['screenshot_path']).read_bytes(), image)

    def test_name_enrichment_requires_matching_frozen_scores(self):
        self.reader.read.return_value = [dict(name=None, score=100), dict(name=None, score=200)]
        self.settled()
        self.reader.read.return_value = [dict(name='WRONG', score=101), dict(name='WRONG', score=200)]
        for i in range(18, 27): self.feed(i*.2)
        self.assertEqual([p['name'] for p in self.service.status()['records'][0]['players']], [None, None])

    def test_confirmed_names_survive_transient_local_write_failure(self):
        self.reader.read.return_value = [dict(name=None, score=1615), dict(name=None, score=1632)]
        self.settled()
        original = self.service.outbox.enrich_names
        calls = []
        def failing_once(*args):
            calls.append(args)
            if len(calls) == 1:
                raise OSError('temporary disk failure')
            return original(*args)
        with patch.object(self.service.outbox, 'enrich_names', side_effect=failing_once):
            self.reader.read.return_value[0]['name'] = 'XETA'
            for i in range(18, 25): self.feed(i*.2)
        self.assertGreaterEqual(len(calls), 2)
        result = self.service.status()['records'][0]
        self.assertEqual(result['players'][0]['name'], 'XETA')
        self.assertEqual(result['revision'], 2)
        self.assertIsNone(self.service.error)

    def test_settings_change_seals_saved_episode_enrichment(self):
        self.reader.read.return_value = [dict(name=None, score=1615), dict(name=None, score=1632)]
        self.settled()
        count = self.reader.read.call_count
        self.service.configure(include_player_names=False)
        for i in range(18, 25): self.feed(i*.2)
        self.assertEqual(self.reader.read.call_count, count)
        self.assertEqual(len(self.service.status()['records']), 1)

    def test_results_name_toggle_preserves_score_evidence_and_deadline(self):
        self.feed(0)
        for t in (2, 2.2, 2.4): self.feed(t)
        episode = self.service.active
        evidence = episode.evidence[0][1]
        self.service.configure(parse_names=False)
        self.assertIs(self.service.active, episode)
        self.assertIs(episode.evidence[0][1], evidence)
        self.assertEqual(episode.start, 0)
        for t in (2.6, 2.8, 3): self.feed(t)
        saved = self.service.status()['records'][0]
        self.assertEqual(saved['timestamp'], 3)
        self.assertEqual([p['name'] for p in saved['players']], [None, None])

    def test_disabling_names_seals_posted_result_without_removing_names(self):
        self.reader.read.return_value[1]['name'] = None
        self.settled()
        before = self.service.status()['records'][0]
        self.service.configure(parse_names=False)
        self.service.configure(parse_names=True)
        self.reader.read.return_value[1]['name'] = 'LATE'
        for i in range(18, 28): self.feed(i*.2)
        after = self.service.status()['records'][0]
        self.assertEqual(before['players'], after['players'])
        self.assertEqual(after['revision'], 1)

    def test_ocr_failure_selects_settled_low_motion_frame_and_keeps_alternative(self):
        self.reader.read.side_effect = RuntimeError('offline model failure')
        for t, value in ((0, 0), (2, 100), (2.2, 100), (2.4, 100), (2.6, 240)):
            self.service.submit(np.full_like(self.frame, value), t, 'song_result', 'song_result')
            self.service.flush()
        self.service.finish(); self.service.flush()
        saved = self.service.status()['records'][0]
        self.assertEqual(saved['timestamp'], 2.4)
        self.assertFalse(saved['screenshot_confirmed'])
        self.assertEqual([p['score'] for p in saved['players']], [None, None])
        self.assertEqual([p['timestamp'] for p in saved['alternatives']], [2.6])
        self.assertTrue((cv2.imread(saved['screenshot_path']) == 100).all())

    def test_live_deadline_saves_newer_frame_while_ocr_is_blocked(self):
        entered, release = threading.Event(), threading.Event()
        def blocked(*args):
            entered.set(); release.wait(4)
            return self.reader.read.return_value
        self.reader.read.side_effect = blocked
        self.service.reset('live', False, 'ex')
        try:
            self.feed(0); self.feed(2, flush=False)
            self.assertTrue(entered.wait(1))
            self.feed(3, flush=False)
            self.service.tick(10)
            wait_for(lambda: bool(self.service.status()['records']))
            saved = self.service.status()['records'][0]
            self.assertEqual(saved['timestamp'], 3)
            self.assertTrue(saved['partial'])
            self.assertEqual([p['score'] for p in saved['players']], [None, None])
        finally:
            release.set(); self.service.flush()
        self.assertEqual(self.service.status()['records'][0]['revision'], 1)

    def test_old_episode_cannot_enrich_next_song(self):
        self.reader.read.return_value = [dict(name=None, score=1615), dict(name=None, score=1632)]
        self.settled()
        entered, release = threading.Event(), threading.Event()
        def blocked(*args):
            entered.set(); release.wait(4)
            return [dict(name='OLD', score=1615), dict(name='OLD', score=1632)]
        self.reader.read.side_effect = blocked
        try:
            self.feed(3.6, flush=False); self.assertTrue(entered.wait(1))
            self.service.finish(); self.service.reset('new', False, 'ex')
        finally:
            release.set(); self.service.flush()
        self.assertEqual(self.service.status()['records'][0]['revision'], 1)

    def test_capture_gap_and_unknown_break_motion_comparisons(self):
        self.feed(0); self.feed(.2); self.feed(2)
        self.assertIsNone(self.service.active.motion)
        self.feed(2.2); self.feed(2.4, raw='unknown'); self.feed(2.6)
        self.assertIsNone(self.service.active.motion)

    def test_export_failure_still_delivers(self):
        sender = Mock(return_value=dict(message_id='123'))
        self.service.outbox.sender = sender
        blocked = Path(self.temp.name) / 'file'
        blocked.touch()
        self.service.configure(discord=True, webhook='mock', output_directory=str(blocked))
        self.settled()
        wait_for(lambda: self.service.status()['records'][0]['delivery']['state'] == 'sent')
        self.assertTrue(self.service.status()['records'][0]['export_error'])
        sender.assert_called_once()


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

    def unnamed(self):
        result = record()
        for p in result['players']: p['name'] = None
        result['partial'] = True
        return result

    def test_names_during_send_are_persisted_and_edit_same_message(self):
        entered, release = threading.Event(), threading.Event()
        sent = []
        def sender(webhook, result, path):
            sent.append(json.loads(json.dumps(result)))
            entered.set(); release.wait(4)
            return dict(message_id='123')
        box = self.box(sender)
        box.editor = Mock()
        try:
            box.save(self.unnamed(), self.frame)
            self.assertTrue(entered.wait(1))
            box.enrich_names('abc123', ['XETA', None])
            box.enrich_names('abc123', ['XETA', 'DANOOCT1'])
            release.set()
            wait_for(lambda: box.snapshot()['records'][0]['delivery']['delivered_revision'] == 3)
            saved = box.snapshot()['records'][0]
            self.assertEqual(len(sent), 1)
            self.assertIsNone(sent[0]['players'][0]['name'])
            box.editor.assert_called_once()
            self.assertEqual(saved['delivery']['message_id'], '123')
            self.assertEqual(saved['players'][1]['name'], 'DANOOCT1')
            persisted = json.loads((Path(self.temp.name)/'abc123/result.json').read_text())
            self.assertEqual(persisted['revision'], 3)
        finally: release.set()

    def test_unsent_names_coalesce_into_initial_post(self):
        box = self.box(enabled=False)
        box.editor = Mock()
        box.save(self.unnamed(), self.frame)
        box.enrich_names('abc123', ['XETA', 'DANOOCT1'])
        box.configure(box.webhook, True)
        wait_for(lambda: box.snapshot()['records'][0]['delivery']['state'] == 'sent')
        self.assertEqual(box.sender.call_args.args[1]['players'][0]['name'], 'XETA')
        self.assertEqual(box.snapshot()['records'][0]['name_update']['state'], 'idle')
        box.editor.assert_not_called()

    def test_name_edit_failure_preserves_sent_result_and_manual_retry(self):
        box = self.box()
        box.editor = Mock(side_effect=DeliveryError('HTTP 404'))
        box.save(self.unnamed(), self.frame)
        wait_for(lambda: box.snapshot()['records'][0]['delivery']['state'] == 'sent')
        box.enrich_names('abc123', ['XETA', None])
        wait_for(lambda: box.snapshot()['needs_attention'] == 1)
        self.assertEqual(box.snapshot()['records'][0]['delivery']['state'], 'sent')
        box.editor.side_effect = None
        box.command('retry_names', 'abc123')
        wait_for(lambda: box.snapshot()['records'][0]['name_update']['state'] == 'idle')
        box.sender.assert_called_once()

    def test_edit_rate_limit_budget_and_changed_webhook(self):
        box = self.box()
        box.editor = Mock(side_effect=DeliveryError('rate limit', True, 0))
        box.save(self.unnamed(), self.frame)
        wait_for(lambda: box.snapshot()['records'][0]['delivery']['state'] == 'sent')
        box.enrich_names('abc123', ['XETA', None])
        wait_for(lambda: box.snapshot()['needs_attention'] == 1)
        self.assertEqual(box.editor.call_count, 5)
        box.configure('https://discord.com/api/webhooks/2/different', True)
        box.command('retry_names', 'abc123')
        wait_for(lambda: 'original' in (box.snapshot()['records'][0]['name_update']['error'] or ''))
        self.assertEqual(box.editor.call_count, 5)
        box.sender.assert_called_once()

    def test_pending_edit_recovers_on_restart_without_another_post(self):
        box = self.box()
        box.save(self.unnamed(), self.frame)
        wait_for(lambda: box.snapshot()['records'][0]['delivery']['state'] == 'sent')
        box.configure(box.webhook, False)
        box.enrich_names('abc123', ['XETA', None])
        box.close()
        editor = Mock()
        reopened = Outbox(self.temp.name, box.webhook, True, sender=box.sender, editor=editor)
        self.boxes.append(reopened)
        wait_for(lambda: reopened.snapshot()['records'][0]['delivery']['delivered_revision'] == 2)
        editor.assert_called_once(); box.sender.assert_called_once()

    def test_new_name_during_edit_is_not_overwritten_by_old_acknowledgement(self):
        box = self.box()
        entered, release = threading.Event(), threading.Event()
        def edit(*args): entered.set(); release.wait(4)
        box.editor = Mock(side_effect=edit)
        try:
            box.save(self.unnamed(), self.frame)
            wait_for(lambda: box.snapshot()['records'][0]['delivery']['state'] == 'sent')
            box.enrich_names('abc123', ['XETA', None])
            self.assertTrue(entered.wait(1))
            box.enrich_names('abc123', ['XETA', 'DANOOCT1'])
            release.set()
            wait_for(lambda: box.snapshot()['records'][0]['delivery']['delivered_revision'] == 3)
            self.assertEqual(box.editor.call_count, 2)
            self.assertEqual(box.snapshot()['records'][0]['players'][1]['name'], 'DANOOCT1')
            box.sender.assert_called_once()
        finally: release.set()

    def test_old_failures_remain_visible_beyond_recent_twenty(self):
        box = self.box(enabled=False)
        for i in range(23):
            r = record(); r['event_id'] = f'event-{i}'; r['created_at'] = i
            box.save(r, self.frame)
        with box.lock: box.records['event-0']['delivery']['state'] = 'failed'
        snapshot = box.snapshot()
        self.assertEqual(snapshot['needs_attention'], 1)
        self.assertEqual(len(snapshot['records']), 21)
        self.assertEqual(snapshot['records'][0]['event_id'], 'event-0')

    def test_edit_http_preserves_attachment_mentions_and_classifies_failures(self):
        import requests
        r = self.unnamed()
        hook = 'https://discord.com/api/webhooks/1/secret'
        r['delivery'] = dict(message_id='123', webhook_identity=webhook_identity(hook),
                            image_url='https://cdn.discordapp.com/attachments/456/789/results.png?expired=signature')
        response = Mock(status_code=200)
        response.__enter__ = Mock(return_value=response); response.__exit__ = Mock(return_value=False)
        response.json.return_value = dict(id='123', channel_id='456', embeds=[dict(image={
            'url':'https://cdn.discordapp.com/attachments/456/789/results.png'})])
        with patch('ddrcv.results.delivery.requests.patch', return_value=response) as edit, patch('ddrcv.results.delivery.requests.post') as post:
            self.assertEqual(edit_record(hook, r)['message_id'], '123')
            self.assertTrue(edit.call_args.args[0].endswith('/messages/123'))
            body = edit.call_args.kwargs['json']
            self.assertNotIn('attachments', body); self.assertNotIn('files', body)
            self.assertEqual(body['allowed_mentions'], {'parse':[]})
            self.assertEqual(body['embeds'][0]['image']['url'], 'https://cdn.discordapp.com/attachments/456/789/results.png')
            post.assert_not_called()
            for code, retryable in ((429, True), (503, True), (401, False), (404, False)):
                response.status_code = code
                response.json.return_value = {'retry_after':0}
                with self.assertRaises(DeliveryError) as caught: edit_record(hook, r)
                self.assertEqual(caught.exception.retryable, retryable)
        with patch('ddrcv.results.delivery.requests.patch', side_effect=requests.Timeout()):
            with self.assertRaises(DeliveryError) as caught: edit_record(hook, r)
            self.assertTrue(caught.exception.retryable)

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


class WebhookProbeTests(unittest.TestCase):
    def test_text_probe_requires_acknowledgement_and_handles_delivery_failures(self):
        import requests
        from ddrcv.results.delivery import send_test_message
        hook = 'https://discord.com/api/webhooks/1/private-test-token'
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.status_code = 200
        response.json.return_value = dict(id='123', channel_id='456')
        with patch('ddrcv.results.delivery.requests.post', return_value=response) as post:
            send_test_message(hook)
            self.assertEqual(post.call_args.kwargs['params'], {'wait': 'true'})
            self.assertEqual(post.call_args.kwargs['timeout'], (3, 10))
            self.assertEqual(post.call_args.kwargs['json']['allowed_mentions'], {'parse': []})
            self.assertIn('webhook test', post.call_args.kwargs['json']['content'])
            self.assertNotIn('files', post.call_args.kwargs)
            for code in (401, 404, 429, 503):
                response.status_code = code
                response.json.return_value = {'retry_after': 2}
                with self.subTest(code=code), self.assertRaises(DeliveryError):
                    send_test_message(hook)
            response.status_code = 200
            response.json.return_value = {}
            with self.assertRaisesRegex(DeliveryError, 'did not confirm'):
                send_test_message(hook)
            post.side_effect = requests.Timeout(f'Timed out: {hook}')
            with self.assertRaises(DeliveryError) as caught:
                send_test_message(hook)
            self.assertNotIn('private-test-token', str(caught.exception))


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
