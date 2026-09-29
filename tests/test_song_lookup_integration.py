"""Catalog/version boundaries and temporal safety of the packaged splash service."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np

from ddrcv.jacket_lookup.catalog import ChartIndex, normalize_catalog
from ddrcv.jacket_lookup.config import validate_config
from ddrcv.jacket_lookup.fingerprint import gallery_fingerprint
from ddrcv.jacket_lookup.selection import project_catalog, SelectedCharts
from ddrcv.jacket_lookup.service import SplashService


def wait(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError('Worker did not finish')
        time.sleep(.001)


def raw_song(name='Song', hash='a', jacket='ddr_world/a.png', score=300):
    return dict(name=name, artist='Artist', saHash=hash, jacket=jacket,
                charts=[dict(style='single', diffClass='expert', lvl=10, maxScore=score)])


def fixture():
    raw = raw_song()
    catalog = normalize_catalog({'ddr_world': dict(songs=[raw])}, commit='a'*40)
    gallery = dict(catalog=catalog, entries=[dict(sha256='image-a', paths=[raw['jacket']],
                                                songs={'sa:a': 'Song'})])
    selected = normalize_catalog({'event': dict(songs=[raw], defaults={'lvls': [19]}),
                                  'ddr_world': dict(songs=[raw])}, event='event', commit='b'*40)
    selected['assets'] = {raw['jacket']: {'sha256': 'image-a'}}
    return gallery, deepcopy(selected)


class CatalogTests(unittest.TestCase):
    def test_pinned_cross_revision_join_and_unfiltered_pool(self):
        gallery, selected = fixture()
        projected = project_catalog(gallery, selected)
        self.assertEqual(projected['unsupported'], [])
        chart = SelectedCharts(projected).resolve('sa:a', 'single', 'expert')
        self.assertEqual(chart['max_ex'], 300)
        self.assertEqual(chart['metadata_level'], 10)
        self.assertEqual(chart['source_commit'], 'b'*40)
        self.assertEqual(projected['catalog']['defaults'], {'lvls': [19]})
        self.assertEqual(SelectedCharts(projected).resolve('sa:a', 'double', 'expert')['status'],
                         'chart_outside_pool')

    def test_identity_conflict_and_unsupported_override(self):
        gallery, selected = fixture()
        selected['records'][0]['original']['saHash'] = 'changed'
        self.assertEqual(project_catalog(gallery, selected)['unsupported'][0]['reason'], 'unsupported_identity')
        gallery, selected = fixture()
        selected['records'][0]['charts'][0]['jacket'] = 'ddr_world/new.png'
        selected['assets']['ddr_world/new.png'] = {'sha256': 'new-image'}
        projected = project_catalog(gallery, selected)
        chart = SelectedCharts(projected).resolve('sa:a', 'single', 'expert')
        self.assertEqual(chart, dict(status='unsupported_artwork', max_ex=None))

    def test_new_alias_blocks_artwork_not_every_variant_of_song(self):
        gallery, selected = fixture()
        gallery['entries'].append(dict(sha256='unique-variant', paths=['ddr_world/unique.png'],
                                       songs={'sa:a': 'Song'}))
        new = normalize_catalog({'ddr_world': dict(songs=[raw_song('Other', 'other')])})['records']
        projected = project_catalog(gallery, selected, alias_records=new)
        self.assertIn('image-a', projected['blocked_artwork'])
        self.assertNotIn('unique-variant', projected['blocked_artwork'])

    def test_supplement_conflicts_and_missing_values(self):
        original = raw_song(score=None)
        source = {'event': dict(songs=[original]), 'ddr_world': dict(songs=[raw_song()])}
        selected = normalize_catalog(source, event='event', commit='c'*40)
        chart = ChartIndex(selected).resolve('sa:a', 'single', 'expert')
        self.assertEqual((chart['max_ex'], chart['source_dataset']), (300, 'ddr_world'))
        source['ddr_world']['songs'][0]['charts'][0]['lvl'] = 11
        self.assertEqual(ChartIndex(normalize_catalog(source, event='event')).resolve(
            'sa:a', 'single', 'expert')['status'], 'missing_max_ex')
        gallery, selected = fixture()
        duplicate = deepcopy(selected['records'][0])
        duplicate['charts'][0]['max_ex'] = 500
        selected['records'].append(duplicate)
        self.assertEqual(SelectedCharts(project_catalog(gallery, selected)).resolve(
            'sa:a', 'single', 'expert')['status'], 'ambiguous_chart')

    def test_conflicting_secondary_identifier_cannot_supplement_score(self):
        event, world = raw_song(score=None), raw_song()
        event['saIndex'], world['saIndex'] = 1, 2
        selected = normalize_catalog({'event': dict(songs=[event]),
                                      'ddr_world': dict(songs=[world])}, event='event')
        self.assertIsNone(selected['records'][0]['charts'][0]['max_ex'])

    def test_preparation_detects_world_alias_at_new_path_by_checksum(self):
        from ddrcv.jacket_lookup import catalog
        from urllib.parse import unquote
        gallery, _ = fixture()
        source_song = raw_song()
        alias = raw_song('Other', 'other', 'ddr_world/new-copy.png')
        sources = {'event': dict(meta={}, songs=[source_song]),
                   'ddr_world': dict(meta={}, songs=[source_song, alias])}
        def fetch(url):
            path = unquote(url.split('/src/', 1)[1])
            if path.startswith('songs/'):
                return json.dumps(sources[Path(path).stem]).encode()
            return b'identical artwork bytes'
        gallery['entries'][0]['sha256'] = catalog.sha256(b'identical artwork bytes')
        with tempfile.TemporaryDirectory() as tmp, patch.object(catalog, 'fetch', side_effect=fetch):
            _, selected = catalog.prepare(tmp, event='event', ref='b'*40, include_world_artwork=True)
        self.assertIn(alias['jacket'], selected['assets'])
        aliases = normalize_catalog({'ddr_world': sources['ddr_world']})['records']
        projected = project_catalog(gallery, selected, alias_records=aliases)
        self.assertIn(gallery['entries'][0]['sha256'], projected['blocked_artwork'])

    def test_portable_fingerprint_excludes_machine_details_but_binds_inputs(self):
        gallery, _ = fixture()
        gallery.update(method='classical', size=128, fingerprint='color-gradient-v1')
        vectors = np.array([[1, 2]], np.float32)
        images = np.zeros((1, 128, 128, 3), np.uint8)
        before = gallery_fingerprint(gallery, vectors, images)
        gallery.update(build_seconds=99, catalog_sha256='another-machine')
        gallery['catalog']['assets'] = {'location': 'C:/another/path'}
        self.assertEqual(before, gallery_fingerprint(gallery, vectors, images))
        images[0, 1, 1, 0] = 1
        self.assertNotEqual(before, gallery_fingerprint(gallery, vectors, images))
        images[:] = 0
        gallery['entries'][0]['songs']['sa:another'] = 'Other'
        self.assertNotEqual(before, gallery_fingerprint(gallery, vectors, images))

    def test_full_mode_does_not_require_an_inactive_event_field(self):
        for value in ('', 'unfinished event URL'):
            cfg = validate_config(dict(mode='full',event=value))
            self.assertEqual(cfg['event'], value)
            with self.assertRaises(ValueError):
                validate_config({**cfg,'mode':'event'})

    def test_config_and_legacy_migration(self):
        cfg = validate_config({'event': 'https://ddr.tools/#game-dia_del_ritmo_26'})
        self.assertFalse(cfg['enabled'])
        self.assertEqual(cfg['style'], 'single')
        with self.assertRaises(ValueError):
            validate_config({'style': 'duo'})
        from ddrcv.apps.driver_config import normalize_config
        with self.assertLogs('ddrcv.apps.driver_config', level='WARNING'):
            cfg = normalize_config({'jacket_database': {'prebuilt_database': 'old.pkl'}})
        self.assertNotIn('jacket_database', cfg)


class AssetBoundaryTests(unittest.TestCase):
    def test_catalog_namespaces_do_not_collide(self):
        from ddrcv.jacket_lookup.assets import selection_key
        self.assertNotEqual(selection_key(dict(mode='full',event='full')),
                            selection_key(dict(mode='event',event='full')))

    def test_failed_refresh_preserves_active_pointer(self):
        from ddrcv.jacket_lookup import assets
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            cfg=validate_config(dict(assets_dir=tmp))
            pointer=root/'active'/(assets.selection_key(cfg)+'.json')
            pointer.parent.mkdir(parents=True)
            pointer.write_text('{"previous": true}',encoding='utf-8')
            frozen=assets.profile()
            gallery=root/'galleries'/frozen['gallery_fingerprint']
            gallery.mkdir(parents=True)
            (gallery/'index.json').write_bytes(b'{}')
            (gallery/'vectors.npz').write_bytes(b'')
            with patch.object(assets,'Lookup'), patch.object(assets.catalog,'prepare',side_effect=OSError('offline')):
                with self.assertRaisesRegex(OSError,'offline'):
                    assets.prepare(cfg,refresh=True)
            self.assertEqual(pointer.read_text(encoding='utf-8'),'{"previous": true}')

    def test_ocr_selection_does_not_require_templates(self):
        from ddrcv.jacket_lookup import assets
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp:
            cfg=validate_config(dict(assets_dir=tmp,difficulty_method='ocr'))
            pointer=Path(tmp)/'active'/(assets.selection_key(cfg)+'.json')
            pointer.parent.mkdir(parents=True)
            pointer.write_text('{}',encoding='utf-8')
            lookup=Mock()
            with patch.object(assets,'_load',return_value=lookup), patch(
                    'ddrcv.jacket_lookup.difficulty.DifficultyTemplates',side_effect=ValueError('missing bank')):
                assets.load(cfg)
                lookup._get_recognizer.return_value.warmup.assert_called_once()
                with self.assertRaisesRegex(ValueError,'missing bank'):
                    assets.load({**cfg,'difficulty_method':'template'})

    def test_failed_preflight_keeps_current_desktop_runtime(self):
        from unittest.mock import Mock
        from ddrcv.desktop.controller import Desk
        with tempfile.TemporaryDirectory() as tmp:
            desk=Desk(tmp)
            current=Mock()
            current.thread=None
            desk.runtime=current
            desk.draft['song_lookup']=dict(enabled=True,assets_dir=str(Path(tmp)/'missing'))
            try:
                with self.assertRaises(FileNotFoundError):
                    desk.apply()
                current.stop.assert_not_called()
            finally:
                desk.close()


class CatalogInformationTests(unittest.TestCase):
    def write_bundle(self, root, commit='b'*40, prepared_at=None):
        from ddrcv.jacket_lookup import assets, catalog
        from uuid import uuid4
        gallery, selected = fixture()
        selected['commit'] = commit
        selected['upstream_updated'] = {'event': 1704067200000}
        projected = project_catalog(gallery, selected)
        if prepared_at:
            projected['prepared_at'] = prepared_at
        bundle = uuid4().hex
        path = root/'bundles'/bundle/'selection.json'
        catalog.dump_json(path, projected)
        pointer = dict(schema=1,bundle=bundle,gallery=assets.profile()['gallery_fingerprint'],
                       selection_sha256=catalog.sha256(path.read_bytes()))
        catalog.dump_json(root/'active/event-event.json', pointer)
        return path

    def test_description_uses_recorded_dates_without_loading_gallery_or_ocr(self):
        from ddrcv.jacket_lookup import assets
        with tempfile.TemporaryDirectory() as tmp:
            self.write_bundle(Path(tmp))
            with patch.object(assets,'Lookup',side_effect=AssertionError('Image arrays loaded')):
                info = assets.describe(dict(assets_dir=tmp,event='event'))
            self.assertTrue(info['available'])
            self.assertEqual(info['dataset_updated_at'], '2024-01-01T00:00:00+00:00')
            self.assertIsNone(info['prepared_at'])
            self.assertEqual(info['commit'], 'b'*40)
            self.assertEqual(info['assets_dir'], str(Path(tmp).resolve()))

    def test_changed_pointer_updates_prepared_version_but_not_loaded_bundle(self):
        from ddrcv.jacket_lookup import assets
        from ddrcv.jacket_lookup.operations import CatalogPreparation
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_bundle(root)
            cfg = dict(assets_dir=tmp,event='event')
            operations = CatalogPreparation()
            before = operations.describe(cfg)
            with patch.object(assets,'Lookup',return_value=Mock()):
                loaded = assets.load(cfg)
            self.write_bundle(root,commit='c'*40,prepared_at='2026-09-29T12:00:00+00:00')
            after = operations.describe(cfg)
            self.assertEqual(after['commit'], 'c'*40)
            self.assertEqual(after['prepared_at'], '2026-09-29T12:00:00+00:00')
            self.assertNotEqual(before['bundle'], after['bundle'])
            self.assertEqual(loaded.bundle_info['commit'], 'b'*40)

    def test_inspection_reports_missing_or_corrupt_metadata(self):
        from ddrcv.jacket_lookup import assets
        with tempfile.TemporaryDirectory() as tmp:
            cfg = dict(assets_dir=tmp,event='event')
            self.assertFalse(assets.describe(cfg)['available'])
            path = self.write_bundle(Path(tmp))
            path.write_text('{}',encoding='utf-8')
            info = assets.describe(cfg)
            self.assertFalse(info['available'])
            self.assertIn('checksum',info['error'])

    def test_relocating_metadata_preserves_version_and_checksums(self):
        from ddrcv.jacket_lookup import assets
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, target = root/'streaming machine', root/'second client'
            self.write_bundle(source)
            before = assets.describe(dict(assets_dir=str(source),event='event'))
            shutil.copytree(source,target)
            after = assets.describe(dict(assets_dir=str(target),event='event'))
            self.assertTrue(after['available'])
            for key in ('commit','gallery','selection_sha256','bundle','dataset_updated_at'):
                self.assertEqual(before[key],after[key])
            self.assertNotEqual(before['assets_dir'],after['assets_dir'])


class Names:
    def __init__(self):
        self.changed = threading.Event()
    def reset(self, generation=None): pass
    def submit(self, *args): pass
    def snapshot(self): return dict(p1=None, p2=None)
    def close(self, timeout=1): return True
    def threads(self): return ()


class Processor:
    def __init__(self):
        gallery, selected = fixture()
        self.selection = dict(catalog=selected)
        self.lookup = type('Gallery', (), dict(catalog=gallery['catalog']))()
        self.result = dict(accepted=True, reason='matched',
                           song=dict(song_id='sa:a', name='Song', index=0),
                           players={f'p{p}': dict(difficulty='expert', metadata_level=10,
                                max_ex=300, status='matched', source_dataset='event', source_commit='b'*40)
                                    for p in (1, 2)}, timings_ms={'total': 1})
        self.entered = threading.Event()
        self.release = None
        self.error = False
        self.calls = []
    def analyze(self, frame, **kwargs):
        self.calls.append(kwargs)
        self.entered.set()
        if self.release:
            self.release.wait(3)
        if self.error:
            raise RuntimeError('worker failed')
        return deepcopy(self.result)
    def close(self, timeout=1): return True
    def threads(self): return ()


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.processor = Processor()
        self.service = SplashService({'enabled': True}, names=Names(), processor=self.processor)
        self.frame = np.zeros((720, 1280, 3), np.uint8)
    def tearDown(self):
        if self.processor.release:
            self.processor.release.set()
        self.service.close()
    def submit(self, t, state='song_splash', presence=(True, True), generation='song'):
        count = self.service.completed
        self.service.submit(self.frame, t, state, state, presence, generation)
        if state == 'song_splash':
            wait(lambda: self.service.completed > count)
    def test_two_frames_and_independent_players_then_no_more_work(self):
        self.processor.result['players']['p2'] = dict(status='uncertain_chart', max_ex=None)
        self.submit(0); self.assertIsNone(self.service.snapshot()['song'])
        self.submit(.2)
        song = self.service.snapshot()['song']
        self.assertEqual(song['charts']['p1']['max_ex'], 300)
        self.assertIsNone(song['charts']['p2'])
        self.processor.result['players']['p2'] = deepcopy(self.processor.result['players']['p1'])
        self.submit(.4); self.submit(.6)
        self.assertEqual(self.processor.calls[-1]['remaining_players'], [2])
        self.assertIsNotNone(self.processor.calls[-1]['confirmed_song'])
        count = self.service.completed
        self.service.submit(self.frame, .8, 'song_splash', 'song_splash', (True, True), 'song')
        self.assertEqual(self.service.completed, count)
        self.assertEqual(self.service.status()['phase'], 'confirmed')
    def test_rejection_and_gap_break_agreement(self):
        self.submit(0)
        self.processor.result['accepted'] = False
        self.submit(.2)
        self.processor.result['accepted'] = True
        self.submit(.4)
        self.assertIsNone(self.service.snapshot()['song'])
        self.submit(1.4)
        self.assertIsNone(self.service.snapshot()['song'])
        self.submit(1.6)
        self.assertIsNotNone(self.service.snapshot()['song'])
    def test_duplicate_timestamp_and_state_gate(self):
        self.submit(0)
        self.service.submit(self.frame, 0, 'song_splash', 'song_splash', (True, True), 'song')
        self.service.submit(self.frame, .2, 'song_splash', 'song_select', (True, True), 'song')
        self.assertEqual(self.service.completed, 1)
        self.submit(.4); self.assertIsNone(self.service.snapshot()['song'])
        self.submit(.6); self.assertIsNotNone(self.service.snapshot()['song'])
    def test_lifetime_and_single_player_explicit_double(self):
        self.service.config['style'] = 'double'
        self.submit(0, presence=(False, True))
        self.submit(.2, presence=(False, True))
        song = self.service.snapshot()['song']
        self.assertIsNone(song['charts']['p1'])
        self.assertEqual(song['charts']['p2']['style'], 'double')
        self.submit(.4, state='song_playing', presence=(False, True))
        self.submit(.6, state='song_result', presence=(False, True))
        self.assertEqual(self.service.snapshot()['song'], song)
        self.service.reset('new')
        self.assertIsNone(self.service.snapshot()['song'])
    def test_late_errors_and_results_after_reset_or_close(self):
        self.processor.release = threading.Event()
        self.service.submit(self.frame, 0, 'song_splash', 'song_splash', (True, True), 'old')
        self.assertTrue(self.processor.entered.wait(1))
        self.service.reset('new')
        self.processor.error = True
        self.processor.release.set()
        wait(lambda: not self.service.worker.status()['busy'])
        self.assertIsNone(self.service.error)
        self.assertIsNone(self.service.snapshot()['song'])
    def test_first_completion_after_fade_is_stale(self):
        self.processor.release = threading.Event()
        self.service.submit(self.frame, 0, 'song_splash', 'song_splash', (True, True), 'song')
        self.assertTrue(self.processor.entered.wait(1))
        self.service.submit(self.frame, .1, 'song_select', 'song_splash', (True, True), 'song')
        self.processor.release.set()
        wait(lambda: not self.service.worker.status()['busy'])
        self.assertEqual(self.service.song_evidence.count, 0)
        self.submit(.2)
        self.assertIsNone(self.service.snapshot()['song'])
        self.submit(.4)
        self.assertIsNotNone(self.service.snapshot()['song'])

    def test_bounded_mailbox_copy_and_shutdown(self):
        self.processor.release = threading.Event()
        self.service.submit(self.frame, 0, 'song_splash', 'song_splash', (True, True), 'song')
        self.assertTrue(self.processor.entered.wait(1))
        for t in (.2, .4, .6):
            self.service.submit(self.frame, t, 'song_splash', 'song_splash', (True, True), 'song')
        self.assertEqual(self.service.worker.status()['pending'], 1)
        self.assertEqual(self.service.worker.status()['replaced'], 2)
        self.assertFalse(self.service.close(timeout=.01))
        self.processor.release.set()
        wait(lambda: not self.service.worker.thread.is_alive())
        self.assertIsNone(self.service.snapshot()['song'])

    def test_runtime_failure_is_status_not_capture_exception(self):
        self.processor.error = True
        self.submit(0)
        self.assertEqual(self.service.status()['phase'], 'failed')
        self.assertIsNone(self.service.snapshot()['song'])


class OptionalTests(unittest.TestCase):
    def test_no_neural_runtime_imported_by_template_core(self):
        script = """
import builtins
original = builtins.__import__
def checked(name, *args, **kwargs):
    if name.split('.')[0] in ('rapidocr','onnxruntime','torch','timm','faiss'):
        raise AssertionError('Unexpected optional import: '+name)
    return original(name, *args, **kwargs)
builtins.__import__ = checked
from ddrcv.jacket_lookup.assets import PACKAGE_ASSETS
from ddrcv.jacket_lookup.difficulty import DifficultyTemplates
from ddrcv.jacket_lookup.service import SplashService
DifficultyTemplates(PACKAGE_ASSETS / 'templates')
s = SplashService()
assert s.snapshot() == dict(song=None, player_names=dict(p1=None,p2=None))
assert s.close()
"""
        result = subprocess.run([sys.executable, '-B', '-c', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
