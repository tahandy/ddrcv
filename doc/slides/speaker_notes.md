# DDRCV operator guide — speaker notes

Slide content and screenshots reflect the repository on 18 September 2026.


## 01. DDRCV

Audience: the person setting up or running the tournament station.
Walk through slides 1–16 before the event; use slides 17–21 at the desk.
The screenshots are current desktop forms in an isolated stopped session,
with example local paths and no credentials. They are not a live rehearsal.
Source: doc/operator_walkthrough.md and doc/operator_reference.md.
Source/UI snapshot: 18 September 2026. Recheck labels after application updates.


## 02. What connects to what

DDRCV reads the full DDR World game feed and publishes live scores.
ddr_score_render is a separate repository that displays those scores in a
window. OBS can capture that window and optionally automate scene selection.
Results capture saves evidence locally and can send it through a Discord webhook.
Neither OBS nor the renderer is required to verify recognition itself.
Source: doc/operator_walkthrough.md, introduction and sections 5–7.


## 03. Before you start

Use the version or ZIP supplied by the event organizer. Extract it into a
writable folder, not Program Files and not inside the ZIP. First setup needs
internet. No existing Python install is necessary. Live capture is fixed at
1280 × 720; a full-frame 16:9 recording can be resized explicitly.
OBS, renderer assets, and a webhook are optional. Get the renderer repository
and its assets from the organizer; DDRCV setup does not download them.
Source: doc/operator_walkthrough.md sections 1–2; doc/installation.md.


## 04. Install once, then use the launcher

Double-click setup_desktop.bat. On a fresh install, Enter selects option 1:
Install/use local Python in this checkout. Option 2 finds compatible installed
Python versions; option 3 accepts a manual path. The supported interpreter is
x64 CPython 3.12. On later runs, option 4 reuses the existing environment.
Setup installs locked dependencies, provisions and tests actual OCR, and checks
WebView2. Wait for Setup complete. If it fails, retain the exact error text.
Do not move or delete .venv or .tools/python. Set up a fresh environment when
moving to another computer. See doc/installation.md for troubleshooting.


## 05. Find the four areas of the panel

This screenshot shows the real app with capture stopped. The UI may display
unknown or absent players until a live session observes them.
Status & configuration: source, score mode, health, names, accepted scores.
OBS: connection, mapping, automation and manual scene switching.
Renderer: repository path and launch controls.
Results: screenshots, Discord, and recent results/recovery.
Source: ddrcv/desktop/templates/index.html and static/desk.js.


## 06. Choose a clean source

Capture camera: Scan, choose the device, then check Camera index. Device indices
can differ between computers. RTSP stream: enter the URL; frames must be 720p.
Local video: Browse to the file, enabling Resize full 16:9 file to 720p if needed.
Borders, cropped broadcasts, overlays, or stretching move the recognition regions.
Still image diagnostics cannot establish temporal score or state confirmation.
Leave publisher localhost:9000 for a single-computer setup. Run only one app,
workbench, or CLI against that publisher port and Results outbox.
Source: doc/operator_walkthrough.md section 3.


## 07. Match the score mode to the game

Select EX when the game shows the event EX score. Select Money for the ordinary
score toward 1,000,000. Desktop defaults to EX; the browser workbench defaults
to Money. A profile can override either, so always verify the selected mode.
A wrong score mode may reject otherwise valid score reads and uses the wrong
results crop. Leave Custom filter to the profile maintainer.
Money results do not declare an EX winner.
Source: driver_config.py; doc/results_publishing.md, confirmation/mode rules.


## 08. Prove recognition before adding integrations

The screenshot is a stopped UI for orientation, not proof of a running capture.
During your test, look for Running, healthy capture, a confirmed state following
the game, and recent accepted reads that agree with the machine.
View stream fetches one snapshot. Refresh frame fetches the next; it is not a
continuous preview. Starting mid-song can lack player-presence evidence.
The final score, including a full-combo ending, must be compared with the machine.
A briefly delayed confirmed state is expected because recognition needs multiple
observations. Source: operator_walkthrough.md section 4; tournament_desktop.md.


## 09. Add the score renderer

Obtain the separate ddr_score_render repository and assets from the organizer.
Select its folder with Browse; the folder must contain apps/tbd5.py.
Set Launch on Start if desired. Apply configuration while stopped, then Start.
If already running, Apply and Restart resets tracking, so use it between songs.
With automatic launch off, use Launch renderer after starting capture.
Check the actual window, then capture it in OBS. Publisher clients or a running
process alone do not establish visible output. Buttons use the applied path/port.
Source: doc/operator_walkthrough.md section 5; tournament_integrations.py.


## 10. Connect OBS before enabling automation

Enable OBS's WebSocket server. Enter the host, port and password into DDRCV;
usual same-computer settings are localhost and 4455. Check Connect on Start.
Keep Enable scene automation on Start off for the initial rehearsal.
Edit the JSON map, retaining quotes and commas. Apply configuration and Start;
Connect if necessary, then Check scenes. Enable automation after validation.
song_select, login and total_result default to Commentator; song_splash,
song_playing and song_result default to Gameplay. Null/omitted mappings hold;
unknown always holds. No scenes are created by DDRCV.
Source: doc/operator_walkthrough.md section 6; publish/obs_policy.py.


## 11. Practice manual OBS control

In DDRCV's OBS tab, select an existing scene and use Switch scene & pause
automation. Resume with Enable automation; it reconciles to the latest
confirmed state. If changing a scene directly in OBS, pause DDRCV automation
first so it does not change the scene back. This does not stop recognition.
After a successful rehearsal, choose whether automation should enable on Start,
then apply and save the profile. Source: tournament_desktop.md and obs_policy.py.


## 12. Save results screenshots

New profiles enable Capture results, but an existing saved off value is honored.
Choose a writable screenshot folder. Default copies are under screenshots in
the checkout. Durable originals and delivery records live in .workbench/results
unless configured otherwise. Changing the screenshot folder does not move old files.
Filenames use UTC time and a unique event suffix. Parsed names can be included
only when recognized. Apply results settings does not restart capture, clear
gameplay scores, or reconnect OBS/renderer. Save the JSON profile separately.
Source: operator_walkthrough.md section 7; results_publishing.md.


## 13. Test Discord, then enable automatic posts

Ask the organizer/channel administrator for the intended results webhook. Enter
it in Results. Test Discord Webhook uses the URL currently entered even when
capture and automatic publishing are off. It does not apply pending settings
or enable publishing. Verify the channel before enabling Publish results to Discord.
Enabling publishing also checks Capture results. Click Apply results settings.
Complete a test song, inspect Recent results & recovery, then inspect Discord.
During a local rehearsal leave publishing off, or use the organizer's test channel.
Source: desktop/templates/index.html; operator_walkthrough.md section 7.


## 14. Choose how much results text to read

Screenshots only and Read names on results apply immediately, without a general
restart. Screenshots only skips both results score and name OCR. The detected
results episode saves on departure or after its original ten-second deadline.
Capture results must stay enabled; Discord must also be enabled for posts.
With parsing enabled, confirmed scores can post before names; later confirmed
names update the same message. With name parsing disabled, scores use P1/P2.
The login/song splash name switch is separate and applies immediately.
These switches do not correct saved results or recover an entirely missed screen.
Source: results_publishing.md and tournament_desktop.md.


## 15. Save a profile and understand Apply

Open loads a profile into the form without starting capture. Save/Save as writes
the form into a JSON profile without applying pending changes to the current run.
Start uses the current form. Apply configuration works while stopped; Start runs it.
Apply and Restart during a run confirms a reset of live score/state tracking.
Use Results-only Apply for those controls; name and screenshot-only switches are
immediate. Save a named profile after changing settings, even when the local draft
is automatically retained. Profiles contain real secrets and absolute paths.
Source: desktop/controller.py, static/desk.js; operator_walkthrough.md section 8.


## 16. Finish with a real event rehearsal

Use the actual tournament computer, capture device, renderer and OBS scene
collection. Observe select → splash → gameplay → song results → total results.
Validate full-combo final scores, single-player presence and starting mid-song.
Exercise capture reconnect, manual scene selection/resume, and window close/reopen.
Check actual Results files and Discord messages, including recovery from delivery
failure. If a results screen is never detected, automatic recovery has no episode.
Preserve the event's recording or manual evidence procedure.
Source: operator_walkthrough.md section 8; tournament_handoff.md section 5.


## 17. Start the station in five steps

If the panel was closed but the backend remains active, reopening it does not
create another recognition session. Fully exiting or a backend crash requires
relaunch and an explicit Start. Profile restoration never starts capture itself.
Verify mode and capture index every time hardware or computers change. A saved
profile can restore automatic OBS/Discord actions; inspect it before Start.
For problems, check fresh capture and accepted-read ages independently.
Source: operator_reference.md, Start an event session.


## 18. Recover a saved result

Inspect the saved screenshot before sending. Send/retry requires capture Running,
Capture results enabled, Discord publishing enabled, and a configured webhook.
Saved: use Send saved result. Failed: fix the issue and Retry delivery.
Queued/Sending/Retrying: wait and watch connectivity. Sent: Open Discord message.
Retry name update edits the existing message after a failed name update.
Republish under More recovery options confirms creation of another Discord post.
Disabling publishing and applying pauses queued deliveries; in-flight sends may
finish. Re-enabling resumes queued work. A completely missed screen cannot recover.
Source: operator_reference.md, Results recovery; static/desk.js.


## 19. When something looks wrong

Preview is a requested still; Refresh frame updates it. Capture freshness and
accepted-read age differ: frames can be fresh while score reads are rejected.
Check complete 1280x720 framing, source, score mode, and read rejection reasons.
If a wrongly high accepted score is stuck, use Reset P1/P2 tracking after checking
the input. It clears only that live score and does not edit saved results.
A camera switch tests the new source before replacing the old; success resets
tracking. If a driver cannot open both, Stop/Start the new source between songs.
Port/outbox conflicts: stop the other desktop/workbench/CLI; a closed panel can
still own the session. See operator_reference.md for the full troubleshooting table.


## 20. Closing the panel keeps capture running

Window close/Alt+F4 closes the disposable UI, while the backend keeps capture,
publishing, automation and owned renderer active. Open panel from the tray or
relaunch the VBS to reopen without resetting scores. Exit application confirms
stopping the backend and its owned renderer; OBS itself remains open.
At session end inspect unresolved deliveries, save intended profile changes,
then exit. Keep the screenshot copies and .workbench/results outbox for evidence.
Desktop settings/logs: %LOCALAPPDATA%/DDRCV/tournament. For updates fully exit,
update source, rerun setup using option 4 for a compatible environment, and rehearse.
Source: operator_reference.md, Files and shutdown; tournament_desktop.md.


## 21. Leave the next operator a complete handoff

Fill the event setup table in doc/operator_walkthrough.md before handover.
Include DDRCV folder/version, saved JSON path, source device/index/resolution,
EX/Money, renderer folder, OBS scene collection/mapping, screenshot folder,
Discord channel/contact and manual evidence procedure.
Do not write webhook tokens or passwords into this presentation; saved JSON
profiles contain actual credentials despite masked UI fields. Share them only
with authorized operators. Verify absolute paths and camera index on each computer.
Further reading: doc/operator_walkthrough.md, doc/operator_reference.md,
doc/installation.md, doc/tournament_handoff.md, doc/results_publishing.md.
