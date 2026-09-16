# DDRCV

Read DDR World gameplay scores and publish them to the tournament score renderer
and OBS scene controller.

On Windows with Python 3.12:

1. Run **setup_workbench.bat** once.
2. Run **launch_workbench.bat** to open http://localhost:5002/.
3. Open a local video or image and inspect recognition before connecting capture
   hardware. New rehearsal sessions default to Money score.

The [rehearsal and tournament handoff guide](doc/tournament_handoff.md) covers
recorded footage, diagnostics, the sibling `ddr_score_render` checkout, optional
OBS integration, live capture, and the maintained TBD5 CLI.
