"""Exact preprocessing and cache invalidation contracts for gameplay glyphs."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from ddrcv.score.glyph_detector import GlyphDetector, preprocess_image


def reference_preprocess(image):
    result = (255 * np.prod(image / 255, axis=-1)).astype(np.uint8)
    result[result > 128] = 255
    result[result <= 128] = 1
    return result


class PreprocessingTests(unittest.TestCase):
    def test_every_uint8_rgb_color_matches_original(self):
        colors = np.zeros((256, 256, 3), np.uint8)
        colors[..., 1] = np.arange(256, dtype=np.uint8)[:, None]
        colors[..., 2] = np.arange(256, dtype=np.uint8)[None, :]
        for red in range(256):
            colors[..., 0] = red
            np.testing.assert_array_equal(preprocess_image(colors), reference_preprocess(colors))

    def test_strided_read_only_empty_and_legacy_input_formats(self):
        rng = np.random.default_rng(4)
        rgb = rng.integers(0, 256, (45, 240, 3), dtype=np.uint8)
        original = rgb.copy()
        rgb.flags.writeable = False
        for image in (rgb, rgb[::-1, ::2, ::-1], rgb[:0], rgb.astype(np.float32),
                      rgb.astype(np.float64), rgb.astype(np.uint16), rgb[..., :2],
                      np.concatenate((rgb, rgb[..., :1]), axis=-1)):
            with self.subTest(shape=image.shape, dtype=image.dtype):
                result = preprocess_image(image)
                np.testing.assert_array_equal(result, reference_preprocess(image))
                self.assertEqual(result.dtype, np.uint8)
        np.testing.assert_array_equal(rgb, original)


class GlyphCacheTests(unittest.TestCase):
    def setUp(self):
        self.detector = GlyphDetector({'1': (np.full((2, 2), 255, np.uint8),
                                            np.full((2, 2), 255, np.uint8))}, dilation=0)
        self.image = np.zeros((5, 8, 3), np.uint8)
        self.image[1:3, 2:4] = 255

    def fresh_result(self):
        fresh = GlyphDetector(deepcopy(self.detector.glyphs), threshold=self.detector.threshold, dilation=0)
        fresh.optimal_scale = self.detector.optimal_scale
        return fresh.detect_glyphs(self.image)

    def test_identical_preprocessed_input_skips_matching_and_owns_results(self):
        with patch.object(self.detector, '_match_glyph', wraps=self.detector._match_glyph) as match:
            first = self.detector.detect_glyphs(self.image)
            expected = deepcopy(first)
            self.assertTrue(first)
            first[0]['glyph_class'] = 'corrupted'
            first.clear()
            # Different RGB values can still produce the exact same matcher input.
            self.image[0, 0] = 2
            second = self.detector.detect_glyphs(self.image)
            self.assertEqual(second, expected)
            second[0]['location'] = (999, 999)
            self.assertEqual(self.detector.detect_glyphs(self.image), expected)
            self.assertEqual(match.call_count, 1)

    def test_changed_crop_misses_and_cache_keeps_only_last_input(self):
        original = self.image.copy()
        with patch.object(self.detector, '_match_glyph', wraps=self.detector._match_glyph) as match:
            self.detector.detect_glyphs(self.image)
            self.image[1:3, 2:4] = 0
            self.assertEqual(self.detector.detect_glyphs(self.image), [])
            self.assertEqual(self.detector.detect_glyphs(original), self.fresh_result_for(original))
            self.assertEqual(match.call_count, 3)

    def fresh_result_for(self, image):
        fresh = GlyphDetector(deepcopy(self.detector.glyphs), dilation=0)
        return fresh.detect_glyphs(image)

    def test_empty_detections_are_cached(self):
        self.image[:] = 0
        with patch.object(self.detector, '_match_glyph', wraps=self.detector._match_glyph) as match:
            self.assertEqual(self.detector.detect_glyphs(self.image), [])
            self.assertEqual(self.detector.detect_glyphs(self.image), [])
            self.assertEqual(match.call_count, 1)

    def test_matching_settings_and_in_place_template_changes_invalidate(self):
        changes = (
            lambda d: setattr(d, 'threshold', 1.01),
            lambda d: setattr(d, 'optimal_scale', 2),
            lambda d: d.glyphs['1'][0].__setitem__((0, 0), 1),
            lambda d: d.glyphs['1'][1].__setitem__((0, 0), 0),
            lambda d: d.glyphs.update({'2': tuple(a.copy() for a in d.glyphs['1'])}),
            lambda d: d.glyphs.update({'1': tuple(a[:, :1].copy() for a in d.glyphs['1'])}),
        )
        for change in changes:
            self.setUp()
            self.detector.detect_glyphs(self.image)
            change(self.detector)
            with patch.object(self.detector, '_match_glyph', wraps=self.detector._match_glyph) as match:
                self.assertEqual(self.detector.detect_glyphs(self.image), self.fresh_result())
                self.assertGreater(match.call_count, 0)

    def test_glyph_order_is_part_of_cache_key(self):
        self.detector.glyphs['2'] = tuple(a.copy() for a in self.detector.glyphs['1'])
        self.detector.detect_glyphs(self.image)
        self.detector.glyphs = dict(reversed(list(self.detector.glyphs.items())))
        with patch.object(self.detector, '_match_glyph', wraps=self.detector._match_glyph) as match:
            self.assertEqual(self.detector.detect_glyphs(self.image), self.fresh_result())
            self.assertEqual(match.call_count, 2)

    def test_invalid_dtype_or_mask_shape_cannot_return_stale_success(self):
        for bad_dtype in (True, False):
            self.setUp()
            self.detector.detect_glyphs(self.image)
            glyph, mask = self.detector.glyphs['1']
            self.detector.glyphs['1'] = (glyph.astype(np.float32), mask) if bad_dtype else (glyph, mask.ravel())
            with self.assertRaises(cv2.error):
                self.detector.detect_glyphs(self.image)

    def test_detector_instances_have_independent_caches(self):
        other = GlyphDetector(deepcopy(self.detector.glyphs), threshold=1.01, dilation=0)
        self.assertTrue(self.detector.detect_glyphs(self.image))
        self.assertEqual(other.detect_glyphs(self.image), [])


if __name__ == '__main__':
    unittest.main()
