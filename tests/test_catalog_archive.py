"""Portable catalogs: direct offline loading, qualification, and atomic replacement."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import cv2
import numpy as np

from ddrcv.jacket_lookup import assets, catalog
from ddrcv.jacket_lookup.archive import CatalogArchive, json_bytes, write_archive
from ddrcv.jacket_lookup.config import catalog_path, validate_config
from ddrcv.jacket_lookup.features import build_index
from ddrcv.jacket_lookup.fingerprint import gallery_fingerprint
from ddrcv.jacket_lookup.lookup import Lookup
from ddrcv.jacket_lookup.operations import CatalogPreparation
from ddrcv.jacket_lookup.selection import project_catalog


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        rng = np.random.default_rng(884)
        self.images = [rng.integers(0, 255, (128, 128, 3), dtype=np.uint8) for _ in range(3)]
        songs, images = [], {}
        for i, image in enumerate(self.images):
            data = cv2.imencode('.png', image)[1].tobytes()
            (self.root / f'{i}.png').write_bytes(data)
            jacket = f'ddr_world/{i}.png'
            images[jacket] = dict(path=f'{i}.png', sha256=catalog.sha256(data))
            songs.append(dict(name=f'Song {i}', artist='Artist', saHash=str(i), jacket=jacket,
                              charts=[dict(style='single', diffClass='expert', lvl=14, maxScore=1500+i)]))
        raw = dict(songs=songs)
        data = catalog.normalize_catalog({'ddr_world': raw}, commit='a'*40)
        data['assets'] = images
        catalog.dump_json(self.root/'source.json', data)
        build_index(self.root/'source.json', self.root/'index')
        lookup = Lookup(self.root/'index')
        self.profile = dict(schema=1, score=.4, margin=.28, source_commit='a'*40,
                            gallery_fingerprint=gallery_fingerprint(lookup.meta, lookup.vectors, lookup.images))
        self.metadata = (self.root/'index/index.json').read_bytes()
        self.arrays = (self.root/'index/vectors.npz').read_bytes()
        selected = catalog.normalize_catalog({'event': raw, 'ddr_world': raw}, event='event', commit='b'*40)
        selected['assets'] = images
        self.selection = project_catalog(lookup.meta, selected)
        self.selection.update(gallery_fingerprint=self.profile['gallery_fingerprint'], bundle_id='a'*32)
        self.path = self.root/'portable.ddrcatalog'
        self.cfg = validate_config(dict(event='event', catalog_file=str(self.path), assets_dir=str(self.root/'cache')))
        self.profile_patch = patch.object(assets, 'profile', return_value=self.profile)
        self.profile_patch.start()
        self.addCleanup(self.profile_patch.stop)
        self.write()

    def write(self, selection=None, metadata=None, arrays=None, profile=None):
        write_archive(self.path, self.metadata if metadata is None else metadata,
                      self.arrays if arrays is None else arrays,
                      self.selection if selection is None else selection, profile or self.profile)

    def rewrite(self, transform):
        with zipfile.ZipFile(self.path) as archive:
            payloads = {n: archive.read(n) for n in archive.namelist()}
        transform(payloads)
        with zipfile.ZipFile(self.path, 'w') as archive:
            for name, data in payloads.items():
                archive.writestr(name, data)

    def legacy(self):
        root = self.root/'cache'
        gallery = root/'galleries'/self.profile['gallery_fingerprint']
        gallery.mkdir(parents=True)
        (gallery/'index.json').write_bytes(self.metadata)
        (gallery/'vectors.npz').write_bytes(self.arrays)
        selection = root/'bundles'/('a'*32)/'selection.json'
        catalog.dump_json(selection, self.selection)
        catalog.dump_json(root/'active/event-event.json', dict(schema=1,bundle='a'*32,
            gallery=self.profile['gallery_fingerprint'],selection_sha256=catalog.sha256(selection.read_bytes())))
        return root

    def test_direct_offline_load_exact_matching_and_chart_provenance(self):
        folder = Lookup(self.root/'index', thresholds=self.profile)
        with patch('socket.socket.connect', side_effect=AssertionError('Network')), patch.object(
                zipfile.ZipFile, 'extractall', side_effect=AssertionError('Extraction')):
            loaded = assets.load(self.cfg)
        a, b = folder.lookup(self.images[0]), loaded.lookup(self.images[0])
        a.pop('timings_ms'); b.pop('timings_ms')
        self.assertEqual(a, b)
        chart = loaded._charts.resolve(a['song']['song_id'], 'single', 'expert')
        self.assertEqual(chart['max_ex'], 1500)
        self.assertEqual(chart['source_commit'], 'b'*40)
        self.assertEqual(list(self.root.glob('portable*')), [self.path])
        self.assertFalse((self.root/'cache').exists())

    def test_atomic_replace_updates_metadata_but_loaded_session_retains_version(self):
        before = assets.load(self.cfg)
        operation = CatalogPreparation()
        self.assertEqual(operation.describe(self.cfg)['commit'], 'b'*40)
        selected = deepcopy(self.selection)
        selected['catalog']['commit'] = 'c'*40
        assets._publish(self.path, self.metadata, self.arrays, selected, self.cfg)
        self.assertEqual(before.bundle_info['commit'], 'b'*40)
        self.assertEqual(operation.describe(self.cfg)['commit'], 'c'*40)
        self.assertEqual(assets.load(self.cfg).bundle_info['commit'], 'c'*40)
        self.assertTrue(before.lookup(self.images[0])['accepted'])
        self.assertEqual(list(self.root.glob('*.tmp')), [])

    def test_failed_validation_or_refresh_preserves_file(self):
        original = self.path.read_bytes()
        with self.assertRaises(Exception):
            assets._publish(self.path, self.metadata, b'invalid array data', self.selection, self.cfg)
        self.assertEqual(original, self.path.read_bytes())
        self.assertEqual(list(self.root.glob('*.tmp')), [])
        with patch.object(catalog, 'prepare', side_effect=OSError('offline')):
            with self.assertRaisesRegex(OSError, 'offline'):
                assets.prepare(self.cfg, refresh=True)
        self.assertEqual(original, self.path.read_bytes())
        self.assertTrue(assets.check(self.cfg)['ok'])

    def test_existing_prepare_is_offline_and_refresh_reuses_embedded_gallery(self):
        with patch.object(catalog, 'prepare', side_effect=AssertionError('Download')):
            self.assertTrue(assets.prepare(self.cfg)['ok'])
        data = deepcopy(self.selection['catalog'])
        data['commit'] = 'c'*40
        source = self.root/'sources'
        catalog.dump_json(source/'cache'/data['commit']/'src/songs/ddr_world.json', dict(songs=[]))
        data['failures'] = []
        with patch.object(catalog, 'prepare', return_value=(None, data)), patch.object(
                assets, 'build_index', side_effect=AssertionError('Re-encoding')):
            result = assets.prepare(self.cfg, refresh=True, source_root=source)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['commit'], 'c'*40)
        self.assertFalse((self.root/'cache/galleries').exists())

    def test_legacy_conversion_is_offline_non_destructive_and_repeatable(self):
        root = self.legacy()
        legacy_cfg = validate_config(dict(assets_dir=str(root), event='event'))
        info = assets.describe(legacy_cfg)
        self.assertEqual(info['storage_format'], 'directory')
        self.assertTrue(info['needs_conversion'])
        before = assets.load(legacy_cfg)
        with patch.object(catalog, 'prepare', side_effect=AssertionError('Download')), patch.object(
                assets, 'build_index', side_effect=AssertionError('Encoding')):
            self.assertTrue(assets.prepare(legacy_cfg)['ok'])
            packed = catalog_path(legacy_cfg).read_bytes()
            self.assertTrue(assets.pack(legacy_cfg)['ok'])
            self.assertEqual(packed, catalog_path(legacy_cfg).read_bytes())
        self.assertTrue((root/'active/event-event.json').exists())
        self.assertEqual(assets.describe(legacy_cfg)['storage_format'], 'ddrcatalog')
        self.assertEqual(before.selection['catalog'], assets.load(legacy_cfg).selection['catalog'])
        explicit = {**legacy_cfg, 'catalog_file': str(self.root/'chosen.ddrcatalog')}
        self.assertTrue(assets.pack(explicit)['ok'])
        self.assertTrue(Path(explicit['catalog_file']).exists())

    def test_qualified_legacy_profile_survives_new_default_pack_and_refresh(self):
        original_profile = deepcopy(self.profile)
        new_default = {**self.profile, 'gallery_fingerprint': 'new-default'}
        self.legacy()
        legacy_cfg = validate_config(dict(assets_dir=str(self.root/'cache'), event='event'))
        with patch.object(assets, 'profile', return_value=new_default), patch.object(
                assets, 'legacy_profile', return_value=original_profile):
            self.assertEqual(assets.load(self.cfg).encoder.fingerprint, 'color-gradient-v1')
            self.assertEqual(assets.check(self.cfg)['gallery'], original_profile['gallery_fingerprint'])
            self.assertEqual(assets.describe(self.cfg)['gallery'], original_profile['gallery_fingerprint'])
            self.assertTrue(assets.pack(legacy_cfg)['ok'])
            with CatalogArchive(catalog_path(legacy_cfg), original_profile) as archive:
                self.assertEqual(archive.profile, original_profile)
            # Refresh on a receiver retains the existing qualified gallery and math.
            data = deepcopy(self.selection['catalog'])
            data.update(commit='c'*40, failures=[])
            source = self.root/'sources'
            catalog.dump_json(source/'cache'/data['commit']/'src/songs/ddr_world.json', dict(songs=[]))
            with patch.object(catalog, 'prepare', return_value=(None, data)), patch.object(
                    assets, 'build_index', side_effect=AssertionError('Re-encoding legacy gallery')):
                result = assets.prepare(self.cfg, refresh=True, source_root=source)
            self.assertTrue(result['ok'], result)
            self.assertEqual(result['gallery'], original_profile['gallery_fingerprint'])
            with CatalogArchive(self.path, original_profile) as archive:
                self.assertEqual(archive.profile, original_profile)
            self.write(profile={**original_profile, 'score': .1})
            with self.assertRaisesRegex(ValueError, 'unqualified'):
                assets.load(self.cfg)

    def test_missing_explicit_file_never_falls_back_to_legacy(self):
        self.legacy()
        cfg = {**self.cfg, 'catalog_file': str(self.root/'missing.ddrcatalog')}
        self.assertFalse(assets.check(cfg)['ok'])
        self.assertFalse(assets.describe(cfg)['available'])

    def test_selection_mismatch_and_profile_drift_fail_closed(self):
        for change in (dict(mode='full'), dict(event='other')):
            cfg = {**self.cfg, **change}
            self.assertFalse(assets.check(cfg)['ok'])
            self.assertFalse(assets.describe(cfg)['available'])
        for change in (dict(score=.1), dict(gallery_fingerprint='unqualified')):
            self.write(profile={**self.profile, **change})
            with self.assertRaisesRegex(ValueError, 'unqualified'):
                assets.load(self.cfg)
        selected = {**self.selection, 'gallery_fingerprint': 'wrong'}
        self.write(selection=selected)
        with self.assertRaisesRegex(ValueError, 'different artwork'):
            assets.load(self.cfg)

    def test_tampered_payloads_missing_extra_duplicate_and_future_format(self):
        mutations = [lambda p: p.update({'selection.json': b'{}'}),
                     lambda p: p.pop('gallery/vectors.npz'),
                     lambda p: p.update({'../outside.txt': b'bad'}),
                     lambda p: p.update({'manifest.json': json_bytes(dict(format='ddrcv.catalog',version=99))})]
        for mutate in mutations:
            self.write(); self.rewrite(mutate)
            self.assertFalse(assets.check(self.cfg)['ok'])
        self.write()
        with zipfile.ZipFile(self.path, 'a') as archive:
            with self.assertWarns(UserWarning):
                archive.writestr('selection.json', b'{}')
        self.assertFalse(assets.check(self.cfg)['ok'])

    def test_array_bounds_and_semantic_fingerprint_checked_before_use(self):
        for vectors in (np.zeros((3, 2881), np.float32), np.zeros((3, 2880), np.float64),
                        np.zeros((3, 2880), object)):
            stream = BytesIO()
            np.savez_compressed(stream, vectors=vectors, images=np.asarray(self.images))
            self.write(arrays=stream.getvalue())
            with self.assertRaisesRegex(ValueError, 'shape or dtype'):
                assets.load(self.cfg)
        # A valid container/checksum cannot qualify changed matching inputs.
        metadata = json.loads(self.metadata)
        metadata['entries'][0]['songs']['sa:other'] = 'Other'
        self.write(metadata=json_bytes(metadata))
        with self.assertRaisesRegex(ValueError, 'frozen acceptance'):
            assets.load(self.cfg)

    def test_metadata_inspection_does_not_read_arrays(self):
        real_read = CatalogArchive.read
        def read(archive, name):
            if name.startswith('gallery/'):
                raise AssertionError('Array loading during inspection')
            return real_read(archive, name)
        with patch.object(CatalogArchive, 'read', read):
            self.assertTrue(assets.describe(self.cfg)['available'])

    def test_config_file_validation_and_default_selection_paths(self):
        for value in ('folder', '', 123):
            with self.assertRaises(ValueError):
                validate_config(dict(catalog_file=value))
        self.assertEqual(catalog_path(validate_config(dict(mode='full'))).name, 'full-world.ddrcatalog')
        self.assertEqual(catalog_path(validate_config()).name, 'event-dia_del_ritmo_26.ddrcatalog')


if __name__ == '__main__':
    unittest.main()
