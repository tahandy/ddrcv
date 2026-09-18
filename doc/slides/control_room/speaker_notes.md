# DDRCV operator guide — Control room

## 01. Install DDRCV and open the panel

FIRST-TIME QUESTIONS: Where do I get the files? Ask the event organizer for
the tested DDRCV ZIP and, if available, a prepared settings file. A game capture device
brings the machine's video into the computer; selecting a webcam is not a substitute.
A clean recording can be used without live hardware. Renderer files, OBS scenes and
Discord are optional; skip slides 4 and 6 if they are not part of the event.
Double-click the named .bat/.vbs files in File Explorer. Setup option 1 downloads local
Python; no command prompt or prior Python install is needed. On failure keep the setup
window/error and see doc/installation.md before proceeding. Setup does not fetch the
separate ddr_score_render repository. Do not assume this deck installs that program.

ADDITIONAL REFERENCE
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

FIRST-TIME QUESTIONS: A profile is a saved .json settings file. Open… loads a
supplied profile into the form; it does not start capture. Check paths and camera index
for this computer. Without a profile, fill the visible source and mode fields.
Use Capture camera for the game's capture device. Scan lists the devices; choosing one
sets Camera index. Use RTSP only when the organizer supplies a network-stream URL.
For a full 16:9 recording at another resolution, check Resize full 16:9 file to 720p.
Do not choose Still image diagnostics for a full rehearsal. Select the score displayed
by the game: EX for event EX scoring, Money for ordinary scoring toward 1,000,000.
Ask the organizer if uncertain. Leave Publisher address/port at their defaults for a
single-computer setup. Do not run another desktop/workbench/CLI recognition session
against the same port or results storage. The browser workbench is a separate rehearsal
tool; it is not needed for this desktop walkthrough.

ADDITIONAL REFERENCE
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

FIRST-TIME QUESTIONS: The song splash is the title screen immediately before
gameplay. Start there or earlier so DDRCV can see the active players. Click View stream
first; the button then becomes Refresh frame. Each click fetches one still picture.
Check that capture age stays recent, then compare Accepted score during gameplay with
the machine. Last accepted read reports how old that accepted number is. Scores may be
blank before a valid gameplay read and stop updating after gameplay; this is not itself
a fault. Screenshots in this deck show a stopped example, not the expected Running state.
Use the actual event's final score, not a UI screenshot from this guide, for verification.

ADDITIONAL REFERENCE
The screenshots show the stopped UI as a control-location reference, not an
observed live session. Start uses the current form. Watch Running and healthy capture.
View stream fetches a single snapshot; Refresh frame fetches another. Fresh capture
does not imply fresh accepted scores; inspect the accepted-read age independently.
Beginning before song splash provides presence evidence. Brief state confirmation delays
are normal. Compare final scores, including full-combo endings, against the machine.
Use the separate browser workbench for pause, seek, slow playback, and diagnostic export.
Source: operator_walkthrough.md §4; tournament_desktop.md; tournament_handoff.md.

## 04. Optional: add a score display and OBS

FIRST-TIME QUESTIONS AND CLICK ORDER: Configure between songs. Click Stop in
DDRCV. In Renderer, Browse… to the organizer's ddr_score_render folder, containing
apps/tbd5.py. In OBS, first open the event's scene collection and enable the WebSocket
server through OBS's Tools menu; the WebSocket settings label varies by version.
Copy its port and password. In DDRCV's OBS tab, enter those values and use localhost
when OBS runs on this same computer. For another computer use the organizer's host.
Edit State → scene mapping: the left side names a game screen, the right side names
an existing OBS scene. For example, song_playing maps to Gameplay if that scene exists.
Keep the JSON quotes/commas. The supplied default map may refer to Gameplay and Commentator;
rename those values to your existing scenes or use an organizer-prepared profile.
After entering the renderer and OBS settings, click Apply configuration, then Start.
Only now use Launch renderer, Connect, Check scenes, and Enable automation as applicable.
If auto-launch/connect was selected, those actions may already have happened. Confirm the
actual renderer window and OBS scene. Add the renderer window to the intended OBS scene
using the event's window-capture setup. Default automatic scene-on-Start should remain
off during first rehearsal. Switch scene & pause automation gives manual control;
Enable automation resumes. Pause DDRCV automation before switching directly inside OBS.
Official OBS reference: https://obsproject.com/kb/remote-control-guide
Local references: doc/operator_walkthrough.md §§5–6; ddrcv/apps/tournament_integrations.py.

ADDITIONAL REFERENCE
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

## 05. Choose what to save from the results screen

FIRST-TIME QUESTIONS: All three modes retain a results screenshot. P1/P2 mean
Player 1 and Player 2 when names are not read. Capture results must be checked even
for screenshot-only operation. Choose Screenshot folder with Browse…; the default is
screenshots inside the DDRCV folder. Click Apply results settings after choosing the
folder/capture options. Screenshots only and Read names on results apply immediately;
they do not require the top-level Apply and Restart button. These controls affect the
results screen, not the live gameplay scores. Live name display has the independent
Read names on login/song splash checkbox on Status & configuration.
For local-only results leave Publish results to Discord off and skip slide 6. After a
song ends, inspect the selected folder and expand Recent results & recovery. Saved
means retained locally; Sent means delivered to Discord. With Screenshots only enabled,
wait until the results screen ends or its ten-second deadline. Missed detection requires
the event's recording/manual-results procedure, not another retry button.

ADDITIONAL REFERENCE
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

## 06. Optional: send results to Discord

FIRST-TIME QUESTIONS: A Discord webhook is a channel-specific URL that lets
DDRCV post messages. Obtain it from the channel administrator, not from the channel's
ordinary web address. An administrator can create it in Discord Server Settings →
Integrations → Create Webhook, select the results channel, and copy its Webhook URL.
Paste it unchanged into DDRCV's Results tab. Test Discord Webhook sends a real message
even while capture/publishing is off. Check the actual channel. The test does not enable
automatic publishing: separately check Publish results to Discord and click Apply
results settings. This also enables Capture results. Complete one song and check both
the saved screenshot and the real Discord post. No webhook is needed for local files.
Expand Recent results & recovery on the Results tab. Queued, Sending, and Retrying are
actual in-progress labels, not a separate Pending state. Failed records offer Retry
delivery; read the displayed error and fix the connection/webhook before retrying.
Sent records link to the message. More recovery options contains Republish, which
intentionally creates another post. Retry name update edits the existing post when a
name enrichment failed. Sending/retrying requires running capture with results capture
and Discord publishing enabled and a configured webhook. Inspect screenshots before sending.
Official Discord reference: https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks

ADDITIONAL REFERENCE
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

## 07. Save your setup and use the right controls

FIRST-TIME QUESTIONS: After the rehearsal settings work, click Save as… and
save tournament.json in the DDRCV folder, or choose another location you will remember.
This creates the event profile. Use Save to update that same file later; Open… loads
it on another launch. Saving records the form, including any edits not yet applied.
If changes should affect the current run, use the correct Apply control separately.
Stop leaves the desktop app open for later Start. Window close leaves recognition
running; launch_desktop.vbs or the DDRCV icon near the Windows clock reopens the panel.
Exit application… is the bottom-panel action that stops the whole app after confirmation.
OBS itself stays open. If Start is disabled because the app is already Running, verify
that existing session instead of trying to launch another driver.

ADDITIONAL REFERENCE
Open loads a form without starting or replacing the active configuration. Save
writes the form to a profile, including actual secrets/absolute paths, and does not apply
pending edits. Start uses the current form. Apply configuration while stopped prepares
it; Start runs it. Apply and Restart while running asks before resetting tracking.
Results-only Apply preserves live gameplay and integrations. Name/screenshot-only toggles
are immediate. Stop stops recognition and owned integrations but leaves the application
available. Window close keeps the backend running; reopen from the tray or launcher.
Exit application stops the backend and owned renderer; it does not close OBS itself.
Source: operator_reference.md, Controls; desktop/controller.py and static/desk.js.

## 08. Rehearse your setup; check every session

FIRST-TIME QUESTIONS: Rehearse after setup or material changes, not only once
for the lifetime of the installation. Check both single- and two-player operation and
the machine's final full-combo score. For every event session, open the saved .json
profile using Open…, verify this machine's device and score mode, and start before
the pre-song title screen. Use the automatic renderer/OBS options saved in the profile,
or launch/connect manually as described on slide 4. Discord checks only apply if used.
If Running is already shown, check that session; do not start a competing instance.
Finish by saving the tested settings with Save/Save as… (slide 7).

ADDITIONAL REFERENCE
Rehearse on the actual event computer, capture device, renderer and scene
collection. Observe selection, splash, gameplay, song results and total results. Check
single-player presence, full-combo final score, capture reconnect and manual OBS/resume.
Verify actual screenshot files and Discord delivery. Installation checks and these
illustrative UI screenshots do not establish hardware readiness. Daily startup uses
the saved profile, checks device/mode/integrations, then explicit Start. A reopened panel
can already have a running backend; do not start a second app/CLI/workbench on its port.
Source: walkthrough §8; operator_reference.md, Start an event session.

## 09. Check the failing part first

FIRST-TIME QUESTIONS: Read details & recent errors is an expandable section
on Status & configuration. Its Reset P1 tracking and Reset P2 tracking buttons affect
only the selected live score; they cannot edit a screenshot or saved result. Device
ownership means another application may already be using the capture device. Close
that competing capture or use the event's planned feed-sharing arrangement.
If capture will not start after Stop, wait for the device to release and read the error.
If the source or scores still fail, retain the recording, source details, score mode and
error text for the organizer. For a detailed diagnostic export, stop this session and
use doc/tournament_handoff.md's workbench instructions; do not run both on the same port.
Do not treat a stale displayed score as a newly accepted read. Do not infer a result from
unreadable text; use Screenshots only and the event's manual evidence process.

ADDITIONAL REFERENCE
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

## 10. Hand over the profile and keep the evidence

FIRST-TIME QUESTIONS: Outbox means the application's saved original result
images and Discord delivery history, not just the screenshot copies. Defaults are
screenshots and .workbench/results inside the DDRCV folder; a profile may override them.
In File Explorer open the DDRCV folder and browse those folders, or use the full path
chosen in Screenshot folder. Keep both when preserving event evidence. A copied PNG
alone cannot resume queued delivery. Inspect unresolved deliveries before exiting; the
durable records can be retried after the next Start with publishing enabled.
The walkthrough and quick reference are in the DDRCV folder's doc directory. Record
the actual settings in the walkthrough's event setup table, including a technical
contact and recording/manual-results procedure. Profiles contain real credentials;
give them only to authorized operators. Copying a profile does not install Python or
fix machine-specific camera indices and paths on another computer.

ADDITIONAL REFERENCE
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
