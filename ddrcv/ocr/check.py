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
        image = cv2.imread(str(Path(__file__).resolve().parents[2] / 'state_images/song_splash_updated.png'))
        if image is None:
            raise RuntimeError('Missing tracked splash fixture for OCR readiness test')
        crops = [prepare_ddr_crop(image[463:497, 62:273]), prepare_ddr_crop(image[463:497, 1006:1218])]
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
