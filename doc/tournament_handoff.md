# Rehearse with recorded footage first

DDRCV reads the numerical score from a full DDR World game screen. The local
workbench uses the **same recognition, confirmation, and score filtering engine
as the DDR World command-line driver**. Start with a recording before connecting the
tournament capture card or OBS.

## 1. Set up and open the panel

Use **64-bit Windows**. Setup installs a local Python 3.12 with Tkinter if
needed; no Python launcher or system installation is required. Keep the
repository's digit and state templates. For the optional score renderer, put its checkout beside
DDRCV:

```text
code/
  ddrcv/
  ddr_score_render/
```

Double-click `setup_workbench.bat`. It creates or reuses `.venv`, installs the
locked rehearsal dependencies, provisions OCR, and checks templates and renderer
assets. Existing local settings are preserved. To supply your own interpreter,
run `setup_workbench.bat -Python "C:\path\to\Python312\python.exe"`.
Incompatible environments must be renamed as a backup before rerunning setup.
Renderer and OBS availability do not block parser-only testing.
`pyproject.toml` declares the dependencies; `uv.lock` pins the complete resolved
set. See [installation](installation.md) for details.

Double-click `launch_workbench.bat`. It opens **http://localhost:5002/** and owns
one score publisher at **ws://127.0.0.1:9000**. Leave its console open while
rehearsing. Closing the last control-panel tab shuts down the workers and owned
renderer after a short grace period and releases the score-feed port. Refreshing
or keeping another control-panel tab open preserves the session; OBS video views
do not keep it alive. The shutdown button and Ctrl+C in the console also stop it.
The server binds only to this computer and runs without Flask's development reloader.

Use **Setup check** whenever something seems missing. It reports dependency,
template, file/resolution, score-port, renderer-asset, and optional OBS checks.
If port 9000 is occupied, stop the old driver or simulator, or choose another
publisher port under integrations. Do not run the old driver alongside the
workbench on the same port. Restart the renderer after changing the port.

## 2. Inspect a recording or image

1. Select **Video**, browse to the local file (or paste its path), and click
   **Open source**. Large recordings are read in place, never uploaded or copied.
2. Use the full, unobstructed **16:9 game window**. Native **1280×720** is preserved.
   For another 16:9 resolution, explicitly enable **Resize to 720p**; the panel
   shows both the original dimensions and transformation. Other aspect ratios
   are rejected. Prepare a clean full-frame recording without borders, crops,
   broadcast overlays, or stretching. Broadcast cropping is outside this version.
3. New sessions default to **Money score** (`max_per_frame: null`). This disables
   the upward-jump limit, so ordinary non-Event-mode recordings can be tested.
   Choose **EX score** for the 12-points-per-game-frame limit. The selected mode
   is prominent in the panel. Changing it clears filter history.
4. Play, pause, step one frame, seek by time or timeline, restart, loop, or choose
   0.25× / 0.5× / 1× / 2×. Playback is silent. Every replay frame is processed;
   a throughput warning means processing cannot sustain the requested speed.
   It slows down rather than skipping frames. End-of-file holds the last frame
   and results with **Ended** status.
5. Compare the raw state, confirmed state, player presence, score crops, digit
   matches, raw readings, published scores, and filter reasons. Green crop boxes
   show where digits were matched. A plausible diagnostic reading is not proof
   the production pipeline accepted it.

Enable **Show monitored regions** above the preview to see the areas actually
checked on that frame. Solid blue marks matching state markers and score reads
used by the production filter. Dashed gray marks state checks that did not
match; dashed amber marks score reads used only for diagnostics. Each score box
states whether the filter accepted or rejected the reading. Overlapping checks
of exactly the same area are grouped, with the matched/checked counts shown.
The classifier stops when it finds a matching state, so later candidates are
not shown as though they were checked. A matching marker still needs temporal
confirmation. The toggle also works on paused frames and images, and affects
only the inspection preview; the OBS browser source stays clean.

The picture streams at up to **30 frames/s**, independently of the diagnostic
text and crop updates (four times per second). Paused pictures remain still;
viewers do not cause additional recognition. Hover over the processing-time
readout to see video decoding and recognition/publication time separately.
The processing budget is 33.3 ms for 30 fps footage at 1×, or 16.7 ms at 2×.
The displayed frame rate measures parsing, not the browser's display rate.

Recognition uses **source timestamps**, independent of playback speed. Pausing
adds no observations. Seeking, restarting, looping, and changing source clear
scores and confirmation history; a paused seek therefore stays **warming up**
until enough subsequent frames have been observed. This also means seeking
straight into gameplay can temporarily lack player-presence evidence normally
obtained on the song splash.

Optional [login and splash player-name publication](player_names.md) uses background OCR
independently of results capture. Login names remain through selection; the splash
confirms names afresh for the song.

**Image** input runs stateless recognition diagnostics. It never creates fake
confirmation votes or accepted scores and does not automatically select an OBS
scene. Use video playback or **Simulate output without footage** to test the
integration. Simulation includes screen state, player presence, and scores;
entering it stops capture/playback and is prominently labeled. Opening a source
exits simulation and resets the parser.

The last source location, score mode, renderer location, publisher port, and OBS
settings live in `.workbench/settings.json`. They are restored on launch; the
source does not autoplay and OBS automation does not enable itself. This local
file can contain an OBS password or authenticated RTSP URL: do not share it.

## 3. Display scores and rehearse OBS

Under **Renderer and OBS**, start the score renderer. Its default repository
location is the sibling `ddr_score_render`; browse or paste another location if
needed. The panel launches the renderer using the same Python environment and
current publisher address. A window appears that can be captured in OBS.

Check **renderer process status** and **publisher connection count** separately.
A running process does not prove correct rendering, and a subscriber could be
another client. Look at the actual renderer window. It displays raw money or EX
numbers, including single-player output, and fits large money scores into the
existing layout. Missing scores remain blank. Use simulation to try 1000000,
absent players, and startup without valid scores. The renderer reconnects if the
publisher restarts. Its log is available under **Recent logs**.

OBS is optional. When ready:

1. Start OBS, enable its WebSocket server, and enter the host, port (usually
   4455), and password in the panel. Choose scene mappings using exact existing
   scene names, then **Connect / validate**. This checks configuration but leaves
   automatic scene changes disabled. No scenes are created automatically.
2. Add a Browser Source with **http://localhost:5002/video**, width **1280**, and
   height **720**. This clean view shows the same frames as the parser, following
   seeks, pauses, loops, and source changes. It contains no controls or diagnostic
   overlays. Preview delivery is throttled independently of parsing; audio is
   not synchronized or supplied. Change the URL if you use another panel port.
3. Enable automation when ready. The default mapping is song select/login/total
   results → `Commentator`, and splash/gameplay/song results → `Gameplay`. Edit
   these to match the event. An empty mapping holds the current scene; `unknown`
   always holds. Save/reconnect after editing the map, then enable automation.
4. Choose a manual scene to pause automation. Resume when ready; the policy
   reconciles the current confirmed state on its next check, even if a transition
   was missed. Pause automation before changing scenes directly inside OBS.

To run the renderer separately, in its repository:

```bat
python -m apps.tbd5 --uri ws://127.0.0.1:9000
```

The score WebSocket retains the existing `state`, `players`, `song`, and `score`
payload, with `p1_score` and `p2_score` inside `score`. A missing player has null;
an active player without an accepted reading has -1. Diagnostic details use the
workbench API, not this feed. Late subscribers receive the latest snapshot.

## 4. Save a problem and identify the failing layer

Pause on a useful frame and click **Save diagnostic snapshot**. The panel reports
the output folder under `.workbench/snapshots/`. It contains the exact frame,
both original score crops, frame number/source timestamp, raw and published
results, digit match details, filter decisions, effective parser settings, and
recent logs. Exports remove credentials from settings and authenticated URLs.
`monitored.png` includes the monitored-region overlay, while `frame.png` remains
unaltered. The diagnostic JSON records every checked region and its outcome.
A snapshot taken while playing is serialized with playback so its frame and
metadata refer to one position. Share that folder, not local settings.

| Symptom | First check |
| --- | --- |
| No frame or frozen live picture | Source path/device, capture ownership, resolution, frame age, recent logs |
| Wrong raw state or digits | Clean full-frame input and score crops; save an example |
| Raw state is right, confirmed state differs | Warming-up status, continuous observations, confirmation settings |
| Raw score differs from published score | Accepted/rejected reason, Money/EX mode, player presence |
| Published score is right, renderer is blank | Publisher port/subscribers, renderer process/log, then the actual window |
| State is right, OBS scene is wrong | Connection check, mapped scene names, automation paused/enabled |
| Replay cannot keep up | Processing time and throughput; reduce playback speed; no frames are discarded |

For the Windows playback timing and preview fixes, including measured before
and after results, see [Rehearsal performance](rehearsal_performance.md).

The default confirmation window is 0.2 seconds, at least three observations,
and 75% agreement. Unknown requires one second; a gap over 0.5 seconds clears
voting evidence. Scores update only when both raw and confirmed state are
gameplay. Lane gutters do not decide whether to extract scores. EX increases
are limited to `12 * max(1, ceil(elapsed_seconds * 60))`, measured since the last
accepted read; missed/rejected frames therefore do not permanently lock the
filter. Money mode removes only that upward bound. Decreases and missing digits
still preserve the last accepted score. A temporary unknown does not erase it;
a confirmed new song resets it. These are plausibility checks, not a guarantee
that every incorrect digit can be rejected.

## 5. Switch to live capture

Leave the renderer and OBS connections in place. Select **Camera**, list the
available devices, enter its index, and open it. Live capture retains only the
latest available frame. The parser, score mode, publisher, and integrations stay
the same. Opening the source clears score and state history. Native 720p is
preferred; explicit normalization follows the same rules as file input.
Existing RTSP inputs remain available by selecting **RTSP** and entering the URL.

On the actual tournament computer, rehearse select → splash → gameplay → song
results → total results, a single-player game, opening capture mid-song, and
manual OBS selection followed by resume. Verify the final scores against the
machine, including a full-combo ending. Check camera disconnect/reconnect and
closing the launcher while the renderer is running. Automated checks use fake
OBS and synthetic media; they do not replace these hardware checks.

## Maintained CLI and automated validation

The workbench is the recommended rehearsal entry point. The CLI remains
available and defaults to **EX score**, unchanged from tournament operation:

```bat
.venv\Scripts\python.exe -m ddrcv.apps.driver_ddr --choose-camera --debug
.venv\Scripts\python.exe -m ddrcv.apps.driver_ddr --video "D:\recordings\game.mkv" --config apps\scripts\driver_config.example.json
.venv\Scripts\python.exe -m ddrcv.apps.driver_ddr --image "D:\recordings\frame.png"
```

For the separate legacy OBS launchers in `apps/scripts`, first copy
`obs_config.example.json` to `obs_config.json` in that directory and edit the
local copy. Machine-specific `obs_config.json` and `driver_config.json` files
are ignored by Git; share the example templates instead. The workbench keeps
its own integration settings under `.workbench/` and does not need this copy.

Use `--resize-to-720p` to opt into full-frame normalization. JSON capture options
use `{"ingest": {"video": {"path": "D:/recordings/game.mkv", "resize_to_720p": false}}}`
(or the `image` key instead of `video`). Set
`score_filter.max_per_frame` to `null` for money footage. The old
`driver_ddr_tbd5` and `driver_ddr_tbd5_v2` modules are compatibility aliases for
`driver_ddr`. Results screenshots/Discord
are configurable in both the CLI and workbench. See [Results publishing](results_publishing.md) for RapidOCR setup, delivery feedback, and retries.

Run all focused validation checks with:

```bat
.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

This workbench supports manual inspection and evidence export. It has no
annotation/expected-result runner, synchronized audio, broadcast cropping,
automatic scene creation, or song-database lookup. Results OCR is configured separately as described in [Results publishing](results_publishing.md).
