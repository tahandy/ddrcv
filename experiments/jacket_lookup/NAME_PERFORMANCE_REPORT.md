# Splash name OCR and CPU headroom

Use **difficulty templates, one persistent OCR reader per player, and one native
inference thread per reader**. On the tested Windows i9-14900HX, requesting HighQoS
on the analysis workers gives good latency without the CPU cost of additional
native OCR workers. This configuration is the working default in the isolated experiment;
the desktop/live runtime has not been changed.

At the existing 5 Hz name sampling cadence, complete Dia splash parsing—including
both names, jacket lookup and difficulty—measured **28.71 ms median, 34.87 ms p95,
36.45 ms p99**, using **0.308 fully busy logical CPU cores on average**. The earlier
interleaved test measured 38.95 ms p95. These are warm single-frame observations,
not the time to confirm a name across multiple frames.

## What was slow

The existing name reader batches both names into one model invocation. It performs
almost all its work in ONNX inference: with one native thread and system-managed
scheduling, the interleaved Dia test measured median name inference of 80.52 ms
and crop preparation of 2.50 ms. Splitting work between two independent recognizers
allows their inference to overlap. Two Python threads sharing the same recognizer
would serialize on its inference lock.

The earlier apparent difficulty-OCR advantage was not reproduced in the comparable
system-managed, interleaved comparison: batch-one-thread combined p95 was 97.09 ms
with templates and 99.99 ms with difficulty OCR. Once names are accelerated,
difficulty OCR becomes the slow branch. Templates remain the preferred method.
Host scheduling affects timing substantially; the original separate-block
147-versus-111 ms comparison did not establish an OCR advantage or its cause.

## Interleaved comparison

Both catalogs, all eleven clean TBD5 splashes, three rounds of three passes:
**99 observations per configuration/catalog**. Every frame is run through all
sixteen configurations, with rotating and reversing order: batched/per-player
names, one/two native threads, system/HighQoS, and template/OCR difficulty.
OpenCV/BLAS and difficulty OCR use one native thread. Models and caches are warm;
file decoding and initialization are excluded. No affinity or priority changes.

Combined chart-and-name latency with difficulty templates:

| Name execution | Native threads per model | Worker policy | Dia median / p95 / p99 ms | Full DDR p95 ms |
|---|---:|---|---|---:|
| Batched | 1 | System | 84.50 / 97.09 / 99.74 | 96.32 |
| Batched | 2 | System | 49.47 / 58.23 / 75.70 | 61.64 |
| Per player | 1 | System | 46.32 / 58.09 / 62.86 | 57.98 |
| Per player | 2 | System | 32.04 / 40.52 / 48.55 | 41.57 |
| Batched | 2 | HighQoS | 31.25 / 45.17 / 49.55 | 43.13 |
| **Per player** | **1** | **HighQoS** | **20.56 / 38.95 / 41.57** | **37.72** |
| Per player | 2 | HighQoS | 19.48 / 33.21 / 36.31 | 31.81 |

At an equal two-native-thread budget, batching with two threads and splitting
names into two single-threaded models have similar system-managed p95. Merely
adding Python threads is not a universal speedup. HighQoS and native-thread count
are independent controls in this experiment.

With the recommended per-player/one-thread/HighQoS configuration, switching
difficulty to OCR raises complete p95 from **38.95 to 51.92 ms** for Dia and from
**37.72 to 53.24 ms** for full DDR. Template chart results are ready at p95
23.78 ms for Dia and 23.97 ms for full DDR, independently of names.

The recommendation's combined template p95 stayed below 41 ms in each interleaved
round for both catalogs. The 99 repetitions are timing samples from eleven splash
events, not 99 independent accuracy observations. p99 estimates remain limited
by these sample counts.

## Fresh processes and sustained CPU cost

The interleaved harness keeps multiple model configurations loaded, so its process
CPU readings include other native pools. They are not a fair measure of the
selected configuration's CPU demand. A second experiment loads only one selected
pipeline per fresh process, warms it, and processes 22 samples at 5 Hz. Three fresh
processes per configuration yield 66 latency samples. Process order rotates
between rounds; these runs are not paired within each frame.

CPU accounting includes the idle remainder of every 200 ms sampling period.
This matters because extra native workers can consume CPU after inference returns.
The strong difference below is consistent with native thread-pool spinning; no
ONNX runtime implementation or spinning settings were changed.

| Name execution | Native threads per model | Policy | Complete median / p95 / p99 ms | Average CPU cores |
|---|---:|---|---|---:|
| Batched | 2 | System | 55.33 / 78.34 / 95.13 | 1.234 |
| Batched | 2 | HighQoS | 33.40 / 48.92 / 60.02 | 1.197 |
| Per player | 2 | System | 29.66 / 40.32 / 47.22 | 2.237 |
| Per player | 2 | HighQoS | 18.48 / 35.98 / 37.25 | 2.230 |
| Batched | 1 | HighQoS | 44.53 / 56.53 / 59.38 | 0.262 |
| Per player | 1 | System | 23.98 / 37.92 / 44.36 | 0.315 |
| **Per player** | **1** | **HighQoS** | **28.71 / 34.87 / 36.45** | **0.308** |

CPU values are medians across three process-level measurements, expressed as
equivalents of fully busy logical cores, not a percentage of the whole machine.
Latency distributions pool the 66 calls. The recommended mode's individual-process
p95 values were 34.59, 36.30 and 33.01 ms. Its CPU demand was about 86% lower than
two native threads per player, with no useful p95 disadvantage in this paced test.
Small cross-run latency differences should not be interpreted as exact rankings.

These figures cover this parsing process, including idle native-pool work; they
exclude capture, UI, rendering and publishing. The real name service stops reading
a player once its name is confirmed, whereas this probe intentionally keeps
reading throughout all 22 samples.

## Initialization and memory

Three additional fresh processes per mode measured name-model initialization and
working set after eleven clean name pairs, without loading a jacket index:

| Mode | Init median ms | Warm process RSS MiB |
|---|---:|---:|
| Batched, one native thread | 345.8 | 95.9 |
| Batched, two native threads | 365.0 | 96.3 |
| Per player, one native thread | 470.3 | 106.9 |
| Per player, two native threads | 452.4 | 107.7 |

Two model instances add about 11 MiB in this probe. Initialization includes the
first RapidOCR import and model loading, but excludes first inference. These
small initialization differences vary by run. Load and warm models before timing;
reuse the readers afterward. No model or dependency was added.

## Implementation and verification

`PerPlayerNameReader` owns one persistent reader/model/worker per player and reuses
the existing crop preparation, confidence threshold and name validation. It
supports `read`, `read_login` and `warmup`; only supplied player crops are scheduled.
It copies inputs, preserves player keys, serializes sample calls and drains both
branches before propagating an error. Sharing a recognizer between its two readers
is rejected. Its close timeout is bounded; native calls cannot be forcibly stopped.

The reader can be supplied to the existing `PlayerNameService` in an experiment.
That service retains sampling, confirmation, latest-pending-frame and stale-song
rules. Name confirmation still requires multiple observations over time. Name
reading stays independent of the chart service; a slow name cannot delay chart
publication. Neither service is wired into a new live integration here.

`high_qos=True` is the default on `ThreadedSplashLookup` and `PerPlayerNameReader`.
Pass `high_qos=False` for a system-managed comparison.
The existing Windows helper applies a power-scheduling hint on each branch caller
and restores the prior state afterward. On unsupported platforms it is a no-op.
It does not change affinity or process/thread priority.

- 216 name-output comparisons cover all 54 real frames across four name layouts.
- 432 chart comparisons cover both catalogs, both difficulty methods and both
  scheduling policies on the same 54 frames.
- 3,168 timed pipelines add 3,168 name and 3,168 chart parity checks: **6,984 total
  comparisons**, with unchanged accepted names, chart decisions, max EX and
  provenance. Compared numerical chart differences are zero. The timed raw name
  text and confidence values also match exactly across configurations.
- **95 distinct tests passed**. The main suite passed 91 and skipped four optional
  model tests; all four were then explicitly enabled with the local pinned model
  and passed. Coverage includes worker overlap, one-player inputs, ownership,
  errors, shutdown, confirmation, real splash/login fixtures and OCR thread safety.
- Per-player reader construction remains lazy. A template-only demo with names
  disabled succeeds in the minimal venv while RapidOCR, ONNX Runtime, Torch and
  timm imports are blocked. Missing OCR dependencies fail clearly on model use.

These are behavior-preservation checks, not a new name-accuracy study. Existing
OCR mistakes, template abstentions, event eligibility and confirmation delays
remain possible. No thresholds, crop bounds, model weights or name-result caches
were changed.

## Run it

The combined demonstration defaults to template difficulty, per-player names,
one native thread per name and HighQoS, as fixed in `configuration.py`:

```powershell
.venv\Scripts\python.exe -B -m experiments.jacket_lookup.splash_demo --image experiments/jacket_lookup/artifacts/corpus/frames/2025-03-27_15-50-18_00.png
```

Use `--name-method batch|per-player|none`, `--name-threads 1|2`,
`--difficulty-method template|ocr`, `--worker-qos system|high`,
`--catalog event|full`, and `--style single|double` for explicit comparisons.
The one-shot demo reports initialization separately; its first inference may be
cold. It returns single-frame names alongside the existing chart result, without
changing that result's schema.

```powershell
.venv\Scripts\python.exe -B -m experiments.jacket_lookup.splash_profile --rounds 3 --repeats 3
.venv\Scripts\python.exe -B -m experiments.jacket_lookup.splash_paced --name-method per-player --name-threads 1 --qos high --out experiments/jacket_lookup/artifacts/name-profiling/paced-recheck.json
```

The defaults were promoted from this measured configuration; the original
benchmarks explicitly retain their comparison policies. A follow-up default-only
check passed 25 focused tests, the no-flag combined demo, and template lookup
without optional OCR imports. No new speed measurement is claimed for that check.

Raw timings, per-round summaries, output comparisons, resource/paced process
results, demo output and test logs are retained under ignored
`artifacts/name-profiling/`. `measured_summary.json` retains the compact findings
under `name_performance_followup`. No installation, desktop, live-loop or publishing
changes are required to review this experiment.
