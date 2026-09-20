"""Offline readiness and a mandatory real-model setup smoke test."""
import argparse
import json
from pathlib import Path

from ddrcv.ocr import RapidOCRRecognizer, prepare_ddr_crop


def check_ocr(config=None, *, provision=False):
    try:
        import cv2
        options = {**(config or {}), 'allow_download': provision}
        recognizer = RapidOCRRecognizer(**options)
        recognizer.warmup()
        fixtures = Path(__file__).with_name('fixtures')
        images = [cv2.imread(str(fixtures / f'splash_p{player}.png')) for player in (1, 2)]
        if any(image is None for image in images):
            raise RuntimeError('Missing packaged splash crops for OCR readiness test')
        crops = [prepare_ddr_crop(image) for image in images]
        actual = [r.text for r in recognizer.recognize_many(crops)]
        if actual != ['ZERO.', 'PLAYER2']:
            raise RuntimeError(f'Splash OCR smoke test failed: {actual!r}')
        return dict(name='RapidOCR model and inference', ok=True, detail='Offline splash recognition: ZERO. / PLAYER2')
    except Exception as error:
        return dict(name='RapidOCR model and inference', ok=False,
                    detail=f'{error}. Run setup_desktop.bat or setup_workbench.bat.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provision', action='store_true', help='Allow first-time model download into the default cache')
    args = parser.parse_args()
    result = check_ocr(provision=args.provision)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['ok'] else 1)


if __name__ == '__main__':
    main()
