# Results capture and Discord delivery

The tournament CLI and workbench use the same background results service. It reads
player names and the **large score**, captures the supporting clean frame, and
publishes a compact Discord embed. Lower-panel tabs, judgments, difficulty, stage,
and song lookup are not prerequisites.

## Run this worktree

Use the Python environment inside this checkout. Optional OCR dependencies are
installed with `python -m pip install -r requirements-ocr.txt` in addition to the
workbench dependencies. No changes to another checkout's environment are needed.

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
.venv\Scripts\python.exe -B -m ddrcv.apps.driver_ddr_tbd5 --video C:\code\ddrcv\apps\scripts\2025-03-27_15-52-48.mkv --score-mode ex
```

Run from this checkout's root. The default outbox is `.workbench/results`;
`results.outbox_directory` overrides it for the CLI. Do not run two instances
against the same outbox at once: the second reports that it is already in use.
Independent rehearsal runs should use a separate workbench `--data-dir` or CLI
outbox. An OS lock releases automatically when its owner exits or crashes.

### Configuration

Example (without credentials):

```json
{
  "enabled": true,
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

The first fully confirmed result is finalized once. At ten seconds or departure,
the latest assessed results frame is retained with its confirmed fields. No
values are copied from another screenshot. If the screen leaves before OCR can
settle, the retained screenshot is explicitly marked unconfirmed. Missing values
stay null, not zero or -1. Zero is a valid score.

Two confirmed EX scores permit a winner/margin or **TIE**, even if a missing name
must be shown as P1/P2. Confirmed single-player results have no competitive
outcome. Confidence is not proof of correctness; the MKV validation covers one
recording and two names, not arbitrary captures or layouts.

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
