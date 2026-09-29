"""Fixed WORLD image geometry and lossless image I/O."""
from pathlib import Path
import cv2
import numpy as np

JACKET_ROI = (425, 105, 429, 429)
DIFFICULTY_ROIS = ((63, 496, 205, 40), (1005, 496, 211, 40))


def crop(frame, roi=JACKET_ROI):
    x, y, w, h = roi
    return np.ascontiguousarray(frame[y:y+h, x:x+w])


def read_image(path):
    image = cv2.imdecode(np.frombuffer(Path(path).read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f'Cannot decode image: {path}')
    return image


def write_image(path, image):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, data = cv2.imencode(path.suffix, image)
    if not ok:
        raise ValueError(f'Cannot encode image: {path}')
    path.write_bytes(data.tobytes())
