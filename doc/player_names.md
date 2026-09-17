# Login and splash player names

The maintained CLI, desktop runtime, and workbench can publish names confirmed
from login profiles and the song splash. This uses the persistent CPU RapidOCR recognizer; no song
database, difficulty recognition, EasyOCR, or results capture is required.

Run `setup_desktop.bat` or `setup_workbench.bat` in this checkout. Both install
RapidOCR and ONNX Runtime, provision the pinned model in the normal local cache,
and require an actual splash inference test to pass. To verify an existing
installation without downloads:

```bat
.venv\Scripts\python.exe -B -m ddrcv.ocr.check
```

## Enable

Add this section to the shared desktop/CLI JSON profile, load it in the desktop
app and start capture, or pass the profile with the driver's `--config` option:

```json
{
  "player_names": {
    "enabled": true,
    "confidence": 0.8,
    "sample_hz": 5,
    "min_frames": 3,
    "confirmation_seconds": 0.4,
    "max_gap": 0.75,
    "ocr": {"allow_download": false, "num_threads": 2}
  }
}
```

For the workbench, put the same `player_names` section in its local
`settings.json` (normally `.workbench/settings.json`) while it is stopped, then
restart it. Preserve the other existing settings. Workbench configuration changes take effect on the next runtime start. The desktop
name switch applies immediately without restarting capture. Recognition defaults to disabled and is
independent of the Results panel's **Parse player names** option.

## Monitoring

The workbench Status table shows the confirmed **Parsed name** for each player.
The Player name recognition section shows model readiness or errors, evidence
screen, worker activity, and pending/replaced samples. These fields keep updating
when playback is paused; an em dash means no confirmed name.

The desktop **Status & configuration** tab shows each parsed name under its player
label, alongside presence and accepted score. Its name-recognition status reports
initialization and errors. Use **Read names on login/song splash**
in Configuration; the switch applies immediately, including during capture. This setting is separate from Results
name parsing. Both interfaces display the published names, including resets;
neither starts inference from the status poll.

Browser acceptance is reproducible with installed Playwright and Edge:

```bat
.venv\Scripts\python.exe -B tools\validate_player_names_ui.py
```

The default recording is `apps/scripts/2025-03-19_16-47-45.mkv` (override with
`--video` for the same recording elsewhere). The check exercises actual workbench
login recognition, then controlled status responses for partial names, errors,
paused updates, safe text rendering, and desktop configuration persistence.
Screenshots and the report are saved in `.workbench/player-names-ui`.
The September 17 run confirmed ZVIDUN / EVILDAVE with no browser errors;
the accompanying regression run passed all 188 tests with no skips.

## Published contract

Every runtime/workbench snapshot includes this additive field:

```json
"player_names": {"p1": "ZERO.", "p2": null}
```

Values preserve spelling, case, and punctuation. Null means absent or
unconfirmed. The existing `players` booleans carry presence measured at the splash;
login has no independent presence detector, so each side needs its own name-label
evidence. Login names remain available through subsequent song selection, then
clear at the splash for fresh per-song confirmation. If the splash is missed,
entering gameplay/results clears login names rather than using them as a fallback.
Splash names remain available through gameplay, temporary unknown states, and
that song's results. They clear at the next song boundary, a new login, total
results, or source/session reset. Names from saved results are never
silently substituted. OBS receives the enriched integration snapshot, but this
change does not map names to OBS text sources or modify the score renderer.

Runtime and workbench status include `player_name_status`: readiness/error,
worker busy state, pending sample count, replaced-sample count, and the evidence
screen (`login` or `song_splash`). Missing
dependencies, model problems, and inference errors leave unconfirmed names null
and do not stop scoring. In the desktop, switch names off and on to retry initialization without restarting
capture. In the workbench, restart capture after fixing the error.

## Timing and lifetime

Only matching raw and confirmed login/splash states supply evidence. The driver copies
the two small 720p name bands at most five times per second. One background worker
loads the model, prepares crops, and performs batched inference. There is at most
one active read and one pending sample; new samples replace pending work.
Neither inference nor worker joins occur in the per-frame path.

Login bands are `(212,190,338,50)` and `(646,190,338,50)` in `(x,y,width,height)`
coordinates. They contain the label and name line. Before accepting a login name,
the worker must read `DANCER NAME` (spacing ignored) above it at the configured
confidence threshold. This rejects the league summary and card-prompt pages,
which share the existing `login` state detector but do not show player names.
Label OCR uses the original color band; name OCR uses the existing white-text
crop preparation. A confirmed login name latches for that login episode.

Each player needs three identical accepted readings over at least 0.4
seconds. Missing/conflicting reads, interrupted name-screen recognition, and evidence
gaps above 0.75 seconds reset unconfirmed evidence. Duplicate timestamps add no
votes. Confirmed names latch for the song and stop consuming OCR work. An
uninterrupted final splash read can finish during gameplay; a final login read
can finish during selection. Evidence never combines login and splash samples. Generation and run
checks reject old work after resets, source changes, interruptions, and shutdown.
Shutdown waits at most one second for the name worker; an outstanding worker is
reported by the desktop's existing cleanup check before allowing restart.

## Regression and recording validation

The regression runner now requires a provisioned real OCR model before running;
missing OCR cannot become a successful run with all model tests skipped:

```bat
.venv\Scripts\python.exe -B tools\run_results_tests.py --video apps\scripts\2025-03-27_15-52-48.mkv
.venv\Scripts\python.exe -B tools\replay_player_names.py --video apps\scripts\2025-03-27_15-52-48.mkv --expect XETA DANOOCT1
.venv\Scripts\python.exe -B tools\replay_player_names.py --video apps\scripts\2025-03-19_16-47-45.mkv --screen login --start 3 --seconds 10 --expect ZVIDUN EVILDAVE --output .workbench/login-names-validation.json
```

The replay automatically locates a splash (or login with `--screen login`), processes every frame of a nine-second
window through the maintained driver, and compares names enabled/disabled. It
records confirmation time, synchronous submission cost, and recognition timing
in `.workbench/player-names-validation.json`. It does not contact OBS or Discord.
Use `--start`, `--seconds`, and `--output` for another interval or report. Login
confirmation timing starts at the first `login` frame, which can be a league or
card page preceding the name-bearing profile.
Stored fixtures and local recordings cover only a small set of names; confidence
and repeated agreement do not prove correctness for every capture/layout.

### Measured acceptance, September 17, 2026

The destination checkout's Windows Python 3.12 environment has RapidOCR 3.9.2,
ONNX Runtime 1.30.0, and the provisioned default-cache model. Its desktop readiness
check passes, including offline real inference. Both baseline and enabled runs
processed all 270 frames in each nine-second source interval:

Initial splash regression run: **182 tests passed, no skips**, including real-model OCR,
results, tournament, desktop, workbench, and monitored-region suites. An earlier
run encountered a Windows access-denied error replacing a temporary `desk.json`
in an existing desktop test; that test passed immediately in isolation and the
subsequent full run passed without a persistence-code change.

| Recording / interval | Confirmed names | Time after first splash | Submit p95 / maximum |
| --- | --- | --- | --- |
| `2025-03-27_15-52-48.mkv`, 139.5–148.5 s | XETA / DANOOCT1 | 0.618 s | 0.012 / 0.040 ms |
| `2025-03-27_15-50-18.mkv`, 5.5–14.5 s | XETA / DANOOCT1 | 0.625 s | 0.014 / 0.043 ms |

Submit measurements cover the synchronous name-service call, including sampled
crop copies; they exclude worker inference. Neither run replaced pending samples
or reported a worker error. The enabled/disabled recognition medians were
4.164/4.232 ms and 4.290/4.274 ms respectively; this small comparison supports low
overhead, not a speedup claim. Full local reports are
`.workbench/player-names-march27.json` and
`.workbench/player-names-march27-second.json`.

Offline image assertions additionally cover `ZERO.`, `WOLF.`, `PLAYER2`, and
single-player `N.NATURE`. Stall tests cover continued gameplay and source switching,
late publication without frames, bounded pending work/shutdown, and stale outputs
and errors after reset. Live capture and additional player names remain untested.

### Login extension acceptance

**188 regression tests passed, no skips**, including two real profile screenshots,
league/card negative fixtures, independent P1/P2 confirmation, retention through
selection, fresh splash evidence, and rejection of late login work.

The actual driver replay of `2025-03-19_16-47-45.mkv`, 3–13 seconds, processed all
300 frames and confirmed ZVIDUN / EVILDAVE. It emitted only the correct partial
pair followed by the correct complete pair; league text was never published as
a name. The first name arrived 3.493 seconds after the first login frame, and both
were confirmed at 3.673 seconds. Those timings include the preceding league page
before the name-bearing profile appears. Driver-side name submission measured
0.010 ms median, 0.031 ms p95, and 0.217 ms maximum; all label/name inference ran
on the worker. Report: `.workbench/login-names-validation.json`.
