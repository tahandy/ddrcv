"""Opt-in readiness for the selected classical lookup and existing OCR runtime."""
from __future__ import annotations


def check(*, provision=False):
    try:
        import cv2
        import numpy as np
        from .features import Encoder
        from .splash import SplashDetector
        SplashDetector()
        from .lookup import correlation
        from ddrcv.ocr.check import check_ocr
        image = np.random.default_rng(219).integers(0, 255, (128,128,3), dtype=np.uint8)
        encoder = Encoder('classical', 128)
        vector = encoder.encode(image)
        if not np.isfinite(vector).all() or correlation(image, image) < .99:
            raise RuntimeError('Classical descriptor/verification smoke test failed')
        ocr = check_ocr(provision=provision)
        if not ocr['ok']:
            raise RuntimeError(ocr['detail'])
        return dict(ok=True, method='classical', cpu_only=True,
                    detail='Classical jacket descriptors and offline RapidOCR are ready; build a catalog/index separately.')
    except Exception as exc:
        return dict(ok=False, detail=f'{exc}. Run setup_desktop.bat -JacketLookup or install .[jacket-lookup].')
