> The classical matcher and threaded service are now maintained in the package.
> See [song recognition](../../doc/song_recognition.md) and
> [integration validation](INTEGRATION_REPORT.md). The historical results below
> describe the isolated experiment; research commands remain available.

# CPU jacket lookup experiment

## Working configuration

The default splash pipeline is locked to **template difficulty, threaded jacket
lookup, one OCR worker per player, one native thread per name, and HighQoS**.
The event remains Dia Del Ritmo 2026 and the style remains Singles.
[configuration.py](configuration.py) is the shared source of these defaults.
Comparison options remain explicit, and this configuration applies only to the
experiment. Use `splash_demo --image <frame.png>` for the complete pipeline.

This is a source-checkout proof of concept. It does not change the live driver,
desktop UI, renderer, WebSocket messages, or publishing services.

The measured recommendation is the **128-pixel classical color/gradient
descriptor with correlation verification**, using NumPy, OpenCV, and Pillow.
Difficulty can now use an optional five-label template matcher with no digit
recognition. See [DIFFICULTY_REPORT.md](DIFFICULTY_REPORT.md) for its measured
speedup and brightness/transition limits. RapidOCR remains available as the
baseline. [REPORT.md](REPORT.md) contains the original jacket comparison.

## Install or update an existing checkout

From the repository root on Windows x64 CPython 3.12:

```bat
setup_desktop.bat -JacketLookup
```

For an unattended update to the current compatible `.venv`:

```bat
set DDRCV_SETUP_NO_PAUSE=1
setup_desktop.bat -JacketLookup -NonInteractive
```

The workbench installer accepts the same flag. Close DDRCV before updating its
environment, as with the existing installer. Setup reuses a compatible venv,
uses the locked dependencies, and preserves unrelated installed packages with
`--inexact`. It never replaces an incompatible venv. The flag is opt-in; normal
setup does not enable or run the experiment.

For a minimal experiment-only environment, the optional extra is
`.[jacket-lookup]`. It adds the existing OCR stack to the base image-processing
dependencies. It does **not** add Torch, torchvision, timm, FAISS, ONNX export
tools, matplotlib, or ImageHash. The recommended jacket encoder has no model
weights. OCR provisioning uses the existing pinned RapidOCR model/cache.

```powershell
.venv\Scripts\python.exe -B -m experiments.jacket_lookup check --provision
.venv\Scripts\python.exe -B -m experiments.jacket_lookup check
```

## Prepare the catalog and reference index

All commands below run from the repository root. Defaults use the pinned
DDRCardDraw commit `c62053faa82df55ebc926812a7af684f520ae704` and Dia Del Ritmo 2026.
Initial catalog preparation needs network access; encoding and lookup use only
local files. Assets and original JSON are cached, checksummed, and ignored by Git.

```powershell
.venv\Scripts\python.exe -B -m experiments.jacket_lookup catalog --mode event --event "https://ddr.tools/#game-dia_del_ritmo_26"
.venv\Scripts\python.exe -B -m experiments.jacket_lookup catalog --mode full
.venv\Scripts\python.exe -B -m experiments.jacket_lookup encode --catalog experiments/jacket_lookup/artifacts/catalog/dia_del_ritmo_26.json --out experiments/jacket_lookup/artifacts/index/event-classical-128
.venv\Scripts\python.exe -B -m experiments.jacket_lookup encode --catalog experiments/jacket_lookup/artifacts/catalog/full.json --out experiments/jacket_lookup/artifacts/index/full-classical-128
```

Event mode keeps every chart listed in that event JSON; ddr.tools' default UI
level/difficulty selections are not eligibility rules. Full mode inventories
all DDR jacket directories and DDR metadata records, including historical and
event records. Historical non-square banners are inventoried and explicitly
excluded from square-jacket matching. It does not stretch banners into jackets.

Identical file contents are encoded once. All associated song identities and
dataset-specific charts remain available. Shared artwork is ambiguous unless
it represents the same song identity. Missing event EX can be supplemented from
WORLD only for an unambiguous exact song/style/difficulty/level match; existing
event values are retained. Each value records its source dataset and commit.

## Extract and label footage

```powershell
.venv\Scripts\python.exe -B -m experiments.jacket_lookup extract --videos D:/TBD5
```

The extraction scans the seven original MKVs at 2 Hz, finds splash intervals
with the bundled WORLD templates, and selects the sharpest central detected
frame without consulting retrieval results. It saves lossless full frames,
jacket crops, difficulty crops, entry/exit frames, negative controls, file hashes,
timestamps, and review sheets. The overlapping `trimmed` video is excluded.

`ground_truth.json` contains the manually inspected identities and both player
chart labels for this footage. Artwork candidate proposals were visually
verified against the source images; they were not accepted automatically as
ground truth. The transition visibility annotations in the benchmark describe
this particular TBD5 corpus. New footage needs fresh manual labels and review.

## Calibrate, evaluate, and inspect

The complete research comparison tests classical descriptors, SIFT verification,
MobileNetV3-Small ONNX features, and the existing EfficientNet-B0 weights, each
at 128 and 150 pixels. All methods use the same square preprocessing and NumPy
exact search. The EfficientNet comparison is its encoder family under these
controlled conditions, not a timing of the entire old scraper/FAISS application.

The neural research methods require development tools, **separate from the
optional user install**. This checkout used its existing Torch 2.5.1,
torchvision 0.20.1, timm 1.0.12, and legacy EfficientNet checkpoint. ONNX 1.17.0
was installed under `artifacts/export-tools` with `uv pip install --target ...
--no-deps onnx==1.17.0`. Export MobileNet once from that development environment:

```python
import sys
sys.path.insert(0, "experiments/jacket_lookup/artifacts/export-tools")
from experiments.jacket_lookup.features import export_mobilenet
export_mobilenet("experiments/jacket_lookup/models")
```

The export downloads torchvision's named pretrained weights, writes a checksummed
ONNX graph, and records the preprocessing and exporter versions. Lookup loads
ONNX Runtime's CPU provider only. The legacy checkpoint is read from its existing
cache; this experiment does not rewrite legacy code or install its dependency set.

```powershell
.venv\Scripts\python.exe -B -m experiments.jacket_lookup benchmark --phase calibrate
.venv\Scripts\python.exe -B -m experiments.jacket_lookup benchmark --phase evaluate
.venv\Scripts\python.exe -B -m experiments.jacket_lookup evidence
```

Calibration groups all appearances/perturbations of a song together and uses a
deterministic five-song calibration/six-song evaluation split. It freezes the
thresholds, input hashes, and preferred configuration before evaluation. An
existing frozen run cannot be recalibrated in place: select a new output folder.
Synthetic perturbations and repeated timings are reported separately from
independent songs. Similarity scores are not confidence probabilities.

For a new classical-only run in a minimal environment, add
`--methods classical --sizes 128 --out experiments/jacket_lookup/artifacts/classical-only`
to the benchmark command. Use that output folder for subsequent evaluation and
evidence commands. No neural development dependencies are needed for that path.

The `artifacts/benchmark` directory contains the full per-query JSON, frozen
configuration, cold/steady-state profiles, stage timings, max-EX evidence, and
visual review sheets. The `evidence` command uses fresh processes for each
method's memory/latency profile. All benchmarks fix OpenCV, BLAS, and inference
to one thread and use CPU execution only.

## Query a saved splash

After calibration, use the profile bound to that exact index:

```powershell
.venv\Scripts\python.exe -B -m experiments.jacket_lookup lookup --index experiments/jacket_lookup/artifacts/index/event-classical-128 --thresholds experiments/jacket_lookup/artifacts/benchmark/event-classical-128-thresholds.json --image experiments/jacket_lookup/artifacts/corpus/frames/2025-03-27_15-50-18_00.png --splash --style single
```

One-shot CLI calls include cold index/OCR initialization. The reported warm
latencies reuse a `Lookup` instance and a warmed `RapidOCRRecognizer`; the
`evidence` command measures both initialization and warm calls separately.

Omit `--splash` for an already-cropped jacket. Add `--output result.json` to save
the response. Full-splash input is the supported uncropped 1280x720 WORLD layout.
Singles is the explicit default; Doubles can be selected with `--style double`
and is not inferred from player count. The recorded proof covers Singles only.

The result contains acceptance/rejection, top song candidates, score/margin,
per-player OCR text and chart selection, `max_ex`, source provenance, and stage
timings. Missing metadata, ambiguous identities/charts, low confidence, and
out-of-event charts yield no EX value. An unknown song is a rejected retrieval,
not a confidently identified out-of-pool song. Index-bound profiles prevent
silently applying thresholds from another catalog or encoder.

## Validation

```powershell
.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_jacket_lookup.py -v
powershell -NoProfile -ExecutionPolicy Bypass -File tests/test_setup.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File tests/test_setup_menu.ps1
```

Large generated catalogs, indexes, models, frames, and development environments
remain under the ignored artifact/model directories. The source and concise
measured report are reviewable without committing those downloads.

## Difficulty-only templates

Build and freeze the small label bank from the already extracted TBD5 corpus,
then compare it with OCR. This follows a separate source/calibration/evaluation
split, excluding every template-source song from evaluation. The commands need
the prepared jacket indexes and their existing `artifacts/benchmark/frozen.json`.

```powershell
.venv\Scripts\python.exe -B -m experiments.jacket_lookup difficulty-benchmark --phase calibrate
.venv\Scripts\python.exe -B -m experiments.jacket_lookup difficulty-benchmark --phase evaluate
```

An existing bank cannot be recalibrated in place; use `--out` with a new directory.
The comparison requires OCR; subsequent template lookup does not import or use it.
The five templates are derived locally from verified source crops, so they need no
network or additional model installation. They target the recorded WORLD layout.

```powershell
.venv\Scripts\python.exe -B -m experiments.jacket_lookup lookup --index experiments/jacket_lookup/artifacts/index/event-classical-128 --thresholds experiments/jacket_lookup/artifacts/benchmark/event-classical-128-thresholds.json --image experiments/jacket_lookup/artifacts/corpus/frames/2025-03-27_15-50-18_00.png --splash --style single --difficulty-method template
```

`--difficulty-templates` selects a custom bank directory. The default is
`experiments/jacket_lookup/artifacts/difficulty-template`. Template difficulty is
the working default; `--difficulty-method ocr` selects the OCR comparison path.

For repeated calls, load `DifficultyTemplates(bank_dir)` once and pass it as
`difficulty_reader=` to `lookup_splash`. The response contains per-class scores,
rejection reasons, and a `difficulty` stage timing. `metadata_level` is returned
only from a uniquely resolved catalog chart; the template path never reads digits.
Low similarity/separation returns `uncertain_chart` and no max EX. Faded and dim
labels abstain, so use stable splash frames. There is no implicit OCR fallback.

```powershell
.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_difficulty_templates.py -v
```

## Lookup performance and reuse

[PERFORMANCE_REPORT.md](PERFORMANCE_REPORT.md) contains the behavior-preserving
speed pass: paired timings, zero-difference checks, initialization and memory.
The OCR/template command-line switch and existing frozen profiles are unchanged.

Reuse a `Lookup` instance across frames. It now retains its splash detector,
selected-dataset chart index, lazily cached reference grayscale images, and lazy
default OCR recognizer. Passing `recognizer=` still overrides the default;
passing `difficulty_reader=` selects template recognition without OCR imports.
The first OCR call can load its model. Warm measurements exclude that loading.
Treat a loaded index/catalog as a snapshot; construct a new `Lookup` after
changing source metadata or index assets.

```powershell
.venv\Scripts\python.exe -B -m experiments.jacket_lookup.performance --phase compare
.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_jacket_performance.py -v
```

The comparison requires the retained local pre-change source snapshot under
`artifacts/performance/baseline/` plus the existing corpus, indexes and OCR model.
For a future comparison, capture with `--phase snapshot --out <new-directory>`
before editing, and use the same `--out` for the comparison afterward.

## Threaded splash experiment

The existing live player-name service already uses an independent background
worker. Jacket/max-EX recognition remains outside the live runtime. This experiment
now offers parallel jacket/difficulty processing plus a bounded asynchronous API;
[THREADING_REPORT.md](THREADING_REPORT.md) contains measurements and limitations.

Full-splash lookup defaults to threaded execution, template difficulty and
HighQoS. Use `--splash-execution sequential`, `--difficulty-method ocr`, or
`--worker-qos system` for explicit comparisons:

```powershell
.venv\Scripts\python.exe -B -m experiments.jacket_lookup lookup --index experiments/jacket_lookup/artifacts/index/event-classical-128 --thresholds experiments/jacket_lookup/artifacts/benchmark/event-classical-128-thresholds.json --image experiments/jacket_lookup/artifacts/corpus/frames/2025-03-27_15-50-18_00.png --splash --difficulty-method template --splash-execution threaded
```

`ThreadedSplashLookup` runs difficulty reading on a persistent worker while the
calling analysis thread encodes, searches and verifies the jacket. It joins those
two results from the same sample before resolving max EX. Its `analyze()` call
waits for that result, which is appropriate for the one-shot CLI. Use the service
below when the producer must continue capturing frames:

```python
from experiments.jacket_lookup.threaded import ThreadedSplashLookup, LatestSplashService

# lookup and difficulty_reader are already loaded, as in the earlier examples.
processor = ThreadedSplashLookup(lookup, difficulty_reader=difficulty_reader)
with LatestSplashService(processor) as charts:
    charts.submit(frame, timestamp=source_seconds, generation=song_generation,
                  style="single")
    # Returns immediately after copying/enqueuing; inference happens in workers.
    completed = charts.snapshot()  # None until a complete result is ready
    # Poll again later, or use charts.changed as a completion/reset notification.
```

Reuse the service across frames. It owns the processor and closes both workers.
Allow it exclusive use of the supplied `Lookup` while running. It keeps one active
sample and only the newest pending sample; replaced requests are not processed.
Snapshots contain generation, request sequence, source timestamp, result and error.
There is no inference or wait for a model on the submitting thread.

Submit confirmed splash samples only. Pass the current song generation and call
`reset(new_generation)` on song, source or seek changes even if no new splash is
submitted. Reset invalidates running results/errors, clears pending work and
clears the snapshot. Duplicate/backward timestamps are ignored within one epoch;
reset starts a new epoch. A failed sample reports an error and later samples can
recover. Completed results are one-frame observations, not new temporal confirmation.

`close(timeout=1)` stops acceptance, cancels pending work and suppresses late
publication. It returns false if a native call is still running when the timeout
expires; daemon workers exit after that call returns. It cannot forcibly cancel
an in-flight OpenCV/ONNX call. Normal completed work closes cleanly.

Keep name OCR in its existing `PlayerNameService`, with its existing sampling and
confirmation policy. Do not wait for names before consuming a chart snapshot. If
using OCR for difficulty, use a separate persistent `RapidOCRRecognizer` for that
branch: sharing the names recognizer would serialize both calls on its lock.
Warm the independent OCR instances ahead of timed work, and use one native
inference thread per instance when comparing concurrency. Template difficulty
with names disabled still works without importing OCR.

```powershell
.venv\Scripts\python.exe -B -m experiments.jacket_lookup.threading_benchmark
.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_threaded_splash.py -v
```

The timing comparison includes single-frame name observations from the existing
name reader, with separate warmed name/difficulty OCR instances. It measures both
chart-ready latency and time until all branches are ready. It does not measure
name confirmation across multiple frames or publish any results. Reproducing the
pre-refactor parity comparison requires the retained local snapshot under
`artifacts/threading/baseline/`; generated outputs stay ignored.

## Name OCR headroom

[NAME_PERFORMANCE_REPORT.md](NAME_PERFORMANCE_REPORT.md) contains the interleaved
method comparison and fresh-process CPU measurements. Recommended on the tested
Windows machine: templates, one persistent OCR model/worker per player, one native
thread per model, and HighQoS enabled by default. The paced Dia test measured
34.87 ms complete p95 with about 0.31 logical CPU cores of average use.

```powershell
.venv\Scripts\python.exe -B -m experiments.jacket_lookup.splash_demo --image experiments/jacket_lookup/artifacts/corpus/frames/2025-03-27_15-50-18_00.png
```

The shared [working configuration](configuration.py) is frozen and defaults to
`--name-method per-player --name-threads 1 --difficulty-method template
--worker-qos high`. Other choices are `--name-method batch|none`,
`--name-threads 2`, `--difficulty-method ocr`, `--worker-qos system`,
`--catalog full`, and `--style double`. It returns names and the existing chart
result in a separate experiment response. One-shot first inference may be cold;
use the benchmark for warmed distributions. `--name-method none` with templates
requires no OCR imports or model.

`PerPlayerNameReader` is compatible with the existing name-service reader API:

```python
from ddrcv.state.player_names import PlayerNameService
from experiments.jacket_lookup.names import PerPlayerNameReader

config = {"enabled": True, "ocr": {"allow_download": False, "num_threads": 1}}
with PerPlayerNameReader(config) as reader:
    names = PlayerNameService(config, reader=reader)
    try:
        # In an experiment's frame loop, independently of LatestSplashService:
        names.submit(frame, timestamp, "song_splash", "song_splash",
                     (True, True), song_generation)
        confirmed_names = names.snapshot()
    finally:
        names.close()
```

Supply actual detected presence and confirmed state in a real experiment loop;
the constants above illustrate an already-confirmed two-player splash. Keep the
same reader/service alive across frames, reset it on generation/source changes,
and let existing temporal confirmation run. `read()` itself waits for both name
workers, so use it on the service worker rather than capture. Close the service
before its reader; reader shutdown is bounded and cannot kill native inference.

`ThreadedSplashLookup` and `PerPlayerNameReader` enable HighQoS by default. Pass
`high_qos=False` to either component to opt out. The former still accepts an
explicit difficulty reader; use `DifficultyTemplates` for the working template
method. HighQoS restores the prior thread policy after each call,
is best effort on Windows, and is a no-op elsewhere. No desktop/live integration
is enabled by these experiment APIs.

```powershell
.venv\Scripts\python.exe -B -m experiments.jacket_lookup.splash_profile --rounds 3 --repeats 3
.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_parallel_names.py -v
```
