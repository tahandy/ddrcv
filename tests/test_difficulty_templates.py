"""Template rejection, optional imports, and digit-free chart joins."""
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from experiments.jacket_lookup.catalog import ChartIndex, dump_json, normalize_catalog, resolve_chart, sha256
from experiments.jacket_lookup.corpus import DIFFICULTY_ROIS, write_image
from experiments.jacket_lookup.difficulty import CLASSES, PREPROCESS, DifficultyTemplates, text_mask
from experiments.jacket_lookup.lookup import lookup_splash


def fixture_catalog():
    chart = dict(style='single', diffClass='expert', lvl=14, maxScore=1500)
    song = dict(name='Song', artist='Artist', jacket='ddr_world/a.png', charts=[chart])
    return normalize_catalog({'ddr_world':dict(meta={}, defaults={}, songs=[song])})


class DifficultyTemplateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        entries = []
        self.images = {}
        for name in CLASSES:
            image = np.full((40, 205, 3), (30, 170, 40), np.uint8)
            cv2.putText(image, name, (3, 28), cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 0, 0), 5)
            cv2.putText(image, name, (3, 28), cv2.FONT_HERSHEY_SIMPLEX, .6, (255, 255, 255), 2)
            self.images[name] = image
            width = cv2.getTextSize(name, cv2.FONT_HERSHEY_SIMPLEX, .6, 2)[0][0]+6
            path = self.root/f'{name}.png'
            write_image(path, (text_mask(image)[8:32,:width]*255).astype(np.uint8))
            entries.append(dict(difficulty=name, image=path.name, sha256=sha256(path.read_bytes())))
        self.bank = dict(schema=1, preprocess=PREPROCESS, entries=entries, thresholds=dict(score=.8, margin=.08))
        self.save()

    def save(self):
        dump_json(self.root/'bank.json', self.bank)

    def test_offline_labels_offsets_and_color_order(self):
        reader = DifficultyTemplates(self.root)
        for name, image in self.images.items():
            shifted = cv2.warpAffine(image, np.float32([[1,0,8],[0,1,2]]), (205,40))
            for query in (image, shifted):
                result = reader.recognize(query)
                self.assertTrue(result['accepted'], result)
                self.assertEqual(result['difficulty'], name)
                rgb = reader.recognize(query[...,::-1], color_order='rgb')
                self.assertEqual(rgb['difficulty'], name)
                self.assertEqual(rgb['candidates'][0]['score'], result['candidates'][0]['score'])

    def test_blank_and_missing_correct_label_abstain(self):
        reader = DifficultyTemplates(self.root)
        for color in (0, 255):
            self.assertFalse(reader.recognize(np.full((40,205,3),color,np.uint8))['accepted'])
        self.assertFalse(reader.recognize(self.images['expert'], exclude=('expert',))['accepted'])

    def test_duplicate_artwork_is_ambiguous_and_uncalibrated_abstains(self):
        entry = next(e for e in self.bank['entries'] if e['difficulty']=='basic')
        other = next(e for e in self.bank['entries'] if e['difficulty']=='expert')
        entry.update(image=other['image'], sha256=other['sha256'])
        self.save()
        result = DifficultyTemplates(self.root).recognize(self.images['expert'])
        self.assertFalse(result['accepted'])
        self.assertEqual(result['reason'], 'small_margin')
        self.bank['thresholds'] = None
        self.save()
        self.assertEqual(DifficultyTemplates(self.root).recognize(self.images['expert'])['reason'], 'uncalibrated')

    def test_checksum_and_geometry_validation(self):
        reader = DifficultyTemplates(self.root)
        for image in (np.zeros((20,205,3),np.uint8), np.zeros((40,205,3),np.float32)):
            with self.assertRaises(ValueError):
                reader.recognize(image)
        with self.assertRaises(ValueError):
            reader.recognize(self.images['basic'],color_order='xyz')
        path = self.root/'expert.png'
        path.write_bytes(path.read_bytes()+b'changed')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            DifficultyTemplates(self.root)

    def test_full_splash_template_path_uses_metadata_level_and_no_ocr(self):
        catalog = fixture_catalog()
        lookup = Mock(catalog=catalog)
        lookup._charts = ChartIndex(catalog)
        from experiments.jacket_lookup.splash import SplashDetector
        lookup._get_splash_detector.side_effect = SplashDetector
        lookup.lookup.return_value = dict(accepted=True, song=dict(song_id=catalog['records'][0]['song_id']), timings_ms={})
        frame = np.zeros((720,1280,3),np.uint8)
        x,y,w,h = DIFFICULTY_ROIS[0]
        frame[y:y+h,x:x+w] = self.images['expert']
        ocr = Mock()
        with patch('experiments.jacket_lookup.splash.SplashDetector.match', return_value=(True,dict(p1_present=True,p2_present=False))):
            result = lookup_splash(lookup, frame, recognizer=ocr, difficulty_reader=DifficultyTemplates(self.root))
        actual = result['players']['p1']
        self.assertEqual(actual['difficulty'],'expert')
        self.assertEqual(actual['max_ex'],1500)
        self.assertEqual(actual['metadata_level'],14)
        self.assertNotIn('level',actual)
        self.assertNotIn('ocr',result['timings_ms'])
        ocr.recognize_many.assert_not_called()

    def test_template_import_has_no_ocr_or_neural_dependencies(self):
        result = subprocess.run([sys.executable,'-B','-c',
            "import sys; from experiments.jacket_lookup.difficulty import DifficultyTemplates; "
            "assert not set(('rapidocr','onnxruntime','torch','timm')).intersection(sys.modules)"],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)


class ChartWithoutLevelTests(unittest.TestCase):
    def test_unique_chart_resolves_without_observed_digits(self):
        catalog = fixture_catalog()
        sid = catalog['records'][0]['song_id']
        result = resolve_chart(catalog,sid,'single','expert')
        self.assertEqual(result['max_ex'],1500)
        self.assertEqual(result['metadata_level'],14)
        self.assertIsNone(resolve_chart(catalog,sid,'double','expert')['max_ex'])

    def test_conflicting_levels_abstain_even_with_equal_ex(self):
        catalog = fixture_catalog()
        record = catalog['records'][0]
        chart = deepcopy(record['charts'][0]); chart['level'] = 15
        record['charts'].append(chart)
        self.assertEqual(resolve_chart(catalog,record['song_id'],'single','expert')['status'],'ambiguous_chart')
        self.assertEqual(resolve_chart(catalog,record['song_id'],'single','expert',14)['max_ex'],1500)

    def test_historical_records_do_not_override_selected_dataset(self):
        catalog = fixture_catalog()
        record = deepcopy(catalog['records'][0]); record['dataset'] = 'old'
        record['charts'][0].update(level=15,max_ex=123)
        catalog['records'].append(record)
        self.assertEqual(resolve_chart(catalog,record['song_id'],'single','expert')['max_ex'],1500)
        catalog['mode'] = 'event'; catalog['metadata_dataset'] = 'absent-event'
        self.assertEqual(resolve_chart(catalog,record['song_id'],'single','expert')['status'],'chart_outside_pool')


if __name__ == '__main__':
    unittest.main()
