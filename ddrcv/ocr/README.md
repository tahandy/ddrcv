# Persistent RapidOCR text recognition

`ddrcv.ocr` provides a CPU-only English PP-OCRv5 mobile recognizer. A single
instance owns a persistent model and serializes inference calls from threads.
It accepts **already-cropped text lines** and returns text plus confidence.
No detector, orientation model, original font files, Torch, Paddle, GPU, game
state, song database, or network service is required for inference.

## Install

From the repository root, in your application's environment:

```console
python -m pip install -r requirements-ocr.txt
python -m pip install -e .
```

Use Python **3.11 or newer** (the pinned ONNX Runtime requirement). Tested on
Windows x64 with Python 3.12.6. Direct requirements: `rapidocr==3.9.2`,
`onnxruntime==1.30.0`, `numpy==2.2.0`, `opencv-python==4.10.0.84`. Pip installs
transitive dependencies. Tournament, desktop, and workbench requirements include
these dependencies. Both application setup scripts provision the cached model
and require a successful real-model splash smoke test. Run
`python -B -m ddrcv.ocr.check` for an offline readiness check, or add `--provision`
to permit the initial model download. The legacy `get_best_match_from_results`
helper remains for the older parsers and sandbox scripts. The obsolete
`get_ocr_singleton` EasyOCR factory has been removed; use `get_rapidocr()` for
new crop recognition. Legacy EasyOCR demos construct their own reader and
still require EasyOCR; its `readtext` API differs from this component's API.

## One crop, repeated calls

```python
import cv2
from ddrcv.ocr import get_rapidocr, prepare_ddr_crop

ocr = get_rapidocr()  # same object for every caller in this Python process
ocr.warmup()         # optional: loads the model once, before capture begins

frame = cv2.imread('state_images/song_splash_updated.png')  # OpenCV BGR
name_crop = frame[464:496, 63:263]
result = ocr.recognize(prepare_ddr_crop(name_crop))
print(result.text, result.confidence)

# Later calls reuse the loaded model:
other_result = ocr.recognize(prepare_ddr_crop(frame[464:496, 1016:1216]))
```

`recognize(crop)` also works directly without preprocessing. `prepare_ddr_crop`
is the optional **original-color** preparation used in the pilot: locate white
text, remove edge-connected white background from the *trim mask*, keep original
image pixels, pad, and enlarge 2x. It does not replace the image with a binary
mask. It is specific to DDR's white text; it can clip text against borders or
misidentify decorative foreground. Supply a well-bounded crop. Other kinds of
text should normally bypass it.

## Batches and threads

```python
from concurrent.futures import ThreadPoolExecutor
from ddrcv.ocr import get_rapidocr

ocr = get_rapidocr()
results = ocr.recognize_many([crop_a, crop_b])  # same order as the inputs

with ThreadPoolExecutor(max_workers=4) as pool:
    results = list(pool.map(ocr.recognize, [crop_a, crop_b, crop_c]))
```

Initialization and inference are protected by locks. Sharing one instance is
safe but **serializes calls**, avoiding concurrent access to RapidOCR's mutable
recognizer state. `recognize_many` is usually preferable for known groups of
crops; the model batches internally (default six crops). There is no unbounded
background queue. Calls block the calling thread; use an application worker or
`asyncio.to_thread` when needed.

Inputs are copied before inference; they are never modified. Do not overwrite
a capture buffer while the call is making its input copy. Inference exceptions
release the lock. Failed initialization leaves the instance unloaded so a later
call can retry. `warmup()` is idempotent model loading, not a timed inference run.

Each explicit instance has its own model/lock. Model initialization is serialized
across instances within this process, while independent loaded instances may
infer in parallel. This costs more RAM/CPU. Locks do **not** coordinate processes:
provision/cache the model before starting multiple workers, create a recognizer
inside each worker, and do not share/fork an already-loaded ONNX session.

## Model cache and offline operation

Construction/imports do not load models or perform I/O. By default, the first
`warmup()` or nonempty recognition call downloads the ~7.5 MiB English model
through RapidOCR and caches it under:

- Windows: `%LOCALAPPDATA%/ddrcv/ocr`
- Linux/macOS: `$XDG_CACHE_HOME/ddrcv/ocr`, or `~/.cache/ddrcv/ocr`

The file is `en_PP-OCRv5_rec_mobile.onnx`. Cached/local models are SHA-256 checked
and passed directly to inference; a valid cached model needs no network access.
For an explicit cache, thread count, or offline configuration, share your own
instance instead of the zero-argument default getter:

```python
from ddrcv.ocr import RapidOCRRecognizer

# Provision once while online (only on the provisioning machine):
provisioner = RapidOCRRecognizer(model_dir='models/ocr')
provisioner.warmup()

# Deploy the resulting directory and prohibit downloads:
ocr = RapidOCRRecognizer(model_dir='models/ocr', allow_download=False)
ocr.warmup()  # fails immediately if the file is missing or invalid

# Or point directly to a read-only model file; it is never downloaded/replaced:
ocr = RapidOCRRecognizer(
    model_path='models/ocr/en_PP-OCRv5_rec_mobile.onnx',
    allow_download=False,
    num_threads=2,
    batch_size=6,
)
```

`model_dir` and `model_path` are mutually exclusive. The supported model's SHA-256
is `c3461add59bb4323ecba96a492ab75e06dda42467c9e3d0c18db5d1d21924be8`.
This component intentionally supports this exact English recognition model;
arbitrary replacement models are rejected. A checksum failure never silently
downloads over a local file. Re-provision that file deliberately.

## API contract

- `get_rapidocr() -> RapidOCRRecognizer`: process-wide lazy default instance.
- `RapidOCRRecognizer(*, model_dir=None, model_path=None, allow_download=True,
  num_threads=2, batch_size=6)`: configurable independent instance. Positive
  integer thread/batch values; threads are capped to the host CPU count.
- `warmup() -> None`: load/verify the model once.
- `recognize(image, *, color_order='bgr') -> OCRResult`.
- `recognize_many(images, *, color_order='bgr') -> list[OCRResult]`.
- `prepare_ddr_crop(image, *, color_order='bgr') -> ndarray`: optional helper,
  always returns BGR (do not mark its output RGB again).

Images must be nonempty `uint8` NumPy arrays: grayscale `H×W` or color `H×W×3`.
OpenCV BGR is the default. For RGB arrays, explicitly pass `color_order='rgb'`.
Convert alpha images yourself. Noncontiguous crop views are supported. Paths,
encoded bytes, floating-point images, and empty crops are rejected. An empty
batch returns `[]` without loading the model.

`OCRResult` is immutable and has `text: str` and `confidence: float`. Outer
whitespace is stripped; case, internal spaces, punctuation, and digits are
preserved. A model response with no text becomes `OCRResult('', 0.0)`.
Invalid inputs raise `TypeError`/`ValueError`; missing models raise
`FileNotFoundError`; missing optional dependencies raise an actionable
`ImportError`. Model/inference errors propagate rather than becoming false text.

Confidence is not a calibrated probability. This layer performs no acceptance
threshold, numeric parsing, player association, layout detection, or temporal
voting. Callers must handle those policies. A blank/noisy crop can still produce
nonempty hallucinated text; an OCR score alone is not proof of correctness.

## Validation and maintenance

```console
python -B -m unittest discover -s tests -p test_rapidocr.py -v
```

Default tests use a fake backend and never download/load a model. For the optional
real-model tests, set `DDRCV_TEST_OCR_MODEL` to the provisioned ONNX file and run
the same command. They exercise offline initialization, DDR splash/results names
and scores, batch order, grayscale/RGB inputs, and shared-instance concurrent calls.

The adapter directly constructs RapidOCR's `TextRecognizer`: the full pipeline
constructor also loads detector/classifier models even when those inference
stages are disabled. This internal API is isolated in `_build_engine` and the
RapidOCR version is pinned/checked. Run both mocked and real-model tests before
upgrading it. The pilot's small, correlated data set favors this recognizer but
does not establish arbitrary-font/name accuracy. The research suite is not a
runtime dependency and is not merged with this component.
