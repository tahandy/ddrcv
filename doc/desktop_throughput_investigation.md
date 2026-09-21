# Desktop gameplay throughput investigation — September 20, 2026

The exact file `D:\TBD5\2025-03-27_15-52-48_trimmed.mkv` was measured: 1280×720,
30 fps, 9,676 frames. The saved operator profile uses EX scores with login/splash
name recognition and results parsing enabled. No existing desktop instance was
running when the inspection began, so the reported slow session could not be
sampled directly.

## Measured results

The full-app runs used the actual Windows tray host, native WebView2 panel,
background recognition thread, and external renderer. Each used separate state,
publisher port, screenshot folder and outbox. Discord publishing and OBS control
were disabled; no external messages or scene changes were made. These differences
from the saved operator setup remain limitations of the comparison.

| Run | Video segment | Gameplay frames | Mean active ms | p95 ms | Delivered fps | Highest sampled UI average |
|---|---|---:|---:|---:|---:|---:|
| Full desktop + renderer, no stage wrappers | 20–80 s | 1,800 | 6.15 | 12.94 | 28.05 | 11.17 ms |
| Full desktop + renderer, no stage wrappers | 110–127 s, gameplay only | 454 | 6.40 | 12.17 | 28.01 | 8.70 ms |
| Full desktop + renderer, stage profiling | 20–80 s | 1,800 | 9.31 | 14.44 | 27.11 | 11.87 ms |
| Earlier harness, native panel, stage profiling | 20–40 s | 600 | 7.46 | 14.17 | 27.83 | Not sampled |

The 110–127 s interval transitions out of gameplay before its end; the table
excludes those non-gameplay frames. Highest UI averages are sampled at about
0.5-second intervals and include the trial's warmup. “No stage wrappers” still
records frame completions and reads status; it does not mean zero measurement
overhead. Python was 3.12.6, OpenCV 4.10.0 with one OpenCV worker, matching the
earlier benchmark environment. The machine was plugged in.

## What explains the apparent disconnect

The UI's processing time is a **rolling two-second arithmetic mean of active
frame work**, not a complete-song mean. Its capacity is 1000 divided by that mean.
26 ms therefore means about 38.5 fps active-work capacity; it does not mean the
file is being delivered at 38.5 fps.

In `TournamentRuntime.run`, the active timer starts **after** `get_frame()`.
It includes recognition, results/name submissions, and publication/integration
handoff. It excludes file decoding, playback sleep, native rendering and the
background OCR worker's own execution. Those background activities can still
compete for CPU. The desktop and workbench have different timing boundaries;
older workbench timings included source-read work and should not be equated with
this desktop metric.

Actual file delivery includes decoding and Windows scheduling/pacing. The current
main unprofiled run spent an additional 29.34 ms per frame in combined decode and
pacing, giving roughly 35.5 ms total between frames, or 28 fps. That wait is not
an extra 29 ms of recognition work.

The earlier September 17 data was never uniformly 5–9 ms. The retained comparison
already contains a 20.67 ms whole-trial average for the optimized native-panel run
and a 23.10 ms trial with the original recognizer plus renderer. Worst two-second
averages were about 24.98 ms for the optimized recognizer and 26.76 ms for the
original. Those slower windows were understated by focusing on the fast headline
numbers. The user's 26 ms observation is plausible and should not be dismissed.
See [the previous measurements](rehearsal_performance.md#repeated-desktop-results).

![Earlier slow window and current full-app run](../.desktop-validation/throughput-investigation/timing-comparison.png)

In the current profiled full-host trial, mean active work was 9.31 ms:
score extraction 8.82 ms, including glyph matching 6.87 ms; state recognition
0.28 ms; publication 0.11 ms. These are nested measurements, not additive columns.
The smaller panel-only probe measured lock acquisition at 0.006 ms/frame.
The unprofiled main run itself shifted from roughly 9–11 ms displayed averages
to roughly 4.4–4.8 ms without changing settings. This is visible in the trace;
these measurements do not identify what caused that shift.
The profiling and unprofiled runs occurred sequentially, so their difference
cannot be attributed entirely to profiler overhead or entirely to system load.

**A sustained 26 ms UI average was not reproduced today.** The precise cause of
that particular slowdown remains unproven. The tests do not establish a constant
6 ms guarantee, nor do they rule out environmental or integration-related costs
in the operator's original session. No recognition or pacing behavior was changed.

## Capture the next slow episode without changing the app

From the repository, while gameplay is running:

```powershell
.\.venv\Scripts\python.exe tools\record_desktop_timing.py --seconds 60
```

This reads only the authenticated local status endpoint. It leaves capture,
settings and integrations untouched and saves a uniquely named JSON file under
`.desktop-validation`. The report includes screen state, frame sequence,
throughput, single-frame processing time, the same rolling average shown in the
UI, and whether OBS/renderer are connected. Credentials, session tokens and
results history are excluded. Its summary describes **samples of the displayed
average**, not individual-frame percentiles. Missing/stopped sessions and request
failures are recorded instead of being represented as successful measurements.

The recorder was exercised against the real native test session: its captured
gameplay UI averages ranged 4.80–8.40 ms. Allowlist and gameplay-only summary
checks passed. Existing regression code was not changed by this investigation.

## Local evidence

The ignored `.desktop-validation/throughput-investigation/` directory contains:

- `inspection.json`: input/profile characteristics, excluding credentials.
- `native-renderer-unprofiled/`, `native-ending-unprofiled/`: per-frame and sampled UI timing.
- `native-renderer-profile/`, `trim-panel-profile/`: stage timing and frame traces.
- `live-recorder-check-active.json`: read-only recorder validation.
- `native_trial.py`: isolated full-host measurement harness.
- `plot_timing.py`, `timing-comparison.png`: reproducible figure.

Resource readings named `backend_cpu_percent` and `backend_threads` in the first
profiled full-host run sampled Windows' Python launcher rather than the actual
backend and must not be used. The later unprofiled runs use the backend PID from
instance metadata. Frame timing and stage measurements were taken inside the
actual runtime and are unaffected by that resource-sampler correction.

## September 21 follow-up: 20.8 ms screenshot

The operator screenshot shows 20.8 ms/frame, 24.5 fps delivered, EX scores
525/531, and 1,566 processed frames of the trimmed recording. The operator
confirmed a full application exit/relaunch after the glyph optimization. The
desktop had exited before live sampling, so no timing samples from that slow
session were available.

A separate `ddrcv.workbench` process remained running from September 20 at
21:12, listening on ports 5002 and 9000. Its measured CPU use was about 1% over
three seconds. This accounts for the desktop log's port-9000 bind failures; it
does not establish the cause of the slow processing. The process was left alone.

A new isolated, stage-profiled native desktop + renderer replay started at the
beginning of the video and ran through 75 seconds, including normal splash/name
recognition startup. Discord delivery and OBS control were disabled as before.
Whole-replay active time averaged 5.91 ms/frame; the 1,889 gameplay frames averaged
6.73 ms, with p95 13.29 ms. The highest sampled two-second gameplay average was
11.32 ms. At 50–55 seconds, near the screenshot's approximate source position,
the average was 9.29 ms; glyph matching accounted for 7.10 ms and publication
0.14 ms (nested stage timings). Delivered gameplay throughput was 26.62 fps.

This run did not reproduce 20.8 ms. Starting partway through the recording is
therefore not sufficient to explain the difference. The slow-session cause
remains unresolved; the port conflict and timing issue must not be conflated.
The diagnostic app and renderer exited after the run. Receipts are under
`.desktop-validation/glyph-optimization/sept21-from-start-profile/`.

## Resolved: Windows recognition-thread power policy

Later on September 21, the slow session was measured directly after the operator
launched `C:\code\ddrcv\launch_desktop.vbs`. The optimized matcher, checkout,
Python installation, normal process priority, and unrestricted process affinity
were confirmed. Its displayed average reached 23.52 ms. Separate diagnostic
launches using `pythonw`, Windows Script Host, copied operator environment, OBS
connection settings, and copied result history still ran at approximately 6–8 ms.
The configuration differences did not explain the gap.

The machine is an Intel i9-14900HX with both performance and efficiency cores.
Changing only the live recognition thread's affinity to performance cores reduced
its median displayed time from 19.71 to 13.24 ms. Restoring the original affinity
raised it to 26.24 ms; restricting it again reduced it to 14.27 ms. All affinity
changes were then undone. A follow-up test of thread power policy also produced
reversible reductions, without restricting affinity.

The retained fix explicitly requests **Windows HighQoS for the desktop recognition
worker**. Windows otherwise chooses a power/performance policy using factors such
as window visibility, process ancestry, and scheduling heuristics. Our backend is
a tray process with its visible panel in a separate child process. The exact
heuristic responsible for the launch-to-launch difference was not traced, but the
thread-policy effect was verified directly in the operator's slow application.
See Microsoft's [Quality of Service documentation](https://learn.microsoft.com/en-us/windows/win32/procthread/quality-of-service)
and [SetThreadInformation examples](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-setthreadinformation).

### Verification in the operator's VBS launch

After a full exit/relaunch with the fix, the same running recognition thread was
alternated between HighQoS and its previous system-managed policy. No recognition,
integration, profile, or affinity settings changed during this comparison.

| Thread policy, in order | Median displayed ms/frame | Observed range |
| --- | ---: | ---: |
| HighQoS | 6.74 | 3.54–8.06 |
| System-managed | 19.26 | 14.49–24.33 |
| HighQoS | 8.07 | 6.12–9.23 |
| System-managed | 19.21 | 13.32–22.70 |
| HighQoS | 6.99 | 6.28–9.16 |

Each phase lasted eight seconds. These are samples of the UI's rolling two-second
average, collected about every 0.5 seconds; the first three seconds after each
policy change were excluded. They are **not whole-run frame means or frame
percentiles**. All retained samples were gameplay, spanning processed frames
546–1535. The image content advanced between phases, but returning to the former
policy twice reproduced the slower behavior, and restoring HighQoS reversed it
each time. The operator session was left with HighQoS active and normal affinity.

### Implementation and validation

`ddrcv/apps/thread_qos.py` uses the standard Windows thread power-policy API to
disable execution-speed throttling on the recognition worker only. It does not
raise process/thread priority, pin CPU cores, or change the system power plan.
The exact previous thread policy is restored when the worker exits, including on
errors. Non-Windows and CLI operation are unchanged, and unavailable APIs fall
back to the existing behavior. No dependency or operator setting was added.
The existing backend log confirms activation with
`Desktop recognition thread: Windows HighQoS enabled`.

The focused regression runner passed **248 tests, no skips**. Tests cover policy
preservation/restoration, exceptional exits, unsupported platforms/APIs, and
failure fallback. A native Windows API smoke test also passed. The earlier glyph
recognition parity remains applicable: this fix changes scheduling policy only.

Local receipts are in `.desktop-validation/launch-discrepancy/`, particularly
`operator-live/`, `affinity-trial.json`, `qos-trial.json`,
`qos-gameplay-trial.json`, `verify-vbs-fix.log`, and `regression.log`.
Diagnostic launches used isolated storage, disabled Discord delivery, and
disabled OBS scene automation. The final comparison observed the operator's
own session and temporarily changed only its recognition thread's power policy.
