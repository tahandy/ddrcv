# Tournament desktop

The Windows tournament app uses a persistent Python tray backend and a separate
pywebview/WebView2 window. Closing the window saves its draft and releases its UI
processes. Capture, recognition, score publishing, OBS automation, and an owned
score renderer continue. Reopen through the tray or launch the app again.

## Setup and launch

1. Use 64-bit Windows Python 3.12 and the Microsoft Edge WebView2 Runtime.
2. Run `setup_desktop.bat` in this checkout. It creates/reuses this checkout's
   `.venv`, installs the dedicated requirements, and checks WebView2 and templates.
3. Double-click **launch_desktop.vbs**. It launches without a console window.
4. Open a shared JSON configuration, or configure the source and integrations.
   Click **Start** when ready. Restoring a configuration never opens capture.

If Windows policy disables VBScript, a shortcut to
`.venv\Scripts\pythonw.exe -B -m ddrcv.desktop` with its **Start in** directory set
to this checkout provides the same console-free launch. `python.exe -B -m ddrcv.desktop` is useful for troubleshooting.

Desktop settings live in `%LOCALAPPDATA%\DDRCV\tournament`, independently of the
workbench. `--data-dir PATH` selects isolated settings for testing. One backend
owns each data directory; a repeated launch opens its existing panel. A repeated
launch with `--config` does not replace an already running instance's config.

The tray offers Open panel and confirmed Exit application. Window close/Alt+F4
only closes the panel; minimizing retains WebView2 but suspends status polling.
Exit stops the backend and only the renderer process it launched. It does not
close OBS or terminate another driver's publisher.

## Shared CLI configuration

The existing launchers and `--config`, `--choose-camera`, `--video`, `--image`,
`--resize-to-720p`, `--score-mode`, and `--debug` arguments are preserved. Both TBD5 entry points
use the same shared runtime as the desktop. For example:

```bat
.venv\Scripts\python.exe -B -m ddrcv.apps.driver_ddr_tbd5 --config C:\tournament\event.json
```

Existing partial JSON overrides still work. Ingest selects exactly one source
(`simple`, `rtsp`, `video`, or `image`). GUI Save/Save As writes the same JSON,
retains fields not exposed by the form, and makes known filesystem paths
absolute. Relative paths in existing configs retain the CLI's working-directory
semantics; launch from this checkout for the same interpretation.

The score mode sets `score_filter.max_per_frame` to `12` for EX or `null` for
Money. Existing custom positive values are preserved and shown as Custom.
A mode-only profile may use `score_mode: "ex"` or `"money"`; an explicit
`score_filter.max_per_frame` takes precedence so custom filters and GUI edits
survive round trips. The CLI `--score-mode` flag explicitly selects its preset.
Custom positive filters use EX results crops. Legacy defaults remain EX; the separate rehearsal workbench still defaults to
Money. Live capture remains fixed at 1280×720. Optional resizing applies only to
full 16:9 files.

When results are enabled, both CLI and desktop use the durable RapidOCR results
service described in [Results publishing](results_publishing.md). It starts only
with capture, publishes delivery status even while frames are unavailable, and
keeps its outbox alive across camera switches. A switch finalizes retained old
source evidence and resets confirmation for the new source. Legacy
`results.screenshot_directory` and `processing_delay` map to `outbox_directory`
and `settling_seconds` when the new keys are absent; screenshot naming follows
the durable event-directory format. CLI additionally inherits the workbench's
local results settings before applying its explicit JSON overrides. Desktop
profiles retain their own results settings.

Two optional sections extend the driver JSON. Existing files leave both disabled:

```json
{
  "obs": {
    "enabled": false,
    "automation": false,
    "host": "localhost",
    "port": 4455,
    "password": "",
    "scene_map": null
  },
  "renderer": {
    "enabled": false,
    "path": "C:/code/ddr_score_render"
  }
}
```

`obs.enabled` connects on Start; `obs.automation` requests validated automatic
scene switching. A null scene map uses the existing default mapping. An explicit
map can assign state names to scenes or null to hold. Manual scene switching
pauses automation; enabling automation reconciles to the latest confirmed state.
`renderer.enabled` launches the existing `apps.tbd5` renderer using the publisher
address and its managed stop-file interface. These settings work in CLI mode too.
Desktop integration buttons control the currently applied configuration; apply
edited host, scene, or path settings before using them.

Open/edit/save affects the draft. Apply validates source and template loading
before replacing the active runtime; Apply and Restart asks before resetting an
active session. Start uses the current draft when stopped. Drafts survive closing
and reopening the panel. If a draft cannot be saved (invalid JSON or an unavailable backend), closing
asks whether to discard the latest edits rather than trapping the window. Stop leaves the last frame and scores visible, with
freshness indicators. End-of-file stops the runtime and owned integrations.

Credentials are masked in forms/advanced JSON and redacted from application logs.
`[unchanged secret]` preserves an existing secret; an empty string clears it.
Saved profiles and the local draft **contain actual credentials**, so keep these
local. The local control API binds only to loopback and requires a session token;
its token and endpoint metadata are kept in the local settings directory. This
is separate from the unchanged public score WebSocket.

## Operation and recovery

The panel uses compact native graphite styling: Segoe UI, neutral gray surfaces,
blue focus/selection accents, and a player table with explicit presence and read
age. Status remains readable through text as well as color. Profile Open/Save
actions and runtime controls are available on every tab.

Status and configuration share the first tab. **OBS** and **Renderer** have their
own tabs; switching tabs keeps the draft and active session intact. The Start,
Stop, and Apply controls remain available above every tab.

To change cameras during a run, select the camera index (or an RTSP source) and
click **Switch camera**. The app checks the new source for a valid 1280×720 frame
for up to ten seconds while the previous capture continues. Once ready, it
releases the previous capture and resets state/score confirmation for the new
source. The publisher, OBS connection/manual override, renderer, and pending
result delivery stay alive. Any displayed snapshot is cleared at the handoff.
If the new source cannot produce a valid frame, the previous camera and its
score history remain active. Stop cancels a pending switch.

Switch camera applies only the source settings; unrelated draft edits remain
pending, including integration settings. File changes and settings changes for
the same camera use Apply and Restart. Camera handoff briefly opens the two
sources concurrently. If a capture driver cannot support this, the old source
is retained on failure; use Stop/Start for that hardware. A native capture call
that remains blocked during cleanup prevents further handoffs until it exits.

- Status shows confirmed/raw state, presence, accepted scores and read age,
  capture freshness, recognition rate, publisher subscribers, and integration
  health. After one second without a frame, capture is marked stale. A stale
  capture does not turn the last accepted score into a new reading.
- **View stream** retrieves one clean timestamped frame; Refresh retrieves
  another. No preview is encoded between requests and there is no second capture
  connection or continuous stream endpoint.
- Recent logs and raw-score rejection reasons are expandable. Backend logs rotate
  at 1 MiB with two backups. Panel and renderer diagnostics are in `panel.log`
  and `renderer.log` in the same settings directory.
- Capture sources retain their retry behavior; retry waits can be interrupted on
  Stop. A blocked native capture call may take longer to release. A new session
  is refused while a prior worker is still cleaning up.
- OBS/renderer failures do not stop recognition. Check their status separately:
  a renderer process or subscriber count alone does not establish visible output.
- If the panel crashes, reopen it from the tray. No scores reset. If the backend
  exits, launch again and explicitly Start; it does not silently resume hardware
  or scene automation.
- Port conflicts identify the occupied publisher address. Choose another port or
  stop the other driver yourself. The app never takes over another process.

## Validation

Run the focused regressions from this checkout:

```bat
.venv\Scripts\python.exe -B -m unittest discover -s tests -p "test_tournament*.py" -v
.venv\Scripts\python.exe -B -m unittest discover -s tests -p "test_workbench.py" -v
.venv\Scripts\python.exe -B -m unittest discover -s tests -p "test_monitored_regions.py" -v
.venv\Scripts\python.exe -B -m unittest discover -s tests -p "test_desktop.py" -v
```

The optional native acceptance/resource probe needs `psutil` in the validation
environment. It launches the actual tray/window modules, exercises window
lifecycle through pywebview's own methods, and writes isolated artifacts:

```bat
.venv\Scripts\python.exe -m pip install psutil
.venv\Scripts\python.exe -B tools\validate_desktop_windows.py --seconds 8
```

It compares the shared CLI runtime, visible/minimized/closed panel, and repeated
reopening on an identical 30 fps file made from a real gameplay fixture. No
hardware, real OBS server, or external messages are involved. Results are in
`.desktop-validation/windows/report.json`. See
[the validation report](tournament_desktop_validation.md) for measured results
and the remaining live rehearsal checks.
