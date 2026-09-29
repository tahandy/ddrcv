"""Behavior contracts for reusable state and equivalent preprocessing."""
from copy import deepcopy
from itertools import product
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from experiments.jacket_lookup.catalog import ChartIndex, dump_json, resolve_chart, sha256
from experiments.jacket_lookup.difficulty import text_mask
from experiments.jacket_lookup.features import Encoder, build_index, classical, resize
from experiments.jacket_lookup.lookup import Lookup, correlation, lookup_splash


def reference_mask(image):
    low,high = image.min(axis=2),image.max(axis=2)
    white = (low>175)&(high.astype(np.int16)-low<65)
    near_dark = cv2.dilate((high<100).astype(np.uint8),np.ones((5,5),np.uint8))
    return (white&(near_dark!=0)).astype(np.float32)


class EquivalentPreprocessingTests(unittest.TestCase):
    def test_mask_matches_reference_at_boundaries_and_strided_inputs(self):
        rng = np.random.default_rng(472)
        palette = np.array(list(product((0,99,100,175,176,239,240,255),repeat=3)),np.uint8)
        for width in (180,205,211,230):
            for _ in range(8):
                image = palette[rng.integers(len(palette),size=(40,width))]
                for query in (image,image[:,::-1],image[...,::-1]):
                    np.testing.assert_array_equal(text_mask(query),reference_mask(query))

    def test_same_size_encoder_skips_copy_without_changing_features(self):
        rng = np.random.default_rng(591)
        for size in (128,150):
            encoder = Encoder('classical',size)
            for side in (size,429):
                image = rng.integers(0,256,(side,side,3),np.uint8)
                before = image.copy()
                expected = classical(resize(image,size))
                np.testing.assert_array_equal(encoder.encode(image),expected)
                np.testing.assert_array_equal(image,before)


class ChartIndexTests(unittest.TestCase):
    def test_index_matches_scan_for_duplicates_versions_missing_values_and_styles(self):
        def chart(level,ex=500,source='world',style='single'):
            return dict(style=style,difficulty='expert',level=level,max_ex=ex,max_ex_source=source)
        records = [dict(dataset='world',song_id=name,charts=charts) for name,charts in (
            ('unique',[chart(14)]),('duplicate',[chart(14),chart(14)]),
            ('levels',[chart(14),chart(15)]),('scores',[chart(14),chart(14,600)]),
            ('sources',[chart(14),chart(14,source='event')]),('missing',[chart(14,None,None)]),
            ('styles',[chart(14),chart(15,style='double')]),('null_level',[chart(None)]))]
        records.append(dict(dataset='historical',song_id='unique',charts=[chart(15,123)]))
        for mode,dataset in product(('full','event'),('world','historical','empty')):
            catalog=dict(records=records,metadata_dataset=dataset,mode=mode,commit='pinned')
            index=ChartIndex(catalog)
            for song,style,difficulty,level in product(
                [r['song_id'] for r in records]+['absent'],('single','double'),('expert','basic'),(None,14,15,99)):
                self.assertEqual(index.resolve(song,style,difficulty,level),resolve_chart(catalog,song,style,difficulty,level))

    def test_returned_dictionary_cannot_corrupt_cache(self):
        catalog=dict(mode='event',metadata_dataset='world',commit='pinned',records=[])
        index=ChartIndex(catalog)
        value=index.resolve('missing','single','expert');value['max_ex']=100
        self.assertIsNone(index.resolve('missing','single','expert')['max_ex'])


class LookupCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);rng=np.random.default_rng(718)
        self.images=[rng.integers(0,256,(128,128,3),np.uint8) for _ in range(2)]
        records,assets=[],{}
        for i,image in enumerate(self.images):
            path=root/f'{i}.png';data=cv2.imencode('.png',image)[1].tobytes();path.write_bytes(data)
            jacket=f'ddr_world/{i}.png'
            assets[jacket]=dict(path=path.name,sha256=sha256(data))
            records.append(dict(song_id=str(i),name=f'Song {i}',dataset='world',
                charts=[dict(style='single',difficulty='expert',level=14,max_ex=1500,
                             max_ex_source='world',jacket=jacket)]))
        dump_json(root/'catalog.json',dict(mode='full',metadata_dataset='world',commit='pinned',records=records,assets=assets))
        build_index(root/'catalog.json',root/'index')
        self.lookup=Lookup(root/'index',thresholds=dict(score=.9,margin=.05))
        self.frame=np.zeros((720,1280,3),np.uint8)
        self.result=dict(accepted=True,song=dict(song_id='0'),timings_ms={})
        self.detector=Mock()
        self.detector.match.return_value=(True,dict(p1_present=True,p2_present=False))

    def fake_jacket(self):
        return patch.object(self.lookup,'lookup',side_effect=lambda *a,**k:deepcopy(self.result))

    def test_reference_grays_are_lazy_reused_and_correlation_is_unchanged(self):
        self.assertTrue(all(im is None for im in self.lookup._reference_grays))
        first=self.lookup.lookup(self.images[0])
        identities=[id(im) for im in self.lookup._reference_grays]
        second=self.lookup.lookup(self.images[0])
        self.assertEqual(identities,[id(im) for im in self.lookup._reference_grays])
        self.assertEqual(first['candidates'],second['candidates'])
        for candidate in first['candidates']:
            expected=correlation(self.images[0],self.lookup.images[candidate['index']])
            self.assertAlmostEqual(candidate['score'],expected,places=6)
        self.assertFalse(self.lookup.lookup(self.images[0],exclude_song_ids=('0',))['accepted'])

    def test_detector_and_default_recognizer_reused_explicit_override_respected(self):
        default=Mock();default.recognize_many.return_value=[SimpleNamespace(text='Expert 14',confidence=.99)]
        override=Mock();override.recognize_many.return_value=[SimpleNamespace(text='Expert 14',confidence=.98)]
        with self.fake_jacket(),patch('experiments.jacket_lookup.splash.SplashDetector',return_value=self.detector) as detector_constructor,patch('ddrcv.ocr.rapid.RapidOCRRecognizer',return_value=default) as ocr_constructor:
            for _ in range(2):
                self.assertEqual(lookup_splash(self.lookup,self.frame)['players']['p1']['max_ex'],1500)
            lookup_splash(self.lookup,self.frame,recognizer=override)
            lookup_splash(self.lookup,self.frame)
        detector_constructor.assert_called_once_with()
        ocr_constructor.assert_called_once_with(allow_download=False,num_threads=1)
        self.assertEqual(default.recognize_many.call_count,3)
        override.recognize_many.assert_called_once()

    def test_template_and_non_splash_paths_never_request_default_ocr(self):
        reader=Mock();reader.recognize.return_value=dict(accepted=True,difficulty='expert')
        with self.fake_jacket(),patch('experiments.jacket_lookup.splash.SplashDetector',return_value=self.detector),patch.object(self.lookup,'_get_recognizer',side_effect=AssertionError('Unexpected OCR')):
            lookup_splash(self.lookup,self.frame,difficulty_reader=reader)
            self.detector.match.return_value=(False,None)
            result=lookup_splash(self.lookup,self.frame)
        self.assertEqual(result['reason'],'not_splash')
        self.assertIsNone(self.lookup._default_recognizer)


if __name__=='__main__':
    unittest.main()
