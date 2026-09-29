"""Small, offline WORLD difficulty-label template bank; no digit recognition."""
from __future__ import annotations

from pathlib import Path
import time

import cv2
import numpy as np

from .catalog import dump_json, read_json, sha256
from .images import read_image, write_image

CLASSES = ('beginner', 'basic', 'difficult', 'expert', 'challenge')
PREPROCESS = 'white-next-to-dark-v1'
_DILATION_KERNEL = np.ones((5, 5), np.uint8)
# Manually inspected text-only rectangles in the saved 40-pixel-high ROIs.
# These four songs are template sources, never independent evaluation queries.
SOURCES = {
    'beginner': ('2025-03-19_16-29-40_00', 'p1', (2, 6, 142, 27)),
    'basic': ('2025-03-19_16-29-40_00', 'p2', (88, 8, 86, 24)),
    'difficult': ('2025-03-27_15-43-31_00', 'p1', (2, 6, 122, 27)),
    'expert': ('2025-03-19_16-47-45_02', 'p1', (2, 6, 104, 26)),
    'challenge': ('2025-03-19_16-47-45_00', 'p1', (2, 5, 149, 27)),
}


def text_mask(image, *, color_order='bgr'):
    if color_order not in ('bgr', 'rgb'):
        raise ValueError('color_order must be bgr or rgb')
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3 or image.shape[0] != 40 or not 180 <= image.shape[1] <= 230:
        raise ValueError('Expected a uint8 WORLD difficulty ROI, height 40 and width 180..230')
    # Channel min/max deliberately make RGB and BGR identical. White lettering
    # borders dark outlines; most moving colored/white background fails this test.
    a, b, c = cv2.split(image)
    low = cv2.min(cv2.min(a, b), c)
    high = cv2.max(cv2.max(a, b), c)
    white = (low > 175) & (cv2.subtract(high, low) < 65)
    near_dark = cv2.dilate((high < 100).astype(np.uint8), _DILATION_KERNEL)
    return (white & (near_dark != 0)).astype(np.float32)


class DifficultyTemplates:
    def __init__(self, bank_dir):
        started = time.perf_counter()
        bank_dir = Path(bank_dir)
        self.meta = read_json(bank_dir/'bank.json')
        if self.meta.get('schema') != 1 or self.meta.get('preprocess') != PREPROCESS:
            raise ValueError('Unsupported difficulty template format')
        self.thresholds = self.meta.get('thresholds')
        self.templates = {}
        for entry in self.meta['entries']:
            name = entry['difficulty']
            if name not in CLASSES or name in self.templates or Path(entry['image']).name != entry['image']:
                raise ValueError('Invalid difficulty template entry')
            path = bank_dir/entry['image']
            if sha256(path.read_bytes()) != entry['sha256']:
                raise ValueError('Difficulty template checksum mismatch')
            mask = cv2.cvtColor(read_image(path), cv2.COLOR_BGR2GRAY).astype(np.float32)/255
            if min(mask.shape) < 4 or mask.shape[0] > 40 or mask.shape[1] > 180 or mask.std() < .05:
                raise ValueError('Invalid difficulty template pixels')
            self.templates[name] = mask
        if set(self.templates) != set(CLASSES):
            raise ValueError('All five difficulty templates are required')
        self.cold_seconds = time.perf_counter()-started

    def recognize(self, image, *, color_order='bgr', exclude=()):
        started = time.perf_counter()
        mask = text_mask(image, color_order=color_order)
        candidates = []
        for name, template in self.templates.items():
            if name in exclude:
                continue
            result = cv2.matchTemplate(mask, template, cv2.TM_CCOEFF_NORMED)
            _, score, _, xy = cv2.minMaxLoc(result)
            candidates.append(dict(difficulty=name, score=float(score), position=list(xy)))
        candidates.sort(key=lambda row: -row['score'])
        best = candidates[0] if candidates else None
        margin = best['score']-candidates[1]['score'] if len(candidates) > 1 else 0.0
        reason = 'uncalibrated'
        if mask.sum() < 40:
            reason = 'no_text'
        elif best is None:
            reason = 'no_candidates'
        elif self.thresholds:
            reason = ('low_similarity' if best['score'] < self.thresholds['score'] else
                      'small_margin' if margin < self.thresholds['margin'] else 'matched')
        return dict(accepted=reason == 'matched', difficulty=best['difficulty'] if reason == 'matched' else None,
            reason=reason, candidates=candidates, margin=margin,
            elapsed_ms=(time.perf_counter()-started)*1000)
