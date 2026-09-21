# Results capture and Discord delivery

The desktop and tournament runtime use the webhook configured in the Results
settings/profile. Older scripts using `ddrcv.discord.get_webhook_url` instead
require the `DDRCV_DISCORD_WEBHOOK_URL` environment variable; they fail when it
is unset rather than falling back to a bundled webhook. Keep credentials in
local settings or environment variables, never in source files.

For custom renderers consuming gameplay state, scores, names, or the optional
`results` status object, see the [streaming state specification](streaming_state.md).

In the desktop **Results** tab, use **Test Discord Webhook** to send a text-only
test message to the URL currently entered. Capture and automatic publishing can
remain off, and no screenshot is required. The button shows delivery success or
an error; testing does not apply pending results settings or enable publishing.

The tournament CLI, desktop app, and workbench use the same background results service. It reads
player names and the **large score**, captures the supporting clean frame, and
publishes a compact Discord embed. Lower-panel tabs, judgments, difficulty, stage,
and song lookup are not prerequisites.

## Install and run

Use the Python environment inside this checkout. OCR dependencies are
included in the `tournament`, `workbench`, and `desktop` extras in
`pyproject.toml`. Both setup scripts provision the model and run real inference.
For a manual OCR-only install in an existing environment, run
`python -m pip install -e ".[ocr]"` from the repository root, followed by
`python -B -m ddrcv.ocr.check --provision`.

```bat
.venv\Scripts\python.exe -B -m ddrcv.workbench --port 5004
```

Open the **Results and Discord** panel. Enable capture, choose whether to publish
automatically, and supply a webhook. Local results settings and credentials are
saved in ignored `.workbench/results_config.json`. The webhook is never returned
by status APIs or exported diagnostics. Saved posts have a publish action; failed
posts have retry; sent posts have an explicit republish action.

The score selector governs both gameplay filtering and results interpretation.
Select **EX** for the supplied event-mode recording. Money mode reads the money
headline and never declares an EX winner. A mistaken mode selection is not
corrected by inspecting the lower statistics tab.

The CLI loads the same local results config, then applies explicit JSON overrides:

```bat
.venv\Scripts\python.exe -B -m ddrcv.apps.driver_ddr --video C:\code\ddrcv\apps\scripts\2025-03-27_15-52-48.mkv --score-mode ex
```

Run from this checkout's root. The default outbox is `.workbench/results`;
`results.outbox_directory` overrides it for the CLI and desktop app. Do not run two instances
against the same outbox at once: the second reports that it is already in use.
Independent rehearsal runs should use a separate workbench `--data-dir` or CLI
outbox. An OS lock releases automatically when its owner exits or crashes.

### Configuration

Example (without credentials):

```json
{
  "enabled": true,
  "parse_names": true,
  "output_directory": "screenshots",
  "include_player_names": true,
  "discord": false,
  "rehearsal": true,
  "webhook": null,
  "confidence": 0.8,
  "sample_hz": 5,
  "settling_seconds": 2,
  "min_frames": 5,
  "confirmation_seconds": 1,
  "max_gap": 0.75,
  "deadline_seconds": 10,
  "only_duo": false,
  "ocr": {
    "model_path": "C:/path/to/en_PP-OCRv5_rec_mobile.onnx",
    "allow_download": false
  }
}
```

Provision the pinned English PP-OCRv5 model through `RapidOCRRecognizer(model_dir=...).warmup()`
once; keep it local for offline operation. See the [OCR documentation](../ddrcv/ocr/README.md).
The workbench's capture/publishing controls do not edit the model configuration.

## Confirmation and partial results

Only fresh frames with both raw and confirmed `song_result` labels contribute.
After the two-second settling minimum, each field needs matching accepted values
on at least five samples spanning one second. Low confidence, missing text,
contradictions, capture gaps, or interrupted results recognition clear the
relevant consecutive evidence. A paused frame never accumulates votes.

As soon as scores for all present players confirm, the supporting frame and scores
are saved and queued. Names never delay this first post. Missing names continue
being read until they confirm, the screen ends, or the original ten-second deadline
expires. Each later name must come from the same episode with score readings that
match the saved scores. The local record is updated first, then the original Discord
message is edited. Scores, outcome, screenshot, and filenames remain unchanged.

Screenshot candidates are retained independently of OCR, at the existing sample
rate. At the deadline or screen departure, an unconfirmed result prefers a settled
frame with the lowest average score-crop motion across three consecutive samples
(ties prefer newer frames), then the latest settled frame, then the latest recognized
results frame. Recognition interruptions and capture gaps break motion comparisons.
Visual stability is not score confirmation. Only confirmed fields belonging to the
selected frame are included; missing values stay null. Up to two alternative frames
are retained in the outbox for inspection. Live capture loss still expires the deadline;
paused file playback does not advance it. Completely undetected results screens are
not recoverable through this feature.

Two confirmed EX scores permit a winner/margin or **TIE**, even if a missing name
must be shown as P1/P2. Confirmed single-player results have no competitive
outcome. Confidence is not proof of correctness; the MKV validation covers one
recording and two names, not arbitrary captures or layouts.

Set `parse_names: false` to skip name OCR and name confirmation entirely. Present
players then use P1/P2 labels, and confirmed scores are sufficient for a complete
result. This setting defaults to true and appears as **Read names on results** in
the desktop Results tab. It applies immediately without restarting capture or resetting
scores. A names-only change clears name evidence, preserving score evidence,
screenshot candidates, and the original deadline. Disabling it after the first post
ends further name enrichment for that episode; it does not remove saved names.


## Screenshots-only operation

Set `results.screenshots_only: true`, or use the live **Screenshots only** desktop
switch, to bypass all results score/name OCR. Capture and Discord publishing remain
separate settings. The service still detects results episodes, retains sampled
frames, and saves the existing motion-ranked fallback on departure or at the
original deadline (ten seconds by default). OCR models are lazy and are not loaded
for this path. Gameplay tracking and login/splash names are unchanged.

Saved records carry `screenshots_only: true`, null names/scores, and no winner.
Discord shows the screenshot with an explicit parsing-disabled label; intentional
missing fields are not described as a partial recognition failure. The same outbox,
retry, alternatives, exports, and recovery controls apply. Older records/profiles
without the flag keep their existing behavior.

The live switch retains screenshot candidates and the episode deadline, clears
unfinished parsing evidence, and invalidates in-flight OCR. Already-saved content
is preserved; mode changes never duplicate its post. Turning parsing back on uses
fresh evidence and the saved name-reading preference.

## Concurrency, persistence, and delivery

Capture only submits sampled frame copies to a bounded latest-frame mailbox.
OCR, screenshot/metadata persistence, and Discord delivery use separate workers.
Slow OCR replaces pending samples instead of blocking capture. Session generations
invalidate in-flight OCR after seek, source change, or score-mode change.

Each finalized event has its own directory containing `screenshot.png` and atomic
`result.json` metadata. Recorded-source identity plus observed results intervals
suppress replay duplicates; live episodes are separate events. Source intervals
extend in memory as results frames arrive and persist independently of Discord
requests. Sealed EOF bundles reserve their intervals before saving, so looping
cannot duplicate a result while its screenshot is still being written. This does not infer unseen portions
of a recording after an arbitrary seek.

When replaying a saved interval, the desktop shows **Replay already saved**:
it reuses the existing result and does not write another screenshot or send
another automatic Discord post. The screenshot filename retains its original
capture date, even when you replay the video later. Open **Results → Recent
results & recovery** to inspect the existing screenshot and delivery. For another
Discord post, use **More recovery options → Republish** and confirm. A stopped
and restarted replay still uses the same saved intervals. Live capture events
are independent, so this recording safeguard does not suppress new live songs.

### Replaying recordings during development or demos

In **Results → Results capture**, enable **Allow repeat screenshots and Discord
posts from recordings**, then click **Apply results settings**.
The profile setting is `results.allow_replay_duplicates: true` (default `false`).
It applies without restarting capture and is saved with the profile. Each replay
can create a fresh result, uniquely named screenshot, and automatic Discord post.
Capture results and Discord publishing must still be enabled with a working webhook;
this setting does not override rehearsal mode or delivery errors.

A continuous results screen still creates only one result, even with the option
on. Seeking back, looping, or restarting the recording permits another result.
Enabling it while **Replay already saved** is displayed lets the next frames start
capture for that screen, so resume playback if paused. Changing this setting does
not discard an ongoing result's evidence. Turn it off after testing to restore
saved-interval protection, including intervals captured while it was enabled.
There is no need to delete screenshots or outbox metadata. Existing installations
need one full **Exit application…** and relaunch after updating to load the new backend;
closing and reopening only the desktop panel is insufficient.

Desktop/CLI profiles default to capture enabled, with readable PNG copies in
`results.output_directory` (default `screenshots`). Explicit `enabled: false`
settings remain off. The workbench retains its separate opt-in capture setting.
Export names use the event creation time in UTC, optional confirmed player names
(`include_player_names`, default true), and the event ID to prevent collisions.
Filename characters are sanitized for Windows. Disabled/unconfirmed names are
omitted. The exported path is recorded as `screenshot_export_path`; the original
`screenshot_path` remains in the durable outbox for Discord and recovery. Exports
run on the persistence worker after internal persistence. Export-folder failures
appear separately as `export_error` and do not prevent Discord delivery; failure to
persist the internal screenshot/metadata still prevents sending. Desktop folder changes affect new
results and do not move previous files or the outbox.

Delivery states are `saved`, `queued`, `sending`, `retrying`, `sent`, and `failed`.
Status reaches the workbench and WebSocket feed even when playback is paused.
Existing gameplay fields are preserved; an optional `results` field carries the
latest event and service status. The panel also exposes a recent event list and
`/api/results/<event_id>/screenshot`, resolving only known local records.

Discord receives the screenshot and compact embed with mentions disabled.
`wait=true` requires a successful message response and attachment confirmation.
An image referenced in an embed is confirmed through its Discord CDN image URL; Discord may omit it from the top-level attachment list. A known message ID without image confirmation fails visibly without automatic duplicate creation. A read-only webhook lookup supplies the guild ID for a message link when needed.
Connection/read timeouts are 3/10 seconds. Network errors, ambiguous timeouts,
5xx responses, and 429 rate limits retry up to five attempts. Backoff is
exponential; Discord's rate-limit delay takes precedence. Other 4xx responses
fail for manual intervention. Pending deliveries recover on restart.

Name edits use the same delivery worker and retry policy. Additive `revision`,
`delivery.delivered_revision`, and `name_update` metadata preserve pending edits
across restart and prevent old network responses from overwriting newer names.
An edit failure leaves the initial delivery marked sent. A changed webhook or deleted
message fails visibly; an edit never falls back to creating another post. Disabling
publishing pauses both sends and edits. Legacy records load without migration.

The desktop's collapsed **Recent results & recovery** section shows the newest 20
events plus older failed deliveries/name edits. Its quiet attention count includes
all such failures, separately from missing names. Expand it for saved/alternative
screenshots, Send saved result, Retry delivery, Retry name update, and a Discord
message link. Republish is secondary and asks before creating another post. Sending
requires an active results service and enabled publishing; stopped services retain
history in memory and persisted events recover on the next Start. Thumbnails are
requested only while the recovery section is visible and expanded.

Automatic retries intentionally favor delivery over exactly-once semantics: a
lost acknowledgement can produce a duplicate Discord post. Retries retain the
same event ID. EOF and shutdown seal retained evidence without waiting for an
in-flight OCR call; late OCR completions cannot alter that event. Shutdown waits
a bounded time for persistence and delivery. If disk writes or a request outlive
that wait, the worker retains outbox ownership until it stops; pending persisted
work recovers on restart. Disk failures are reported and never treated as
confirmed persistence.

## Reproduce validation

```bat
.venv\Scripts\python.exe -B tools\run_results_tests.py --model C:\code\ddrcv-results-publishing\.workbench\models\en_PP-OCRv5_rec_mobile.onnx --video C:\code\ddrcv\apps\scripts\2025-03-27_15-52-48.mkv
.venv\Scripts\python.exe -B tools\replay_results.py --video C:\code\ddrcv\apps\scripts\2025-03-27_15-52-48.mkv --model C:\code\ddrcv-results-publishing\.workbench\models\en_PP-OCRv5_rec_mobile.onnx --output .workbench\validation-new
```

The replay runner never sends to Discord. It exercises the real CLI loop and
workbench, checks HTTP screenshot access and paused feedback, and repeats the
interval to verify deduplication. Choose a fresh output directory for each run.
The test runner keeps temporary files inside this worktree.

The 255–278 second MKV window produced one confirmed screenshot at **262.0 s**
through each interface: **XETA 1,615**, **DANOOCT1 1,632**, **DANOOCT1 wins by 17 EX**.
The real-model test also masks the entire lower panel and requires unchanged
names/scores. Synthetic tests cover ties, zero, partial reads, source invalidation,
slow workers, HTTP failures, retry recovery, disk failures, and competing outbox owners.

Final focused validation passed **112 tests**, including the provisioned real OCR
model. The headless workbench check verified desktop/narrow layouts, correct
fields, disabled sending during rehearsal, and no JavaScript errors. A live
Discord message was verified read-only with its 1280x720 embedded screenshot.
The first live check exposed Discord's omission of inline images from
`message.attachments`; it produced six rehearsal posts before confirmation was
corrected. A regression test now covers the actual response shape, and the
existing message was reconciled without further posting. Detailed receipts and
screenshots remain under ignored `.workbench/validation/`.

Review-fix validation passed **117 tests** with the pinned model and MKV. New
regressions cover delivery-independent interval persistence, seek deduplication
during a stalled send, partial results at looping EOF (including blocked OCR),
and bounded shutdown with both OCR and disk writes in flight. The local CLI and
workbench replay each retained one confirmed frame at **262.0 s**, with the same
XETA 1,615 / DANOOCT1 1,632 result and 17-point P2 win. The workbench seek pass
remained deduplicated. Artifacts are under ignored
`.workbench/review-fixes-validation/`; no Discord messages were sent for this run.
