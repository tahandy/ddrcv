# DDRCV

Read DDR World gameplay scores and publish them to the tournament score renderer
and OBS scene controller.

**Example OBS overlay:** see [examples/browser_overlay](examples/browser_overlay/README.md)
for a standalone browser source demonstrating P1/P2 names and live scores from
the WebSocket feed.

**Example OBS scene switching:** [create a demo scene collection](examples/obs_scene_switching/README.md)
and drive Lobby, Gameplay, and Results scenes from simulated or real DDRCV state.

**Building a custom renderer?** See the [streaming state specification](doc/streaming_state.md)
for the WebSocket connection, JSON fields, score/name lifetimes, and client examples.

**New operators:** follow the [setup and operator walkthrough](doc/operator_walkthrough.md)
from installation through a complete rehearsal. Keep the
[operator quick reference](doc/operator_reference.md) nearby for event controls,
Results recovery, and troubleshooting.

For a training session or handoff, use the [operator slide deck](doc/slides/README.md)
(editable PowerPoint, PDF, and speaker notes).

On **64-bit Windows**, download/extract this repository into a writable folder,
then double-click **setup_desktop.bat**. Choose local Python installation,
select a detected Python, or enter your own path. You do not need Python installed
first: option **1** downloads local Python 3.12. Setup creates `.venv`, installs the locked
application dependencies, and provisions/checks OCR and WebView2. Internet is
needed for the first setup. When it finishes, double-click **launch_desktop.vbs**.

For recorded-footage rehearsal in a browser, run **setup_workbench.bat**, then
**launch_workbench.bat** (http://localhost:5002/). New sessions default to Money
score. Both applications share this checkout's environment.
Closing the last Workbench tab shuts it down and releases the score feed port
after a short grace period. Refreshing the page or keeping another Workbench tab
open keeps the session running. OBS video views do not keep the Workbench alive.

Already have Python? Pass the full path to **64-bit CPython 3.12**:

```bat
setup_desktop.bat -Python "C:\Users\you\AppData\Local\Programs\Python\Python312\python.exe"
```

See the [installation guide](doc/installation.md) for existing environments,
manual pip/uv installation, updates, and troubleshooting.

**Record camera footage:** double-click
[ffmpeg_record_gui.bat](apps/scripts/ffmpeg_record_gui.bat) to record a camera or
capture device with optional audio to timestamped `.mkv` files. The lightweight
GUI uses Python/Tkinter and FFmpeg with no additional pip packages, and includes
an FFmpeg download link. See the [recorder guide](doc/ffmpeg_record_gui.md) for setup
and controls.

The [rehearsal and tournament handoff guide](doc/tournament_handoff.md) covers
recorded footage, diagnostics, the sibling `ddr_score_render` checkout, optional
OBS integration, live capture, and the maintained DDR World CLI.

Optional persistent, thread-safe crop OCR is documented in
[ddrcv/ocr/README.md](ddrcv/ocr/README.md), including installation and offline use.

For event operation, the [tournament desktop app](doc/tournament_desktop.md) adds
a persistent tray backend, a disposable WebView2 panel, shared CLI configs, and
on-demand frame snapshots. Run `setup_desktop.bat`, then `launch_desktop.vbs`.

Automatic name/large-score capture, stable screenshots, and background Discord
publishing are documented in [Results publishing](doc/results_publishing.md).
