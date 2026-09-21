# DDRCV operator quick reference

For initial setup, follow the [operator walkthrough](operator_walkthrough.md).
This reference uses the **DDRCV Tournament** desktop app's button labels.

## Start an event session

1. Connect the capture hardware; open OBS if used.
2. Double-click **launch_desktop.vbs**, then **Open…** the event's saved profile
   if needed. Verify camera/source, **EX** or **Money**, and Results settings.
3. Click **Start**. Check **Running**, capture freshness, and **View stream**.
4. Verify accepted scores against the machine, the actual renderer window,
   and OBS's active scene. Rehearse from the song splash where possible.
5. If publishing results, verify a test result in the intended Discord channel.

## Controls and their effects

| Control | Effect |
| --- | --- |
| **Open…** | Loads a profile into the form; does not start capture or replace the active configuration. |
| **Save / Save as…** | Saves the form to a JSON profile; does not apply pending changes to the running session. |
| **Start** | Starts recognition using the current form settings. |
| **Stop** | Stops recognition and owned integrations. Last scores/frame can remain visible; check freshness. |
| **Apply configuration** | Applies settings while stopped. Click **Start** to run. |
| **Apply and Restart** | Applies pending settings during a run, restarts capture, and resets live score tracking after confirmation. Use between songs. |
| **Switch camera** | Checks a new camera/RTSP feed before switching. Success resets score/state tracking while preserving integrations and queued results. Failure retains the old source. |
| **View stream / Refresh frame** | Fetches one timestamped snapshot per click. The picture does not update continuously. |
| **Apply results settings** | Applies only the Results controls without restarting capture or clearing gameplay scores. |
| **Screenshots only** | Applies immediately: skips results text parsing, keeps gameplay scoring, and saves detected results on departure or after ten seconds. |
| **Read names on results** | Applies immediately; off uses P1/P2 labels while results score parsing continues when Screenshots only is off. |
| **Read names on login/song splash** | Applies immediately; off clears live names while score recognition continues. |
| **Reset P1 tracking / Reset P2 tracking** | Under **Read details & recent errors**. Clears only that player's live score until another read is accepted. Saved results stay unchanged. |
| **Switch scene & pause automation** | Switches OBS manually and pauses automatic scene changes. **Enable automation** resumes them. |
| Window close / Alt+F4 | Closes the panel; capture and the backend continue. Reopen from the tray or launcher. |
| **Exit application…** | Stops the backend and its owned integrations after confirmation. OBS itself stays open. |

The eye button beside the OBS password and Discord webhook shows or hides the
entered value, including saved values after reopening the panel or loading a
profile. The configuration JSON preview remains masked.

OBS and renderer settings use the main configuration controls. Apply edited
host, password, mapping, repository path, or publisher port before using their
integration buttons. Save the profile separately to retain changes in that file.

## Results recovery

Open **Results → Recent results & recovery**. Inspect the screenshot before
deciding whether to send it. Sending and retrying require capture running with
**Capture results**, **Publish results to Discord**, and a configured webhook.

| Delivery status or problem | What to do |
| --- | --- |
| **Saved** | Stored locally. Use **Send saved result** when it should be posted. |
| **Queued / Sending / Retrying** | Delivery is pending or in progress. Check connectivity and wait for its outcome. |
| **Failed** | Read the error, fix the connection/webhook problem, then use **Retry delivery**. |
| **Sent** | Use **Open Discord message** to check the post. |
| Failed name update | Use **Retry name update** when available; this updates the existing post. |
| Need another copy of a sent result | **More recovery options → Republish** creates another Discord post after confirmation. |
| Screenshot export warning | Check folder permissions and free space. The internal screenshot may still be saved and eligible for delivery. |
| Names are wrong | Turn off **Read names on results**. For live names, use the separate login/song-splash switch. Existing saved results are not corrected by these switches. |
| Results text is unreliable | Enable **Screenshots only**. Keep **Capture results** on; publishing must also be on for automatic posts. |
| Entire results screen was missed | Use the event's recording/manual evidence procedure. Automatic recovery needs a detected results episode. |

Disabling Discord publishing and clicking **Apply results settings** pauses
queued deliveries. A post already being sent may finish. Re-enabling publishing
resumes queued deliveries. **Test Discord Webhook** sends a real test message
using the entered URL but does not apply settings or enable automatic publishing.

## Troubleshooting during a session

| Symptom | First action |
| --- | --- |
| Launcher says to run setup, or the panel will not open | Run **setup_desktop.bat** and keep the failure text if it fails. See [installation troubleshooting](installation.md#update-and-troubleshoot). |
| Panel closed or crashed, but scores still run | Relaunch **launch_desktop.vbs** or use the tray's **Open panel**. |
| No picture / stale capture | Check cable, device index or RTSP address, 1280 × 720 output, and another app's ownership of the capture device. Check recent errors. |
| Preview looks frozen | Click **Refresh frame**. Judge capture using its age/health readout; preview is a snapshot. |
| State or scores are wrong | Inspect the complete game frame for overlays, cropping, or scaling; verify EX/Money mode and read rejection details. |
| A player is absent after starting mid-song | Observe a full song splash. Starting mid-song can lack player-presence evidence. |
| One accepted score is stuck incorrectly high | Verify the image and score mode, then use that player's **Reset tracking** control. This does not fix a bad source or edit saved results. |
| Renderer blank while accepted scores are correct | Check publisher clients, renderer status/path, and its actual window. Apply changed paths/ports before relaunching it. |
| OBS scene is wrong | Check connection, exact scene names, **Check scenes**, and whether automation is enabled. |
| Replaying a recording produces no new screenshot or Discord post | **Replay already saved** means that result was previously captured. Open **Results → Recent results & recovery** to view it. **More recovery options → Republish** deliberately creates another Discord post. Existing screenshot filenames keep their original capture date; live camera results are separate events. |
| Panel says **Reconnecting to desktop backend…** | Wait for automatic reconnection. If it persists or says the desktop session expired, close and reopen the panel from the tray. Closing the panel preserves capture. If the backend exited, relaunch DDRCV. For an interrupted button action, check its status before repeating it. |
| Port 9000 or Results outbox is already in use | Stop the other desktop/workbench/CLI session. A closed desktop panel can still have a running backend. |
| Camera switch fails | Read the source error; the old feed remains active. If the hardware cannot open both sources briefly, use **Stop**, select the new camera, then **Start** between songs. |
| App is still cleaning up after Stop | Wait for capture to release before starting another session; check recent errors. |

For recording demos or development, enable **Results → Allow repeat screenshots and Discord posts from recordings** and click **Apply results settings**. Each replay can save and post again. Keep Capture results and Discord publishing enabled; turn the repeat option off when testing is finished.

Capture age and accepted-read age describe different things: fresh frames can
arrive while scores are rejected. **Processing capacity** measures active frame
processing speed; **Throughput** counts completed frames per second, including
waits. A high capacity does not by itself prove fresh capture or successful OCR.

## Files and shutdown

| Item | Default location |
| --- | --- |
| Launcher / installer | `launch_desktop.vbs` / `setup_desktop.bat` in the DDRCV folder |
| Saved event profile | The JSON path chosen with **Save as…** |
| Screenshot copies | `screenshots` in the DDRCV folder, or the chosen **Screenshot folder** |
| Durable Results records and original screenshots | `.workbench/results` in the DDRCV folder, unless the profile overrides it |
| Desktop settings and logs | `%LOCALAPPDATA%\DDRCV\tournament` (paste into File Explorer's address bar) |

At the end of the session, inspect unresolved results deliveries, save intended
profile changes, then choose **Exit application…**. Closing only the window keeps
the application running. Keep screenshots and the Results outbox when preserving
event evidence; screenshot copies alone do not contain delivery history.

Before an update, fully exit DDRCV and stop the workbench/CLI. Update the source,
rerun **setup_desktop.bat**, and choose **4** to reuse a compatible existing
environment. Rehearse before returning to event operation. Saved profiles can
contain credentials; remove secrets before sharing them for support.

For a reproducible recognition problem, use the
[browser workbench's diagnostic export](tournament_handoff.md#4-save-a-problem-and-identify-the-failing-layer)
to capture the frame, crops, and read decisions.
