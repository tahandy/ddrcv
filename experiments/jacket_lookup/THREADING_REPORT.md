# Threaded splash proof of concept

The later [name-performance investigation](NAME_PERFORMANCE_REPORT.md) interleaves
all methods and measures paced CPU cost. Use its recommendation for CPU headroom;
the separate-block combined timings below are historical evidence.

Parallel splash work is available inside the experiment. `--splash-execution
threaded` overlaps jacket lookup and difficulty recognition; the existing
`--difficulty-method ocr|template` toggle remains independent. These initial measurements used sequential execution by default; the current
working default is threaded templates with HighQoS (see `configuration.py`). `LatestSplashService` adds asynchronous submission with one
active frame and one replaceable pending frame.

Live name OCR already has its own `PlayerNameService` worker. Its capture loop,
confirmation policy and output schema have not changed. This experiment does not
wire jacket lookup into the desktop or live runtime.

## Scheduling and ownership

The chart worker crops a splash once, starts difficulty recognition on a persistent
worker, and performs jacket encoding/search/verification concurrently. Chart
resolution joins the jacket and difficulty from that same frame. Names remain an
independent observation stream: chart results do not wait for name OCR.

`ThreadedSplashLookup.analyze()` waits for one complete chart result, as required
by the one-shot CLI. `LatestSplashService.submit()` copies the input and queues
that call without waiting for inference. The service keeps the newest pending
sample, ignores duplicate/backward timestamps within a song generation, and
invalidates running results and errors on reset. Results include generation,
sequence and source timestamp. Callers must reset on song, seek or source changes.

Each service owns its processor and needs exclusive use of its `Lookup`. Names
and difficulty OCR need separate persistent recognizers; sharing one instance
would serialize inference on the recognizer's lock. Template difficulty needs no
OCR instance. No per-frame recognition results are cached.

## Paired CPU measurements

Windows i9-14900HX, CPU only, one native OpenCV/BLAS/ORT thread, warmed models and
indexes. Separate name and difficulty recognizers are reused by both scheduling
modes. Each pair uses identical inputs and alternates sequential/threaded order.
Three rounds of four passes over eleven clean TBD5 splash frames produce 132 calls
per scheduling mode, catalog and difficulty method.

The serial comparison performs chart lookup followed by both players' name OCR.
The concurrent comparison starts names independently and overlaps jacket and
difficulty work. File decoding, initialization and acquisition are excluded.
These are experiment scheduling measurements, **not measured improvements to the
live runtime**, whose names are already asynchronous.

Time until both chart and single-frame name observations are ready:

| Catalog | Difficulty | Sequential median / p95 / p99 ms | Threaded median / p95 / p99 ms |
|---|---|---|---|
| Full DDR | Template | 133.73 / 200.05 / 207.77 | 109.12 / 152.74 / 160.47 |
| Full DDR | OCR | 227.36 / 323.70 / 345.73 | 95.36 / 112.94 / 117.72 |
| Dia Del Ritmo | Template | 122.30 / 167.59 / 194.45 | 102.83 / 147.06 / 172.08 |
| Dia Del Ritmo | OCR | 209.40 / 293.87 / 333.37 | 90.32 / 111.03 / 130.00 |

Combined median and p95 improve in all three rounds for each catalog/method.
Names are single-frame observations from the existing `PlayerNameReader`; these
times exclude the live service's multi-frame confirmation interval.

Time until chart/max-EX results are ready, without waiting for names:

| Catalog | Difficulty | Sequential median / p95 / p99 ms | Threaded median / p95 / p99 ms |
|---|---|---|---|
| Full DDR | Template | 21.64 / 36.76 / 41.67 | 19.56 / 36.38 / 39.57 |
| Full DDR | OCR | 119.51 / 177.05 / 191.92 | 91.65 / 106.83 / 115.44 |
| Dia Del Ritmo | Template | 18.26 / 35.21 / 40.83 | 18.90 / 33.60 / 38.76 |
| Dia Del Ritmo | OCR | 106.39 / 161.85 / 174.01 | 86.27 / 104.90 / 127.39 |

Template chart processing is already short. Its Dia median increases slightly
under concurrency, so threading does not make every individual operation faster.
Workers share CPU resources; native scheduling and host load also influence
latency. Only paired comparisons within each method support the speed claim.
In particular, the combined OCR/template rows are not a controlled test of which
difficulty method is faster, and these absolute times should not be compared to
the earlier isolated lookup speed pass.

## Capture submission and bounded work

Two hundred rapid template-mode submissions per catalog measured the time to copy
a full 1280x720 BGR frame and enqueue it while processing continued:

| Catalog | Submit median / p95 / p99 ms | Maximum ms | Pending requests replaced |
|---|---|---|---|
| Full DDR | 0.99 / 2.01 / 2.34 | 2.43 | 193 |
| Dia Del Ritmo | 0.76 / 1.25 / 1.63 | 2.46 | 193 |

Replacement is intentional: this is a latest-sample service, not an all-frames
batch processor. Submission has a frame-copy and short locking cost but does not
wait for model inference. At most one active and one pending frame are retained
for analysis. This probe is not a sustained capture-throughput qualification.

Shutdown stops acceptance, cancels pending work and suppresses late publication.
`close(timeout=1)` is bounded and returns false if native work has not finished;
daemon workers exit when that call returns. Python cannot forcibly cancel an
in-flight OpenCV/ONNX call. Normal completed work closes both workers cleanly.

## Behavior and dependency checks

- 54 real frames (11 clean, 22 transitions, 21 negatives), both catalogs and both
  difficulty methods: 216 pre-refactor/current sequential comparisons and 216
  sequential/threaded comparisons.
- 528 additional paired warm comparisons verify complete chart and name outputs.
  Across all 960 comparisons, candidates, decisions, difficulty evidence, chart
  selections, max EX and provenance agree. Maximum numerical difference is zero,
  excluding timing fields. Frozen thresholds and templates were not changed.
- 66 focused tests passed across lookup, templates, the earlier speed pass,
  threading and player names. New tests prove overlap, copy ownership, backpressure,
  error recovery, stale-result/error rejection, bounded shutdown and chart progress
  while the real name-service worker is blocked by a controlled test reader.
- The threaded template CLI passed in the existing minimal test venv with imports
  of RapidOCR, ONNX Runtime, Torch and timm explicitly blocked. Mesmerizer P2 resolves
  to 1881 max EX; its out-of-pool P1 chart remains unavailable.

Repeated timing frames are not independent accuracy evidence. No new name
ground-truth evaluation, frozen-threshold calibration, synthetic accuracy campaign
or live capture qualification is claimed. Earlier accuracy limitations still
apply. Additional thread/model startup time and RSS were not profiled in this
follow-up; the warm comparison excludes initialization. Using difficulty OCR
alongside names requires two model instances instead of sharing one.

## Reproduction and artifacts

See [README.md](README.md#threaded-splash-experiment) for the CLI and asynchronous
API. Run the benchmark with:

```powershell
.venv\Scripts\python.exe -B -m experiments.jacket_lookup.threading_benchmark --repeats 4 --rounds 3
```

The parity run requires the retained, checksummed local pre-refactor source at
`artifacts/threading/baseline/lookup.py`. Generated artifacts remain ignored:

- `artifacts/threading/results.json`: raw paired complete and chart-stage timings.
- `artifacts/threading/summary.json`: aggregate and per-round timing distributions.
- `artifacts/threading/parity.json`: non-timing output comparisons on real frames.
- `artifacts/threading/validation.json`: test results, optional-import check and
  source/input hashes.
- `artifacts/threading/offline-threaded-demo.json`: dependency-isolated CLI result.

`measured_summary.json` also retains a concise `threading_followup` entry for review
without the large local artifact directory. No dependencies, installer behavior,
desktop code, live loop or publishing contract changed in this follow-up.
