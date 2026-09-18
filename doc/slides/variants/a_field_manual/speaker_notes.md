# DDRCV operator guide — Field manual

## 01. Install DDRCV and open the panel

Use the organizer's approved ZIP or checkout. Extract completely to a writable
folder such as C:/Games/ddrcv, outside Program Files. Setup option 1 installs local
x64 CPython 3.12; no existing Python is required. Options 2/3 select a compatible
existing interpreter. Option 4 reuses an environment on subsequent runs. Setup checks
actual OCR and WebView2. Retain error text on failure. Keep .venv and .tools/python
with the installation; run setup again on another computer. The renderer repository
and its assets are separate. Source: doc/installation.md; operator_walkthrough.md §§1–2.
Screenshots in this deck are real forms captured in an isolated stopped session with
example paths, no credentials, and no hardware or external integrations started.

## 02. Select the feed and the score mode

The UI detail is intentionally limited to source and mode controls. Capture
camera: Scan, select the device, verify index. Different computers can assign different
indices. RTSP requires full 1280x720 frames. Local video may explicitly resize full
16:9 footage. Cropped or overlaid broadcasts remain unsuitable. Still-image diagnostics
cannot establish temporal confirmation. EX is the desktop default; browser workbench
defaults to Money. An existing profile can override either. A wrong mode affects live
filtering and results interpretation. Leave Custom filter to a maintainer. Keep default
publisher localhost:9000 for one machine; only one recognition session may own that
port/outbox. Source: operator_walkthrough.md §3; driver_config.py.

## 03. Start, then verify picture, state, and scores

The screenshots show the stopped UI as a control-location reference, not an
observed live session. Start uses the current form. Watch Running and healthy capture.
View stream fetches a single snapshot; Refresh frame fetches another. Fresh capture
does not imply fresh accepted scores; inspect the accepted-read age independently.
Beginning before song splash provides presence evidence. Brief state confirmation delays
are normal. Compare final scores, including full-combo endings, against the machine.
Use the separate browser workbench for pause, seek, slow playback, and diagnostic export.
Source: operator_walkthrough.md §4; tournament_desktop.md; tournament_handoff.md.

## 04. Connect the display and OBS scene control

Both integrations are optional. Renderer: obtain the separate ddr_score_render
repository/assets, select its root (containing apps/tbd5.py), apply path, then Start or
Launch renderer. The renderer's visible output must match accepted scores; a process
or client count is insufficient. Capture the window in OBS. OBS: enable its WebSocket
server, enter host/port/password (usually localhost:4455), apply, connect and Check scenes.
Default map: song_select/login/total_result to Commentator; song_splash/song_playing/
song_result to Gameplay. Use exact existing scene names; null/omitted states hold and
unknown always holds. No scenes are created. Manual switching inside DDRCV pauses
automation; Enable automation resumes. Pause automation before switching directly in
OBS. Set automatic launch/connect only after rehearsal. Source: walkthrough §§5–6;
tournament_integrations.py; publish/obs_policy.py.

## 05. Choose the results evidence you need

Capture results defaults on for new profiles; a saved off setting is preserved.
Choose a writable Screenshot folder. Default exported copies are in screenshots, while
durable originals/history are in .workbench/results unless overridden. Filenames use UTC
and a unique suffix. Include parsed names in filenames affects naming only. Screenshots
only and Read names on results apply immediately; Apply results settings applies other
Results controls without restarting gameplay or integrations. Saved results are unchanged.
Parsed scores can post first and later names update the same message. Screenshots only
saves a detected episode on departure or its original 10-second deadline and skips results
score/name OCR; gameplay scoring continues. Money and screenshot-only results do not
declare an EX winner. The separate login/song-splash names switch controls live names.
Source: walkthrough §7; results_publishing.md; tournament_desktop.md.

## 06. Verify the destination, then publish

Test Discord Webhook sends a real message using the entered URL, even when
capture and publishing are off. It does not apply settings or enable publishing. Verify
the intended channel. Publish results to Discord also checks Capture results; apply the
Results controls. Retry/send needs Running capture, Capture results, Discord publishing,
and a webhook. Inspect screenshots before sending. Queued/Sending/Retrying are ongoing;
after failure fix the cause and Retry delivery. Retry name update edits the original
message. Republish intentionally creates another post. Disabling publishing and applying
pauses queues; an in-flight send may finish. Re-enabling resumes pending work. An entirely
missed results screen cannot be recovered automatically. Source: operator_reference.md,
Results recovery; desktop/static/desk.js; results_publishing.md.

## 07. Know what applies, resets, or keeps running

Open loads a form without starting or replacing the active configuration. Save
writes the form to a profile, including actual secrets/absolute paths, and does not apply
pending edits. Start uses the current form. Apply configuration while stopped prepares
it; Start runs it. Apply and Restart while running asks before resetting tracking.
Results-only Apply preserves live gameplay and integrations. Name/screenshot-only toggles
are immediate. Stop stops recognition and owned integrations but leaves the application
available. Window close keeps the backend running; reopen from the tray or launcher.
Exit application stops the backend and owned renderer; it does not close OBS itself.
Source: operator_reference.md, Controls; desktop/controller.py and static/desk.js.

## 08. Rehearse once; repeat the startup checks

Rehearse on the actual event computer, capture device, renderer and scene
collection. Observe selection, splash, gameplay, song results and total results. Check
single-player presence, full-combo final score, capture reconnect and manual OBS/resume.
Verify actual screenshot files and Discord delivery. Installation checks and these
illustrative UI screenshots do not establish hardware readiness. Daily startup uses
the saved profile, checks device/mode/integrations, then explicit Start. A reopened panel
can already have a running backend; do not start a second app/CLI/workbench on its port.
Source: walkthrough §8; operator_reference.md, Start an event session.

## 09. Check the failing part first

Diagnose capture freshness separately from accepted-score freshness. Stale capture:
check connection, index/RTSP, native 720p, ownership and errors. Frozen requested preview
alone requires Refresh frame. Starting mid-song can lack presence evidence until a splash.
For a bad high accepted score first verify mode/input, then reset only that player's
tracking under Read details & recent errors. This cannot correct saved results. A camera
handoff probes the new source before replacing the old; success resets tracking while
preserving integrations/results. A failed probe retains the old feed. For hardware that
cannot open both, Stop/Start between songs. Port/outbox conflicts require stopping the
other session; closing its panel is insufficient. Screenshot export errors may leave
internal evidence still available for Discord. Source: operator_reference.md.

## 10. Leave a usable profile and an evidence trail

Record source folder/version, profile path, device/index/resolution, score mode,
renderer path, OBS scene collection/mapping, screenshot folder, Discord channel owner,
technical contact and manual evidence procedure. Fill the walkthrough's event table.
Do not put passwords or webhook tokens in the deck. Profile JSON contains real secrets
despite masking in the UI and saves absolute paths, which need checking on another PC.
At shutdown inspect unresolved delivery, save intended changes, then Exit application.
Keep screenshot exports and the durable outbox for evidence. Desktop logs/settings live
in %LOCALAPPDATA%/DDRCV/tournament. Before updates fully exit, update source, rerun setup,
reuse a compatible environment, and rehearse. Detailed references: operator_walkthrough.md,
operator_reference.md, installation.md, tournament_handoff.md, results_publishing.md.
