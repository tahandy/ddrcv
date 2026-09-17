# Tournament desktop validation

Validated on Windows Python 3.12.6, pywebview 6.2.1 and installed WebView2,
2026-09-17, in `codex/tournament-desktop` based on local `dia-del-ritmo`
commit `ec80c67`. The validation environment is isolated in this worktree.

## Automated checks

- 36 tournament/state/score/integration tests passed.
- 24 workbench tests passed.
- 5 monitored-region tests passed.
- 32 desktop tests passed: config compatibility, drafts, secrets, control API,
  source recovery, snapshots, results processing, runtime/instance ownership,
  invalid configurations, duplicate Start, and optional integration failures.
  Live handoff tests cover uninterrupted old-source recognition during probing,
  retained publisher/integration workers, state reset on commit, failed/invalid
  frame rollback, cancelled probes (including serialized desktop Stop), source-only
  config application, reselection, and prevention of lingering capture accumulation.
- Tray exit confirmation runs on a dedicated thread so the tray callback returns
  immediately. Tests cover duplicate clicks, Cancel/retry, Yes, and dialog failure.
  The existing idle instance was gracefully restarted after this fix; native
  Yes/No clicking remains a manual check because desktop automation rejected the
  WSL workspace path.
- Desktop dependency/template/WebView2 checks and `pip check` passed.
- Importing the CLI imports neither pywebview nor pystray.
- Dashboard JavaScript syntax check and headless browser acceptance passed.
  The browser used a real backend with a stubbed native bridge/file picker:
  Start, on-demand snapshot, draft persistence through close/reload, no hidden
  status polling, secret masking, GUI Save As → CLI load, and explicit cancel/discard recovery
  after a failed draft save all passed. Separate OBS/Renderer tabs, keyboard tab
  navigation, preserved drafts across tabs, and camera-switch failure feedback
  passed. The browser camera action is mocked; runtime handoffs use synthetic
  capture sources, without accessing physical cameras.
- The actual WebView2 window passed close/reopen, minimize/restore, three repeated
  reopen cycles, duplicate launch, abrupt UI crash, and clean backend shutdown.
  The lifecycle probe calls the window's own pywebview methods, including the
  actual closing/draft-flush handler. Capture sequence continued across closure
  and UI crash; all observed UI child processes exited.
- The actual sibling score renderer launched, subscribed to published scores,
  and stopped cleanly through its managed stop-file interface.

## Native graphite presentation checks

The restyle passed all 32 desktop regressions and the expanded browser acceptance
probe. No API, backend, configuration-format, or dependency changes were needed.
The existing desktop instance was left untouched; validation used an isolated
backend and local recording.

Actual HTML/CSS screenshots of all three tabs were inspected at 1120×800 and
760×560. Checks cover player presence, accepted/missing scores, stale capture,
pending edits, error messages, disabled controls, visible keyboard focus, and
expanded snapshots. Primary controls fit at the default size; smaller windows
scroll vertically without horizontal overflow. Status includes text labels so
color is supplementary. Screenshots use deterministic status fixtures for the
score/stale/error examples; snapshot images come from the recording.

Artifacts are under `.desktop-validation/graphite/`: `graphite-session-default.png`,
`graphite-obs-default.png`, `graphite-renderer-default.png`, matching minimum-size
views, stale/error views, and snapshot views. `report.json` contains the acceptance
results. Reproduce with `tools/validate_desktop_ui.py --video PATH --out
.desktop-validation/graphite` in the Windows validation environment. Native
window chrome, dialogs, and process lifecycle were unchanged by the restyle.

## Resource measurements

Each condition used the same 30 fps MJPG clip made from the repository's real
`gameplay_2.png` fixture, with recognition warmed up before an eight-second
sample. OBS and the renderer were disabled. This is a bounded desktop-overhead
comparison, not a full tournament-duration or recognition-accuracy evaluation.

Memory is the **sum of process working sets**, in MiB; shared pages can be
counted more than once. CPU uses 100% for one fully occupied logical core, not
100% for the entire machine. Short samples and scheduling noise limit comparisons.

| Condition | Working set (MiB) | CPU (% of one core) | Processed fps | Processes |
|---|---:|---:|---:|---:|
| CLI | 124.3 | 26.81 | 26.29 | 2 |
| Panel open | 589.2 | 31.65 | 26.40 | 10 |
| Panel minimized | 591.7 | 23.06 | 27.27 | 10 |
| Panel closed | 138.2 | 22.29 | 27.05 | 2 |
| Closed after three reopens | 139.1 | 22.61 | 27.10 | 2 |

Closing the panel released approximately 451 MiB of summed working set. The
remaining backend was about 14 MiB above CLI. Three reopens left the closed
backend within 1 MiB of its earlier working set, with no retained UI processes.
Reopening took 1.13, 1.11, 1.13 seconds.
Published state and scores were identical across the measured conditions.
These measurements do not compare WebView2 against a regular browser tab.

Raw results are in `.desktop-validation/windows/report.json`; rerun with:

```bat
.venv\Scripts\python.exe -m pip install psutil
.venv\Scripts\python.exe -B tools\validate_desktop_windows.py --seconds 8
```

Browser checks are reproducible with a local 1280×720 video:

```bat
.venv\Scripts\python.exe -m pip install playwright
.venv\Scripts\python.exe -B tools\validate_desktop_ui.py --video C:\recordings\rehearsal.mkv
```

The browser probe uses installed Microsoft Edge headlessly. Its screenshots and
report are in `.desktop-validation/ui/`. These tools use isolated local profiles,
disable integrations unless explicitly exercised, and send no external messages.

## Remaining live checks

No physical capture card, RTSP endpoint, real OBS server, or Discord delivery was
exercised. Verify switching between the actual capture devices while OBS and
renderer remain connected, including USB bandwidth and DirectShow driver limits.
Resource measurements above precede the tab/live-switch follow-up and were not
repeated for that UI change. Verify real source reconnect behavior, configured scene names, manual
scene override, and visible renderer output during a rehearsal. Native title-bar
and file-dialog interaction was not inspected through the desktop automation
tool because that tool rejected this session's WSL workspace URI. Browser layout
was inspected from generated screenshots; actual native lifecycle was tested
programmatically as described above.

The rehearsal workbench remains separate. Existing CLI entry points/configs and
public score WebSocket messages are preserved. No changes were made in the
original `ddrcv` checkout; sibling renderer source was not edited.
