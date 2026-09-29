"""Offline contract tests for the isolated jacket experiment."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import cv2
import numpy as np

from experiments.jacket_lookup.catalog import (
    dump_json, effective_jacket, normalize_catalog, parse_event, resolve_chart, safe_jacket, sha256)
from experiments.jacket_lookup.features import build_index
from experiments.jacket_lookup.lookup import Lookup, parse_difficulty


def song(name='Song', artist='Artist', score=123, level=14, **kwargs):
    chart = dict(style='single', diffClass='expert', lvl=level)
    if score is not None:
        chart['maxScore'] = score
    return dict(name=name, artist=artist, jacket='ddr_world/a.png', charts=[chart], **kwargs)


def source(*songs):
    return dict(meta={}, defaults={'lowerLvlBound': 16}, songs=list(songs))


class CatalogTests(unittest.TestCase):
    def test_url_and_path_validation(self):
        self.assertEqual(parse_event('https://ddr.tools/#game-dia_del_ritmo_26'), 'dia_del_ritmo_26')
        for bad in ('../file', 'https://example.com/#game-a', 'https://ddr.tools/#nope'):
            with self.assertRaises(ValueError):
                parse_event(bad)
        for bad in ('../a.png', '/a.png', 'C:/a.png', 'ddr_world\\a.png'):
            with self.assertRaises(ValueError):
                safe_jacket(bad)

    def test_chart_override_and_event_defaults_do_not_filter(self):
        s = song()
        s['charts'][0]['jacket'] = 'ddr_world/override.png'
        cat = normalize_catalog({'event': source(s)}, 'event')
        self.assertEqual(cat['records'][0]['charts'][0]['jacket'], 'ddr_world/override.png')
        self.assertEqual(len(cat['records']), 1)  # level 14 below the UI's default 16
        self.assertEqual(effective_jacket(s, {}), 'ddr_world/a.png')

    def test_exact_enrichment_and_provenance(self):
        event, world = song(score=None), song(score=1500)
        cat = normalize_catalog({'event': source(event), 'ddr_world': source(world)}, 'event')
        r = cat['records'][0]
        c = r['charts'][0]
        self.assertEqual(c['max_ex'], 1500)
        self.assertEqual(c['max_ex_source'], 'ddr_world')
        self.assertIsNone(c['original_max_ex'])
        self.assertNotIn('maxScore', event['charts'][0])
        self.assertEqual(resolve_chart(cat, r['song_id'], 'single', 'expert', 14)['max_ex'], 1500)
        self.assertEqual(resolve_chart(cat, r['song_id'], 'double', 'expert', 14)['status'], 'chart_outside_pool')

    def test_enrichment_abstains_on_level_identity_or_duplicate(self):
        for world in [source(song(level=15)), source(song(artist='Different')),
                      source(song(), song()), source(song(saHash='other'))]:
            event = song(score=None, saHash='known')
            cat = normalize_catalog({'event': source(event), 'ddr_world': world}, 'event')
            self.assertIsNone(cat['records'][0]['charts'][0]['max_ex'])

    def test_existing_value_is_not_overwritten(self):
        cat = normalize_catalog({'event': source(song(score=900)),
                                 'ddr_world': source(song(score=1200))}, 'event')
        self.assertEqual(cat['records'][0]['charts'][0]['max_ex'], 900)

    def test_other_games_with_ddr_difficulty_names_are_excluded(self):
        itg = song()
        itg['jacket'] = 'itg/pack/a.png'
        cat = normalize_catalog({'itg': source(itg), 'ddr_world': source(song())})
        self.assertEqual([s['dataset'] for s in cat['records']], ['ddr_world'])

    def test_conflicting_chart_versions_are_not_resolved(self):
        cat = normalize_catalog({'ddr_world': source(song(score=100), song(score=200))})
        sid = cat['records'][0]['song_id']
        self.assertEqual(resolve_chart(cat, sid, 'single', 'expert', 14)['status'], 'ambiguous_chart')


class LookupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        rng = np.random.default_rng(343)
        self.images = [rng.integers(0, 255, (128, 128, 3), dtype=np.uint8) for _ in range(3)]
        songs, assets = [], {}
        for i, image in enumerate(self.images):
            path = f'ddr_world/{i}.png'
            ok, data = cv2.imencode('.png', image)
            (self.root / f'{i}.png').write_bytes(data.tobytes())
            s = song(name=f'Song{i}', score=100+i)
            s['jacket'] = path
            songs.append(s)
            assets[path] = dict(path=f'{i}.png', sha256=sha256(data.tobytes()))
        self.catalog = normalize_catalog({'ddr_world': source(*songs)})
        self.catalog['assets'] = assets

    def make_index(self):
        dump_json(self.root/'catalog.json', self.catalog)
        build_index(self.root/'catalog.json', self.root/'index')
        return Lookup(self.root/'index', thresholds=dict(score=.9, margin=.05))

    def test_offline_reload_color_order_and_unknown_rejection(self):
        lookup = self.make_index()
        bgr = lookup.lookup(self.images[0])
        rgb = lookup.lookup(self.images[0][..., ::-1], color_order='rgb')
        self.assertTrue(bgr['accepted'])
        self.assertEqual(bgr['song']['song_id'], rgb['song']['song_id'])
        self.assertAlmostEqual(bgr['song']['score'], rgb['song']['score'])
        self.assertFalse(lookup.lookup(np.full((128,128,3), 255, np.uint8))['accepted'])
        self.assertFalse(lookup.lookup(self.images[0], exclude_song_ids=[bgr['song']['song_id']])['accepted'])

    def test_shared_artwork_rejects_even_with_high_similarity(self):
        duplicate = deepcopy(self.catalog['records'][0])
        duplicate.update(song_id='different-identity', name='Different song')
        self.catalog['records'].append(duplicate)
        result = self.make_index().lookup(self.images[0])
        self.assertFalse(result['accepted'])
        self.assertEqual(result['reason'], 'ambiguous_artwork')

    def test_uncalibrated_and_corrupt_index_fail_closed(self):
        self.make_index()
        lookup = Lookup(self.root/'index')
        self.assertEqual(lookup.lookup(self.images[0])['reason'], 'uncalibrated')
        with (self.root/'index/vectors.npz').open('ab') as stream:
            stream.write(b'corruption')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            Lookup(self.root/'index')

    def test_threshold_profile_cannot_be_used_with_another_index(self):
        self.make_index()
        with self.assertRaisesRegex(ValueError, 'another index'):
            Lookup(self.root/'index', thresholds=dict(score=.9, margin=.05, index_sha256='wrong'))

    def test_invalid_pixels_are_rejected(self):
        lookup = self.make_index()
        for image in (np.zeros((128,128,3), np.float32), np.zeros((0,128,3), np.uint8)):
            with self.assertRaises(ValueError):
                lookup.lookup(image)

    def test_non_splash_does_not_initialize_ocr(self):
        from experiments.jacket_lookup.lookup import lookup_splash
        from unittest.mock import Mock
        ocr = Mock()
        result = lookup_splash(self.make_index(), np.zeros((720,1280,3), np.uint8), recognizer=ocr)
        self.assertEqual(result['reason'], 'not_splash')
        ocr.recognize_many.assert_not_called()

    def test_splash_templates_need_no_legacy_plotting_dependencies(self):
        result = subprocess.run([sys.executable, '-B', '-c',
            "import sys; from experiments.jacket_lookup.splash import SplashDetector; SplashDetector(); "
            "assert not set(('imagehash','matplotlib','torch','timm')).intersection(sys.modules)"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_difficulty_parser_does_not_guess(self):
        self.assertEqual(parse_difficulty('Expert 15', .99), dict(difficulty='expert', level=15))
        for text, score in [('Expert I5', .99), ('Basic', .99), ('Expert 15', .4), ('Expert 99', .99)]:
            self.assertIsNone(parse_difficulty(text, score))

    def test_classical_import_does_not_load_research_dependencies(self):
        result = subprocess.run([sys.executable, '-B', '-c',
            "import sys; from experiments.jacket_lookup.lookup import Lookup; "
            "assert not set(('torch','timm','onnxruntime','rapidocr')).intersection(sys.modules)"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
