"""Persistent, CPU-only text-line recognition. See the adjacent README.md.

Importing this module and constructing a recognizer do not import RapidOCR,
load models, create cache directories, or access the network.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Iterable, Literal

if TYPE_CHECKING:
    import numpy as np

ColorOrder = Literal['bgr', 'rgb']
RAPIDOCR_VERSION = '3.9.2'
MODEL_FILENAME = 'en_PP-OCRv5_rec_mobile.onnx'
MODEL_SHA256 = 'c3461add59bb4323ecba96a492ab75e06dda42467c9e3d0c18db5d1d21924be8'
_model_load_lock = Lock()
_default_lock = Lock()
_default_recognizer = None


@dataclass(frozen=True)
class OCRResult:
    """One text line; confidence is a model score, not a calibrated probability."""

    text: str
    confidence: float


def _default_cache_dir() -> Path:
    if os.name == 'nt':
        base = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local'))
    else:
        base = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache'))
    return base / 'ddrcv' / 'ocr'


def _verify_model(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f'RapidOCR recognition model not found: {path}')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    if digest.hexdigest() != MODEL_SHA256:
        raise ValueError(f'Expected the pinned English PP-OCRv5 recognition model at {path}; SHA-256 mismatch')


def _build_engine(model_dir: Path, model_path: Path | None, allow_download: bool,
                  num_threads: int, batch_size: int):
    """The only place that depends on RapidOCR's version-specific internals."""
    from importlib.metadata import PackageNotFoundError, version

    local_path = model_path or model_dir / MODEL_FILENAME
    if model_path is not None or local_path.exists() or not allow_download:
        _verify_model(local_path)
    try:
        installed = version('rapidocr')
        if installed != RAPIDOCR_VERSION:
            raise RuntimeError(
                f'Expected rapidocr=={RAPIDOCR_VERSION}, found {installed}; '
                'from the DDRCV repository root, run: python -m pip install -e ".[ocr]"')
        import rapidocr
        import onnxruntime  # noqa: F401 - give a useful optional-dependency error
        from rapidocr import EngineType, LangRec, ModelType, OCRVersion
        from rapidocr.ch_ppocr_rec import TextRecognizer
        from rapidocr.ch_ppocr_rec.typings import TextRecInput
        from rapidocr.utils.parse_parameters import ParseParams
    except (ImportError, PackageNotFoundError) as exc:
        raise ImportError(
            'RapidOCR support requires: python -m pip install -e ".[ocr]" '
            '(run from the DDRCV repository root)') from exc

    cfg = ParseParams.load(Path(rapidocr.__file__).parent / 'config.yaml')
    cfg = ParseParams.update_batch(cfg, {
        'Rec.engine_type': EngineType.ONNXRUNTIME,
        'Rec.lang_type': LangRec.EN,
        'Rec.ocr_version': OCRVersion.PPOCRV5,
        'Rec.model_type': ModelType.MOBILE,
        'Rec.rec_batch_num': batch_size,
        'Rec.rec_img_shape': [3, 48, 320],
        'EngineConfig.onnxruntime.intra_op_num_threads': num_threads,
        'EngineConfig.onnxruntime.inter_op_num_threads': 1,
        'EngineConfig.onnxruntime.use_cuda': False,
        'EngineConfig.onnxruntime.use_dml': False,
        'EngineConfig.onnxruntime.use_cann': False,
        'EngineConfig.onnxruntime.use_coreml': False,
    })
    cfg.Rec.engine_cfg = cfg.EngineConfig.onnxruntime
    cfg.Rec.model_root_dir = str(model_dir)
    cfg.Rec.font_path = None
    # Passing the verified local path bypasses RapidOCR's downloader completely.
    if local_path.is_file():
        cfg.Rec.model_path = str(local_path)
    # Instantiate the recognizer directly: RapidOCR's full pipeline constructor
    # loads detection/orientation models even when their inference is disabled.
    engine = TextRecognizer(cfg.Rec)
    if not local_path.is_file():
        raise RuntimeError(f'RapidOCR did not create the expected model: {local_path}')
    _verify_model(local_path)
    return engine, TextRecInput


def _copy_image(image: np.ndarray, color_order: ColorOrder) -> np.ndarray:
    import numpy as np

    if color_order not in ('bgr', 'rgb'):
        raise ValueError("color_order must be 'bgr' or 'rgb'")
    if not isinstance(image, np.ndarray):
        raise TypeError('Expected a uint8 NumPy image, not a path or encoded bytes')
    if image.dtype != np.uint8:
        raise TypeError('Expected uint8 pixels in the range 0..255')
    if image.ndim not in (2, 3) or min(image.shape[:2]) == 0:
        raise ValueError('Expected a non-empty HxW or HxWx3 image')
    if image.ndim == 2:
        return np.repeat(image[:, :, None], 3, axis=2)
    if image.shape[2] != 3:
        raise ValueError('Expected three color channels; convert alpha images explicitly')
    return np.array(image[:, :, ::-1] if color_order == 'rgb' else image, copy=True, order='C')


class RapidOCRRecognizer:
    """One lazy, persistent recognition model with serialized thread-safe calls.

    Use get_rapidocr() for a process-wide default. Explicit instances have their
    own models and inference locks. Model initialization is serialized across
    all instances in this process to avoid concurrent cache downloads.
    """

    def __init__(self, *, model_dir: str | Path | None = None,
                 model_path: str | Path | None = None, allow_download: bool = True,
                 num_threads: int = 2, batch_size: int = 6):
        if model_dir is not None and model_path is not None:
            raise ValueError('Specify model_dir or model_path, not both')
        for name, value in (('num_threads', num_threads), ('batch_size', batch_size)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f'{name} must be a positive integer')
        if not isinstance(allow_download, bool):
            raise TypeError('allow_download must be a bool')
        self._model_dir = Path(model_dir).expanduser().resolve() if model_dir is not None else _default_cache_dir().resolve()
        self._model_path = Path(model_path).expanduser().resolve() if model_path is not None else None
        self._allow_download = allow_download
        self._num_threads = min(num_threads, os.cpu_count() or 1)
        self._batch_size = batch_size
        self._lock = Lock()
        self._engine = None
        self._input_type = None

    def _ensure_loaded(self):
        # Called only while self._lock is held. Assignment happens after success,
        # so a failed download/load does not poison the persistent instance.
        if self._engine is None:
            with _model_load_lock:
                engine, input_type = _build_engine(self._model_dir, self._model_path,
                    self._allow_download, self._num_threads, self._batch_size)
            self._engine, self._input_type = engine, input_type

    def warmup(self) -> None:
        """Load/verify the model ahead of the first request (idempotent)."""
        with self._lock:
            self._ensure_loaded()

    def recognize(self, image: np.ndarray, *, color_order: ColorOrder = 'bgr') -> OCRResult:
        """Recognize one already-cropped text line; no detection or score parsing."""
        return self.recognize_many([image], color_order=color_order)[0]

    def recognize_many(self, images: Iterable[np.ndarray], *,
                       color_order: ColorOrder = 'bgr') -> list[OCRResult]:
        """Recognize crops in input order, using the model's internal batching.

        Input pixels are copied before queuing for inference and are never
        modified. Callers must not mutate a source buffer during that copy.
        An empty batch returns [] without loading a model.
        """
        import numpy as np

        if color_order not in ('bgr', 'rgb'):
            raise ValueError("color_order must be 'bgr' or 'rgb'")
        if isinstance(images, np.ndarray):
            raise TypeError('Pass a sequence of images to recognize_many, or use recognize for one image')
        batch = [_copy_image(image, color_order) for image in images]
        if not batch:
            return []
        with self._lock:
            self._ensure_loaded()
            output = self._engine(self._input_type(img=batch, return_word_box=False))
            if output is None or output.txts is None:
                return [OCRResult('', 0.0) for _ in batch]
            if len(output.txts) != len(batch) or len(output.scores) != len(batch):
                raise RuntimeError('RapidOCR returned a different number of results than input crops')
            results = []
            for text, score in zip(output.txts, output.scores):
                confidence = float(score)
                if not isinstance(text, str) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
                    raise RuntimeError('RapidOCR returned invalid text or confidence')
                text = text.strip()
                results.append(OCRResult(text, confidence if text else 0.0))
            return results


def get_rapidocr() -> RapidOCRRecognizer:
    """Return the same lazy default recognizer to every caller in this process."""
    global _default_recognizer
    with _default_lock:
        if _default_recognizer is None:
            _default_recognizer = RapidOCRRecognizer()
        return _default_recognizer


def prepare_ddr_crop(image: np.ndarray, *, color_order: ColorOrder = 'bgr') -> np.ndarray:
    """Optional original-color preprocessing used by the DDR OCR pilot.

    Find white foreground to trim excess band width, retain original pixels,
    pad, and enlarge 2x. Returns BGR. This is specialized for DDR's white text;
    do not apply it indiscriminately to other kinds of text.
    """
    import cv2
    import numpy as np

    chip = _copy_image(image, color_order)
    lo, hi = chip.min(axis=2), chip.max(axis=2)
    mask = np.uint8((lo > 165) & ((hi.astype(float) - lo) < 65)) * 255
    _, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    for label, (x, y, width, height, area) in enumerate(stats[1:], 1):
        if area > 8 and (x == 0 or y == 0 or x + width == mask.shape[1] or y + height == mask.shape[0]):
            mask[labels == label] = 0
    ys, xs = np.where(mask > 0)
    if len(xs):
        x0, x1 = max(0, int(xs.min()) - 2), min(chip.shape[1], int(xs.max()) + 3)
        y0, y1 = max(0, int(ys.min()) - 2), min(chip.shape[0], int(ys.max()) + 3)
        chip = chip[y0:y1, x0:x1]
    padded = cv2.copyMakeBorder(chip, 6, 6, 8, 8, cv2.BORDER_REPLICATE)
    return cv2.resize(padded, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
