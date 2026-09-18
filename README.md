# DDRCV

Read DDR World gameplay scores and publish them to the tournament score renderer
and OBS scene controller.

**New operators:** follow the [setup and operator walkthrough](doc/operator_walkthrough.md)
from installation through a complete rehearsal. Keep the
[operator quick reference](doc/operator_reference.md) nearby for event controls,
Results recovery, and troubleshooting.

For a training session or handoff, use the [operator slide deck](doc/slides/README.md)
(editable PowerPoint, PDF, and speaker notes).

On Windows with Python 3.12:

1. Run **setup_workbench.bat** once.
2. Run **launch_workbench.bat** to open http://localhost:5002/.
3. Open a local video or image and inspect recognition before connecting capture
   hardware. New rehearsal sessions default to Money score.

The [rehearsal and tournament handoff guide](doc/tournament_handoff.md) covers
recorded footage, diagnostics, the sibling `ddr_score_render` checkout, optional
OBS integration, live capture, and the maintained TBD5 CLI.

Optional persistent, thread-safe crop OCR is documented in
[ddrcv/ocr/README.md](ddrcv/ocr/README.md), including installation and offline use.

For event operation, the [tournament desktop app](doc/tournament_desktop.md) adds
a persistent tray backend, a disposable WebView2 panel, shared CLI configs, and
on-demand frame snapshots. Run `setup_desktop.bat`, then `launch_desktop.vbs`.

Automatic name/large-score capture, stable screenshots, and background Discord
publishing are documented in [Results publishing](doc/results_publishing.md).
