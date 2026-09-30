# DDRCV: first-time setup and operator walkthrough

Use this guide to go from a downloaded DDRCV folder to a rehearsed tournament
setup on Windows. It follows the **DDRCV Tournament** desktop app. Keep the
[operator quick reference](operator_reference.md) open during an event.

For a guided training session, use the [slide deck](slides/README.md), available
as editable PowerPoint and PDF with speaker notes.

DDRCV reads a DDR World video feed and publishes the scores. The optional
`ddr_score_render` application displays those scores in a window for OBS to
capture. OBS can also change scenes automatically. Results screenshots can be
saved locally and posted to Discord.

## 1. Gather what you need

- A 64-bit Windows computer and internet for initial installation.
- The event's DDRCV repository ZIP or checkout. Ask the organizer which version
  and saved configuration to use, if they have prepared one.
- A capture device or RTSP feed showing the **complete, unobstructed game screen
  at 1280 × 720**. Borders, broadcast overlays, cropping, and stretching can put
  the scores outside the regions DDRCV reads.
- For rehearsal without the machine: a full-frame 16:9 game recording.
- If used at the event: OBS, the `ddr_score_render` repository and its assets,
  and a Discord webhook for the intended results channel.

You can get recognition working before configuring the optional integrations.
The first installation downloads Python, application packages, and the OCR
model used to read text. You do not need to install Python yourself.

## 2. Install and open DDRCV

1. Extract the ZIP completely into a writable folder such as `C:\Games\ddrcv`.
   Open that folder; it should contain `setup_desktop.bat` and
   `launch_desktop.vbs`. Do not run setup from inside the ZIP.
2. Double-click **setup_desktop.bat**.
3. On a fresh installation, choose **1. Install/use local Python in this
   checkout**, or press Enter. If you deliberately want an existing Python,
   choose **2** to select a detected installation or **3** to enter its path.
   It must be 64-bit CPython 3.12.
4. Leave the setup window open until it says **Setup complete**. It installs
   the application, checks actual OCR recognition, and checks/installs the
   WebView2 component used by the desktop window. If it says **Setup failed**,
   keep the error text and use [installation troubleshooting](installation.md#update-and-troubleshoot).
5. Double-click **launch_desktop.vbs**. The **DDRCV Tournament** window opens.

**Check before continuing:** the panel is open and capture is stopped. Merely
opening the app or restoring a profile does not start capture.

Setup stores its environment in `.venv` and local tools/Python in `.tools`.
Keep those folders in place. To install on another computer, copy the source
and run setup there; do not rely on copying an existing Python environment.

## 3. Choose your source and score mode

On **Status & configuration**, use **Open…** if the organizer supplied a JSON
profile. Check its source, file paths, and integrations for this computer.
Otherwise, configure the following:

| Source | What to enter |
| --- | --- |
| **Capture camera** | Click **Scan**, select the capture device in **Camera**, and check **Camera index**. The index is this computer's device number and can differ from another computer's. |
| **RTSP stream** | Enter the feed in **Stream URL**. The feed must deliver 1280 × 720 frames. |
| **Local video** | Use **Browse…** under **Local media**. For a full 16:9 recording at another resolution, check **Resize full 16:9 file to 720p**. |
| **Still image diagnostics** | Use for inspecting a frame. A still image cannot establish live score or screen-state confirmation. Use video for an end-to-end rehearsal. |

Choose **Score mode** to match the score displayed by the game:

- **EX score** for the event's EX scoring. This is the desktop default.
- **Money score** for the game's ordinary score toward 1,000,000.
- Leave **Custom filter** to someone maintaining a custom profile.

This choice controls gameplay filtering and results interpretation. A wrong
mode can prevent valid scores from being accepted. The separate browser
workbench defaults to Money, so check the mode when moving between apps.

Leave **Publisher address** and **Publisher port** at their defaults
(`localhost`, `9000`) for a single-computer setup. Run only one desktop,
workbench, or CLI recognition session using that port and Results outbox.

If a supplied profile enables OBS automation or Discord publishing, turn those
off for a local-only rehearsal. On **Results**, click **Apply results settings**
after disabling publishing if capture is already running.

## Optional: identify songs and chart max EX

On **Song recognition**, follow **Choose → Prepare → Activate**. Gameplay score
reading works without this optional feature.

1. **Choose:** select your **DDRCardDraw event pool** or **Full DDR / WORLD charts**.
   The default is **Dia Del Ritmo 2026**; change it for another event. Use the
   event link from [ddr.tools](https://ddr.tools/), such as
   `https://ddr.tools/#game-dia_del_ritmo_26`. Tournament registration links are
   not catalog links. Website difficulty filters do not restrict recognition.
2. **Prepare:** choose **Build catalog** while online, or **Load catalog…** to use
   a supplied `.ddrcatalog` file offline. Load fills in its event automatically.
   Both validate the file. Expand any **Coverage warnings** to see affected
   songs/charts; a usable catalog can still have incomplete recognition coverage.
3. **Recognition settings:** check **Recognize song and max EX** and choose **Singles** or
   **Doubles**. Use **Start** in the window header to apply pending settings and
   start the source selected on **Status & configuration**. While running, use
   the header’s **Apply and Restart** to apply changes and reset tracking.
4. Play a recording from before the song splash. Check **Recognition active**,
   then verify the identified song and each player's chart max EX on the status
   tab. Building or loading alone does not enable recognition or start capture.

**Catalog found — checked when activated** means the file exists but has not yet
been validated in this application session. Activation checks it before use.
Closing and reopening the panel keeps the backend's validation state.
If the loaded file belongs to another selection, use the offered actions to
restore its event or build your new selection at its default location.

For offline sharing, coverage limits, and recovery, see
[song and chart recognition](song_recognition.md).

## 4. Start recognition and check the picture

1. If capture is still stopped, click **Start**. It uses the settings currently in the form.
2. Check that the phase becomes **Running** and capture is healthy.
3. Click **View stream** to inspect the input. This is one timestamped snapshot;
   click **Refresh frame** for another. A still preview by itself does not mean
   capture has frozen. Use the capture age and health text to judge freshness.
4. Run through song selection, the song splash, gameplay, and the results screen.
   Starting before the splash lets DDRCV observe which players are present.
5. During gameplay, compare **Accepted score** for P1 and P2 with the machine.
   Check **Last accepted read** as well: an old number is not a fresh reading.
6. Open **Read details & recent errors** if a score is missing or seems stuck.
   It includes read details and rejection reasons.

**Check before continuing:** the picture is correctly framed, the confirmed
state follows the game, and accepted scores update for the active players.
Brief state-confirmation delays are expected; a single matching frame is not
enough. Verify final scores too, including a full-combo ending.

For paused inspection, seeking, slow playback, and diagnostic exports, click
**Stop**, then use the [browser rehearsal walkthrough](tournament_handoff.md).
The desktop video source runs through the file and stops at its end.

## 5. Add the score display, if needed

1. Obtain the event's `ddr_score_render` repository and required assets. It is a
   separate download; DDRCV setup does not fetch it. A convenient layout is
   `C:\Games\ddrcv` alongside `C:\Games\ddr_score_render`.
2. In **Renderer**, use **Browse…** to select the renderer repository folder.
3. Check **Launch on Start** if it should start with each recognition session.
4. Apply these settings with **Apply configuration** while stopped, then
   **Start**. During a test session, **Apply and Restart** also applies them,
   but resets live score tracking. If automatic launch is off, use
   **Launch renderer** after starting capture.
5. Look at the actual renderer window and compare it with DDRCV's accepted
   scores. A running process or publisher client count alone does not prove
   the display is correct.
6. Capture the renderer window in OBS and verify it in your intended scene.

The renderer buttons use the applied configuration. Apply a changed repository
path or publisher port before using them. Check the renderer status/error if
the window fails to launch.

## 6. Connect OBS and rehearse scene switching, if needed

1. Open OBS with the event's scene collection and enable its WebSocket server.
   Obtain its host, port, and password; the usual same-computer values are
   `localhost` and `4455`.
2. On DDRCV's **OBS** tab, enter those values. Check **Connect on Start** and
   initially leave **Enable scene automation on Start** off.
3. Edit **State → scene mapping** to use exact scene names already in OBS. The
   field is JSON: retain its quotes and commas. For example:

   ```json
   {
     "song_select": "Commentator",
     "login": "Commentator",
     "total_result": "Commentator",
     "song_splash": "Gameplay",
     "song_playing": "Gameplay",
     "song_result": "Gameplay"
   }
   ```

   Replace `Commentator` and `Gameplay` if your scenes have different names.
   Set a value to `null` to hold the current scene for that state. Unknown
   states always hold. DDRCV does not create the scenes.
4. Apply the configuration, then start capture. Click **Connect** if needed,
   then **Check scenes**. These buttons use the applied settings.
5. Click **Enable automation** and rehearse a complete song. Check the actual
   scene shown by OBS at each transition.
6. Test **Switch scene & pause automation** for manual control. Use
   **Enable automation** to resume. Pause automation before changing scenes
   directly in OBS so DDRCV does not change them back.

Once rehearsed, you can enable **Enable scene automation on Start**, apply it,
and save the profile if that matches your event workflow.

## 7. Configure results screenshots and optional Discord posts

On **Results**:

1. Check **Capture results**. New profiles default to on; an existing profile
   may have it off.
2. Set **Screenshot folder** to a writable location you can find easily, such
   as `C:\Games\ddrcv\screenshots`. The default is `screenshots` inside DDRCV.
3. Choose the results behavior below.
4. For Discord, obtain a webhook for the intended channel and enter
   **Webhook URL**. **Test Discord Webhook** sends a real test message using
   the entered URL, even if publishing and capture are off. Check that it
   arrives in the intended channel.
5. Enable **Publish results to Discord** for automatic posts. This also checks
   **Capture results**. Leave publishing off for local-only capture.
6. Click **Apply results settings**. This applies the Results controls without
   restarting capture, resetting gameplay scores, or reconnecting integrations.
7. Finish a test song. Open **Recent results & recovery**, inspect the saved
   screenshot and delivery status, and verify the actual Discord post if used.

| Desired behavior | Settings |
| --- | --- |
| Read results scores and player names | **Screenshots only** off; **Read names on results** on. Confirmed scores can post first; later confirmed names update the same message. |
| Read results scores with P1/P2 labels | **Screenshots only** off; **Read names on results** off. |
| Keep screenshot evidence without reading results text | **Screenshots only** on. A detected results screen is saved on departure or after ten seconds, with no parsed names, scores, or winner. Live gameplay scores continue. |

**Screenshots only** and **Read names on results** apply immediately. The
separate **Read names on login/song splash** switch on **Status & configuration**
also applies immediately; it controls names displayed during the live session.
**Include parsed player names in filenames** controls naming only, and includes
names only when they were successfully read. Screenshot filenames use UTC time.

If results detection misses the entire screen, there is no automatic screenshot
to recover. Keep your event's recording/manual evidence procedure available.
Money results and screenshot-only results do not declare an EX winner.

## 8. Save the event profile and rehearse a handoff

1. Click **Save as…** and choose a recognizable JSON filename, such as
   `tournament.json`. Use **Save** after later changes.
2. Remember that **Save writes the form to disk**. It does not apply pending
   changes to the running session. **Apply and Restart** does that and resets
   live score tracking; use it between songs.
3. Close the panel with its window close button. Confirm capture and the score
   display continue. Reopen from the DDRCV tray icon's **Open panel** or by
   double-clicking **launch_desktop.vbs** again.
4. Use **Exit application…** to stop the whole application, then relaunch it.
   Open the saved profile if necessary and click **Start** explicitly.
5. Have the next operator follow the [quick reference](operator_reference.md)
   using the event setup details below.

Saved profiles contain actual webhook/password values, even though the fields
are masked in the panel. Keep those profiles local or share them privately with
the authorized operator. Profiles also save absolute paths; verify those paths
and the camera index when setting up another computer.

Before handing over, rehearse two-player and single-player play, a full-combo
ending, capture reconnect, manual OBS switching and resume, and Results
delivery/recovery on the actual event computer.

### Event setup details to fill in

| Item | This event |
| --- | --- |
| DDRCV folder and version supplied by organizer | |
| Saved profile path | |
| Capture device / camera index / resolution | |
| Score mode: EX or Money | |
| Renderer repository path | |
| OBS scene collection and mapped scene names | |
| Screenshot folder | |
| Discord channel and person managing its webhook | |
| Technical contact and recording/manual-results procedure | |

## Further reference

- [Operator quick reference and troubleshooting](operator_reference.md)
- [Installation, updates, and existing Python environments](installation.md)
- [Desktop configuration and behavior](tournament_desktop.md)
- [Recorded-footage rehearsal and diagnostic exports](tournament_handoff.md)
- [Results confirmation, delivery, and recovery details](results_publishing.md)
