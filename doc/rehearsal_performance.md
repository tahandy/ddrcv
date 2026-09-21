# Rehearsal performance investigation

Measured on Windows Python 3.12.6 with the supplied native 1280×720, 30 fps
`2025-03-27_15-52-48.mkv` recording, around 150 seconds into gameplay. The baseline
was commit `d70b9a2`. Measurements below are short steady-state samples, not a
claim about every frame in the recording or other capture hardware.

## Causes and changes

1. **Playback used a coarse clock and timed queue waits.** On this runtime,
   `time.get_clock_info('monotonic')` reports Windows `GetTickCount64()` with
   15.625 ms resolution. This quantized the reported processing duration to
   values such as 0, 15, or 31 ms. Playback also accumulated wakeup delay because
   each deadline was relative to the actual start of the previous frame.
   Together these produced roughly 21 fps on a 30 fps source, even though actual
   processing took about 10–12 ms. The worker now uses `perf_counter()`
   (`QueryPerformanceCounter()`), advances an absolute schedule, and uses short
   high-resolution sleeps. It neither busy-waits nor changes the system timer
   resolution. Slow parsing still keeps every recorded frame.
2. **The main picture was limited to four updates per second.** It fetched a new
   JPEG only during the 250 ms status poll. The picture now uses the same MJPEG
   delivery mechanism as the clean view, with an optional monitored overlay.
   Delivery runs independently at up to 30 fps; text and score crops keep their
   slower update rate. Paused viewers wait for changes, with a small heartbeat
   to detect disconnected clients.
3. **Color conversion and preview delivery did unnecessary work.** NumPy channel
   reversal/copy cost about 3 ms per frame in isolation. OpenCV conversion gives
   identical pixels in about 0.6 ms. Its thread pool is limited to one thread:
   the default 32-thread pool did not improve this small operation's latency and
   used more CPU. Preview viewers now share JPEG encoding for the same view and
   frame, and full images are copied only when drawing overlays.

## Measured result

Each row uses a five-second sample after warmup, a real Edge browser, and a
fresh workbench process. “Frame work” is independently measured decode plus
recognition/publication, excluding the deliberate playback wait.

| Open clients | Before: parsing fps | After: parsing fps | Before: mean frame work | After: mean frame work | After: p95 frame work |
| --- | ---: | ---: | ---: | ---: | ---: |
| Panel | 21.1 | 30.0 | 12.4 ms | 7.1 ms | 8.1 ms |
| Panel and clean view | 21.2 | 30.0 | 10.2 ms | 7.3 ms | 8.5 ms |
| Panel, clean view, renderer | 21.2 | 30.0 | 10.4 ms | 7.5 ms | 9.0 ms |

Workbench CPU with both views and the renderer was approximately 0.57 CPU cores
before and 0.64 cores after; renderer CPU was approximately 0.10 and 0.08 cores.
These are process CPU-time/wall-time ratios, not percentages of the whole
32-logical-CPU machine, and exclude the browser and OBS. More frames are now
processed and displayed each second, so reduced work per frame does not imply
less aggregate CPU consumption. Whole-computer lag was **not reproduced** in
these measurements; that part of the original report remains unconfirmed.

The source timestamps, score filters, state confirmation, score WebSocket
payload, and clean-view pixels are unchanged. Tests cover the 30 fps cadence,
all-frame replay at different speeds, exact RGB conversion, shared encoding,
paused/stepped streams, overlays, and snapshots. The full regression command is
in [the handoff guide](tournament_handoff.md).

Restart the workbench after updating; the launcher intentionally disables live
code reloading. No dependency reinstall is needed for these changes.

## Gameplay capacity follow-up (September 2026)

A [September 20 investigation using the trimmed recording and full tray app](desktop_throughput_investigation.md) compares these measurements with the operator's reported 26 ms/frame and provides a read-only timing recorder.

The reported approximately 33 ms of active gameplay processing was investigated
separately from the recording's 30 fps playback limit. The initial isolated
recognizer checks took 4.2–4.7 ms/frame. Attribution runs through the production
desktop controller/runtime, local API, native WebView2 panel and optional Pygame
renderer took 5.8–9.6 ms/frame on average during gameplay. They did not reproduce
a sustained 33 ms average. These probe sessions do not start the tray host or
connect to physical capture hardware or OBS.

Masked glyph template matching dominated active frame time. Publication cost
approximately 0.07–0.12 ms/frame, and measured lock acquisition approximately
0.004–0.006 ms/frame. The outbox/history path was therefore left unchanged.
Packing glyph templates into contiguous arrays only saved about 1% in a narrow
microbenchmark and was not retained.

The retained change avoids allocating/converting a full 1280×720 RGB image for
each recognition call. The existing consumers read small crops and accept
strided arrays, so `frame[..., ::-1]` provides the same RGB pixels as a view.
This removes one approximately 2.6 MiB allocation per frame. Matching methods,
masks, thresholds, score filters, source timestamps and frame cadence stay the
same. Six alternating isolated trials gave 4.14–4.37 ms/frame for the original
conversion and 3.62–3.79 ms/frame for the view, with identical recognition output.
This is approximately a 12% reduction in isolated processing time. Numeric scores
repeated on approximately 80% of consecutive gameplay frames, but only 21–31% of
their preprocessed crops were identical. No recognition cache was introduced in
this pass.

### Repeated desktop results

The unprofiled comparison completed 36 trials: three repetitions of each
interval/condition/engine combination. Values below pool gameplay frames across
the three repetitions; the ending interval includes only its gameplay frames in
this table. Each cell is original → RGB view, in milliseconds.

| Interval | Condition | Mean | p95 | p99 |
| --- | --- | ---: | ---: | ---: |
| 150–170 s | Headless runtime | 7.25 → 5.73 | 15.82 → 8.18 | 25.42 → 16.04 |
| 150–170 s | Native panel | 11.25 → 10.74 | 26.82 → 27.06 | 54.90 → 56.55 |
| 150–170 s | Panel + renderer | 11.60 → 6.16 | 29.31 → 10.50 | 64.13 → 17.02 |
| 248–265 s | Headless runtime | 6.78 → 6.61 | 13.06 → 13.91 | 15.14 → 21.40 |
| 248–265 s | Native panel | 7.14 → 6.54 | 13.30 → 13.26 | 19.84 → 20.63 |
| 248–265 s | Panel + renderer | 6.59 → 5.81 | 12.45 → 10.39 | 19.55 → 15.40 |

Full-runtime timing varied substantially. One original panel+renderer trial
averaged 23.10 ms/frame; one optimized panel trial averaged 20.67 ms/frame.
The worst observed two-second gameplay average was 26.76 ms (37.4 fps capacity)
for the original and 24.98 ms (40.0 fps capacity) for the view. Individual frames
exceeded 33 ms, but the reported sustained approximately 30 fps capacity was not
reproduced. The view removes a measured cost; it does **not** eliminate the tail
spikes or establish the cause of the reported slowdown. Do not interpret the
large renderer-row average difference as the guaranteed gain from this change.

Actual recording throughput remained approximately 26–28 fps, with decode and
existing playback pacing included. Across conditions, whole-trial backend CPU
usage ranged from 0.38–0.52 cores originally and 0.36–0.49 cores with the view.
The per-condition CPU, throughput, capacity and individual trial values are in
`.desktop-validation/gameplay-comparison/summary.json`; complete measurements
are in that directory's `report.json` and per-trial subdirectories.

All 18 paired recognition traces matched exactly. The focused regression runner
passed **216 tests, no skips**, including installed-model checks, real glyph/state
comparisons on strided and contiguous RGB crops, and input-frame immutability.
An additional EX/Money comparison covers both players, either single-player
position, real full-combo frames and unknown frames; its receipt is
`equivalence.json` in the comparison directory.

The timed ending slice deliberately stops at 265 seconds. With the saved
five-second results settling setting, that can precede completion of results OCR.
A separate 248–278 second replay with native panel and renderer confirmed final
gameplay scores 1,615 / 1,632 and a saved results frame at 265 seconds with
XETA / DANOOCT1 and P2 winning by 17. Receipt:
`.desktop-validation/gameplay-full-combo/report.json`. No external messages were
sent. Fully exit and relaunch the desktop backend to load the optimization.

### Reproducing the desktop comparison

The existing Windows probe now supports a gameplay matrix and optional stage
attribution. Probe dependencies remain optional and isolated:

```bat
.venv\Scripts\python.exe -B -m pip install --target .desktop-validation\test-deps psutil
.venv\Scripts\python.exe -B tools\validate_desktop_windows.py --gameplay --video apps\scripts\2025-03-27_15-52-48.mkv --compare-revision d279afe --repeats 3 --out .desktop-validation\gameplay-comparison
```

Use a fresh output directory each time. `--config` accepts a profile or saved
desktop state; the measured run used the saved EX settings. The probe freezes
those settings once, redirects storage to its output directory, uses a private
loopback score port, and disables Discord/OBS. Names and results capture remain
enabled. `--renderer-path` selects the sibling renderer checkout when needed.

Each trial starts a fresh process, plays five seconds of warmup, then measures
150–170 seconds of steady gameplay or 248–265 seconds around the verified
perfect-full-combo ending and results transition. Conditions are headless runtime
(including its normal background services), native panel, and panel plus renderer.
The reference engine is loaded from the specified commit; all other production
code is shared because the optimization changes only that engine. Reference and
current order alternate between repetitions. Every paired frame trace must match.

`report.json` contains mean/p95/p99 active times, processing capacity, actual
throughput, recognition-thread CPU time, whole-trial backend CPU usage, and child
process CPU totals. `frames.json` and `trace.json` retain the per-frame evidence.
Startup samples are separate from the measurement interval. Thread CPU accounting
on Windows is coarse; its mean is useful, not individual frame values. Backend
CPU totals include startup and cleanup, and child totals span each child's sampled
lifetime. Native panel and renderer processes are closed after each trial.

For attribution, add `--profile-stages`; normal comparison runs omit it. Stage
timings include nested calls and must not be summed. Decode/playback waits are
reported separately and excluded from active processing capacity. No profiler,
extra telemetry, or new configuration setting is installed in the application.

## Exact glyph reuse and integer preprocessing (September 20, 2026)

The glyph detector now uses integer preprocessing for RGB `uint8` inputs:
`R * G * B >= 129 * 255 * 255`, with `uint32` multiplication to avoid overflow.
It produces the same 255/1 matcher input; other input types retain the original
floating-point path. Each detector keeps only its last preprocessed crop and
detections. Reuse requires exact pixel equality plus unchanged threshold, scale,
and ordered glyph/mask shapes, dtypes, and contents. Returned detections are
independent copies, including on cache hits. Matching methods, masks, thresholds,
search regions and suppression are unchanged. Every frame still enters temporal
score validation with its current timestamp, even when matching is reused.

### Recognition and extraction validation

All **16,777,216 RGB colors** produced exactly the original preprocessing output.
Focused tests also cover strided/read-only inputs, legacy input types, changed
pixels, empty detections, template/settings changes, cache isolation, and mutation
of returned detections. The regression runner passed **244 tests, no skips**,
including installed-model and recorded-video tests.

The trimmed recording's 10–155 second interval produced **4,350 identical complete
recognition traces**, covering detection dictionaries, raw/accepted scores,
temporal decisions, state transitions, and publication. This includes full-combo
animation and results transitions. Another 111 extraction comparisons checked
either player absent and both absent. The extraction benchmark also compared
13,320 complete detection outputs exactly.

Three alternating baseline/optimized trials measured 2,220 player crops each,
preloaded from 20–40 and 110–127 seconds of
`2025-03-27_15-52-48_trimmed.mkv`. Times include preprocessing, cache validation,
matching or reuse, and detection output creation; video decoding is excluded.

| Trial | Baseline ms/player crop | Optimized ms/player crop |
| --- | ---: | ---: |
| 1 | 1.669 | 1.227 |
| 2 | 1.646 | 1.208 |
| 3 | 1.671 | 1.205 |
| Median | **1.669** | **1.208** |

Median extraction improved **27.6%**, exceeding the 15% retention requirement.
That isolated result saves approximately 0.92 ms per two-player frame.

### Native desktop and renderer validation

Six fresh native runs used the actual persistent tray host, WebView2 desktop
panel, production background recognition thread, and external renderer. Each
played 15–40 seconds of the same trimmed recording, with 20–40 seconds used for
the steady gameplay comparison after warmup. The saved operator settings were
copied to isolated profiles, ports, and output directories. OBS control and
Discord delivery were disabled. Python was 3.12.6, OpenCV 4.10.0 with one OpenCV
thread; stage profiling was disabled. Order alternated baseline/optimized,
optimized/baseline, baseline/optimized.

| Trial | Whole replay mean, baseline → optimized | After warmup mean, baseline → optimized | Highest sampled two-second mean, baseline → optimized |
| --- | ---: | ---: | ---: |
| 1 | 9.24 → 7.02 ms | 9.93 → 7.50 ms | 12.20 → 9.52 ms |
| 2 | 9.14 → 5.98 ms | 9.19 → 6.73 ms | 12.38 → 9.79 ms |
| 3 | 9.87 → 7.67 ms | 10.84 → 8.32 ms | 12.21 → 9.98 ms |

Whole replay means include all 750 frames per trial, including warmup; pooled
means were **9.42 → 6.89 ms/frame**. After warmup, pooled means across 1,800 frames
per variant were **9.99 → 7.52 ms/frame**, a **24.7%** reduction. The corresponding
p95 was **14.74 → 13.73 ms**, and p99 **16.98 → 15.71 ms**. The desktop's rolling
two-second metric was sampled about every 0.5 seconds throughout playback,
including warmup; the table reports the highest observed samples, not a guarantee
of the absolute maximum between samples. There was no material processing-time
regression in these runs.

Active processing excludes video decode and playback pacing. Actual delivered
throughput remained **26.86 → 26.89 fps**, constrained by the existing file-source
cadence. These measured desktop gains are workload-specific and do **not** show
that the intermittent 26 ms slowdown has been fixed. The native runs cover this
25-second slice, not the entire recording or a live capture/OBS/Discord workload.

### Reproduction and receipts

The pre-change detector is available at commit `193b7a4`. From the repository
root, these commands create a baseline snapshot and repeat the exact-recognition
and crop-extraction comparison (use a new output directory for a new run):

```bat
.venv\Scripts\python.exe -c "from pathlib import Path; import subprocess; p=Path('.desktop-validation/glyph-baseline.py'); p.parent.mkdir(exist_ok=True); p.write_bytes(subprocess.check_output(['git','show','193b7a4:ddrcv/score/glyph_detector.py']))"
.venv\Scripts\python.exe -B tools\validate_glyph_optimization.py --baseline .desktop-validation\glyph-baseline.py --video D:\TBD5\2025-03-27_15-52-48_trimmed.mkv --out .desktop-validation\glyph-recheck
.venv\Scripts\python.exe -B tools\run_results_tests.py --video apps\scripts\2025-03-27_15-52-48.mkv
```

Local measurement receipts are in `.desktop-validation/glyph-optimization/`:
`parity-and-speed/report.json`, `native-summary.json`, and each
`native-<trial>-<variant>/report.json` and `frames.json`. The local
`native_trial.py`/`run_native_matrix.py` probes preserve the actual tray-host
comparison procedure and machine-specific configuration. These probes and raw
artifacts are ignored by Git; the crop comparison tool and regression tests are
part of the repository. No dependency or operator setting was added.

Fully **Exit application** from the desktop/tray and relaunch to load the change.
Closing and reopening just the panel keeps the existing Python backend running.
