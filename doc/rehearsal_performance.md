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
