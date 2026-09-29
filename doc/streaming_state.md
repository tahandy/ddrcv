# Streaming state: custom renderer integration

For an example client, see the [OBS browser overlay](../examples/browser_overlay/README.md).
For state-driven scene changes in an actual OBS collection, see the
[OBS scene-switching example](../examples/obs_scene_switching/README.md).

Connect to **`ws://127.0.0.1:9000`** to receive DDRCV's current state as JSON.
No subscription message, token, or request body is required. Each WebSocket
text message is a complete snapshot; replace your previous snapshot with it.

This document describes the maintained tournament desktop app, DDR World CLI
(`ddrcv.apps.driver_ddr`), and rehearsal workbench. It documents the current,
**unversioned** wire format. Legacy drivers and simulators can publish different
payloads; tolerate missing optional fields and ignore unknown fields.

## Connect

1. Start capture in the [desktop app](tournament_desktop.md), run the DDR World CLI,
   or launch the [workbench](tournament_handoff.md). Only one publisher can bind
   a given address and port. The workbench can publish simulated states without
   a camera or video.
2. Open a standard WebSocket connection to the publisher. Use the root URL above;
   this is plain WebSocket, not Socket.IO. There is no topic or subprotocol.
3. Parse each incoming text message as one JSON object. Render the latest
   snapshot and reconnect after the socket closes.

| Setting | Meaning |
| --- | --- |
| Desktop / CLI `publish.websocket.host` | Bind address; defaults to `localhost`. |
| Desktop / CLI `publish.websocket.port` | TCP port; defaults to `9000`. |
| Desktop / CLI `publish.websocket.delay` | Seconds between broadcast checks; defaults to `0.1`. This is not a guaranteed frame rate. |
| Desktop / CLI `publish.websocket.only_send_new` | Defaults to `true`; broadcast when the producer has submitted a snapshot since the last broadcast. This does **not** compare JSON values. |
| Workbench | Binds `127.0.0.1`; its publisher port is configurable under integrations. |

For a renderer on another machine, bind the desktop/CLI publisher to an interface
reachable from that machine, then connect to that machine's address, for example
`ws://192.168.1.20:9000`. `0.0.0.0` is a bind address, not a client destination.
This partial CLI/profile configuration exposes the publisher on all interfaces:

```json
{
  "publish": {
    "websocket": {
      "host": "0.0.0.0",
      "port": 9000,
      "delay": 0.1,
      "only_send_new": true
    }
  }
}
```

The feed has no authentication or TLS; use a trusted network and allow the port
through the host firewall when connecting remotely. There is no built-in `wss://`
endpoint. An HTTPS renderer page may block a plain `ws://` connection as mixed
content; use an appropriate local page or a TLS proxy. This port is separate
from the workbench HTTP UI (`5002`) and OBS WebSocket (`4455`).

## Delivery and freshness

- A new connection receives the latest retained snapshot immediately, if one
  exists. If the producer has not submitted anything yet, it waits for a snapshot.
- The publisher retains only the latest snapshot. Multiple submissions between
  broadcast checks collapse into one message. Do not rely on seeing every state
  transition or every score increment.
- Duplicate payloads are normal: each producer submission counts as new even
  when its values are unchanged. A connection can also receive the same snapshot
  during initial delivery and a broadcast. With `only_send_new=false`, the latest
  snapshot repeats even without producer submissions.
- There is no replay, acknowledgement, application heartbeat, or client command
  protocol. Sending JSON to this socket does not control capture or the renderer.
- No top-level timestamp, sequence number, session/song ID, schema version, or
  score mode is published. The internal song generation is not on the wire.
- An open socket does not prove that capture is advancing. Paused playback or
  capture loss can leave an old snapshot in place. Name/song/Results workers can also
  publish updates without a new video frame. Track connection state and local
  receive time separately; even repeated messages do not prove fresh gameplay.

Clear or visibly mark your display as disconnected when the socket closes.
On reconnect, replace the entire snapshot, including null and omitted optional
fields, so values from a previous session do not linger. A receive-time timeout
is a renderer policy, not a protocol-level guarantee of capture failure.

## Core payload

Illustrative two-player gameplay message (the optional `results` object is
omitted here):

```json
{
  "state": "song_playing",
  "players": [true, true],
  "song": null,
  "score": {"p1_score": 1234, "p2_score": 1200},
  "player_names": {"p1": "ALICE", "p2": "BOB"}
}
```

P1 is the left side of the captured game screen; P2 is the right side. Array
indices are always `[P1, P2]`, even when only P2 is present.

| Field | JSON type | Meaning |
| --- | --- | --- |
| `state` | string | Confirmed screen state; see the table below. |
| `players` | array of two booleans | Player presence inferred from the song splash, retained through gameplay/results. Defaults to `[true, true]` after reset, so it is not proof that both players have been observed. |
| `song` | object or null | Optional confirmed song identity and per-player charts. Null while disabled or unconfirmed. See Song and chart lifetime below. Legacy song-database payloads are outside this contract. |
| `score` | object or null | Latest filtered gameplay scores. `null` means no score object in the current session, including after a reset. |
| `score.p1_score`, `score.p2_score` | integer or null | Nonnegative raw score, `-1` for unread/reset before an accepted value, or `null` for an absent/unavailable side. `0` is a valid score. |
| `player_names` | object; tolerate omission | Maintained producers add `p1` and `p2`, each a string or `null`. Confirmed login/splash OCR names, not player IDs. |
| `results` | optional object | Background Results capture/delivery status and newest persisted record; described below. It can be absent, including when Results capture is disabled. |

State names are case-sensitive:

| `state` | Screen / renderer implication |
| --- | --- |
| `unknown` | No confirmed screen yet, or recognition has lost the screen. Previously accepted scores may remain. |
| `login` | Player login; starts a fresh score session. |
| `song_select` | Song selection; clears previous song/score data on entry. |
| `song_splash` | Pre-song splash; resets scores and determines player presence. |
| `song_playing` | Gameplay; score extraction is allowed only when the raw and confirmed states both agree on gameplay. |
| `song_result` | Per-song results; retains the last accepted gameplay scores. |
| `total_result` | Overall results; clears gameplay scores on entry. |

Unknown future state strings should have a safe fallback, such as hiding the
gameplay overlay. State confirmation is debounced, so published state can lag a
screen transition. Brief unknown intervals can retain the prior confirmed state.
Starting directly in gameplay without a preceding select/splash also resets the
score session. Manual score reset, source changes, and rehearsal seek/reset can
clear values; do not require scores to increase across the entire connection.

### Score units and missing reads

`score` contains the numbers read from gameplay, without normalization. Configure
your renderer for the same **Money or EX** mode as the producer/game display;
there is no top-level unit flag and no automatic score conversion. Do not infer
the mode from score magnitude, assume an EX maximum, or label the value as a
percentage. `results.latest.score_mode` describes that stored result only.

Within a score session, rejected decreases, implausible jumps, or unread digits
normally leave the previous accepted value in place. Money mode removes the EX
upward-jump limit. The feed does not include per-player score age, confidence,
raw readings, or rejection reasons. In particular, `song_result` plus a non-null
`score` is **not** confirmation that the final Results-screen score was read.

Render a blank/placeholder for `null`, missing fields, and negative scores. Never
coerce them to zero. For example, this snapshot has an unread P1 and an absent P2:

```json
{
  "state": "song_playing",
  "players": [true, false],
  "song": null,
  "score": {"p1_score": -1, "p2_score": null},
  "player_names": {"p1": null, "p2": null}
}
```

### Song and chart lifetime

Song recognition is opt-in. See [setup and catalog preparation](song_recognition.md).
The song object has song_id, title, artist, catalog, and charts.p1 / charts.p2.
Catalog includes mode, event, dataset, the pinned metadata commit, and the
qualified gallery fingerprint. Each chart is null until its difficulty confirms;
a confirmed record has style, difficulty, level, max_ex, status, and provenance.
Level comes from chart metadata, not template recognition of digits. Provenance
contains the dataset and commit supplying max EX, or null values when unavailable.

Identity and each player's chart confirm independently from two accepted
observations spanning at least 200 ms. A missing player read does not hold back
the other player or a confirmed song title. Shared artwork cannot establish a
unique identity. Recognized out-of-pool charts still publish their difficulty with
max_ex=null and status=chart_outside_pool. Conflicting metadata, unsupported artwork,
and missing scores also produce null max EX with an explanatory status.

Song/chart values persist through gameplay and per-song results, and clear at
song/session reset boundaries, source changes, and seeks. Background completion
can update the snapshot without another captured frame. Clients must honor null
and replace the complete song object, including its charts.

max_ex is always an EX maximum. It neither changes the score field's configured
units nor makes a Money score suitable for an EX percentage.

### Name lifetime

Login/splash name recognition is optional (`player_names.enabled`, default
`false`). `null` can mean disabled, not yet confirmed, absent, or failed; the
state feed does not distinguish these causes. Fall back to `P1` / `P2` labels.

Confirmed splash names persist through gameplay and per-song results, then clear
for the next song/session. Login names can persist into selection, but are not a
fallback for gameplay when the splash was missed. Always honor a new `null`;
do not carry the previous player's name forward. Results-screen name OCR is a
separate setting and appears inside `results.latest.players`, not here.

## Optional Results payload

`results` reports asynchronous screenshot/OCR/persistence/Discord work. It does
not replace `score`. It can update while gameplay is unchanged or capture is
paused. If Results initialization fails, the object can contain only
`{"phase": "failed", "error": "..."}`; read the other fields defensively.

| `results` field | Type / meaning |
| --- | --- |
| `phase` | String: `disabled`, `idle`, `settling`, `capturing`, `confirming`, `saving`, `saved`, `already_saved`, `single_player_skipped`, `ocr_failed`, or `failed`. This is capture/service status, not Discord delivery state. |
| `error` | Error string or `null`. |
| `enabled`, `discord`, `parse_names`, `screenshots_only`, `allow_replay_duplicates`, `rehearsal`, `webhook_configured` | Boolean configuration/status flags. `discord=true` alone does not mean a result has been sent. |
| `pending`, `replaced_frames`, `deduplicated` | Integer diagnostics: queued OCR episodes, replaced pending samples, and reused recorded results, respectively. |
| `needs_attention` | Number of persisted records with failed delivery or failed name updates; can include older records. |
| `last_sent_at` | Unix seconds of the latest successful send, or `null`. |
| `delivery_available` | Boolean: whether the outbox/service is available; not a network connectivity check. |
| `latest` | Newest persisted record by creation time, or `null`. Can be from an earlier song, source, or previous run. The stream does not contain full Results history. |

Useful fields in `results.latest`:

| Record field | Type / meaning |
| --- | --- |
| `event_id`, `source_id` | Opaque strings identifying the persisted result and its capture source. Neither identifies the current gameplay snapshot. |
| `recorded` | Boolean: whether the source was recorded video. |
| `score_mode` | `"ex"` or `"money"` for this record. |
| `players` | Two objects in P1/P2 order, each with `present` (boolean), `name` (string or `null`), and `score` (nonnegative integer or `null`). These are independent Results-screen readings; unavailable scores use `null`, not `-1`. |
| `partial` | Boolean: requested recognition was incomplete. A missing name alone can make this true. |
| `screenshots_only`, `parse_names`, `rehearsal` | Boolean policy flags captured for this record. In screenshots-only mode, names/scores are intentionally null and `partial` is false. |
| `screenshot_confirmed` | Boolean confirmation flag for the selected evidence; false indicates fallback/unconfirmed evidence. |
| `outcome` | Object with `kind` (`winner`, `tie`, or `unavailable`), `winner` (zero-based `0` for P1, `1` for P2, or `null`), and `margin` (integer or `null`). Currently computed only for EX with both players present and both scores known; Money yields `unavailable`. |
| `timestamp`, `interval` | Selected frame time and `[start, end]` in source seconds: video time for recordings, monotonic time for live capture. These are not Unix timestamps. |
| `frame_index` | Frame index for a recording, or `null` for live capture. |
| `created_at` | Unix seconds when the result was finalized. |
| `revision` | Integer record revision, initially `1`; can increase when names are enriched. It is not a stream sequence number. |
| `delivery` | Object with `state` (`saved`, `queued`, `sending`, `retrying`, `sent`, `failed`), `attempts`, `error`, `next_attempt` (Unix seconds, or `0`), `message_id`, `message_url`, and `delivered_revision`. Successful sends add `sent_at` (Unix seconds); receipt metadata may also be present. |
| `name_update` | Separate name-enrichment delivery status: `state` (`idle`, `queued`, `sending`, `retrying`, `failed`), `attempts`, `error`, and `next_attempt`. Successful updates return to `idle`. |
| `screenshot_path` | Filesystem path on the publisher's machine, not a URL or image bytes. |
| `output_directory`, `include_player_names` | Screenshot export configuration for this record. |
| `screenshot_export_path`, `export_error` | Optional exported path or export error. |
| `alternatives` | Array of alternative screenshot metadata (`id`, source `timestamp`, `frame_index`); no image bytes. |

Use `event_id` to avoid presenting a repeated record as a new result, but permit
updates for the same event (names, interval, export, and delivery status can
change). Do not assume every change increments `revision`. A newer gameplay
snapshot and an older `latest` record may coexist; there is no shared song ID to
join them automatically. See [Results publishing](results_publishing.md) for the
capture and recovery workflow.

## Browser / OBS browser-source example

Save this as an HTML file and load it as a local page or OBS browser source.
Change `FEED` for a remote publisher. It clears disconnected output, tolerates
optional fields, preserves zero, and replaces the snapshot on every message.
Name strings are assigned with `textContent`, so they cannot inject HTML.

```html
<!doctype html>
<meta charset="utf-8">
<title>DDRCV state client</title>
<p id="connection">Connecting…</p>
<pre id="scores"></pre>
<script>
const FEED = "ws://127.0.0.1:9000";
const connection = document.getElementById("connection");
const scores = document.getElementById("scores");
let retryMs = 500;

function render(snapshot) {
  const visible = ["song_playing", "song_result"].includes(snapshot.state);
  scores.textContent = visible ? [0, 1].map(i => {
    const key = `p${i + 1}`;
    if (snapshot.players?.[i] !== true) return "";
    const raw = snapshot.score?.[`${key}_score`];
    const value = Number.isInteger(raw) && raw >= 0 ? raw.toLocaleString() : "—";
    const name = snapshot.player_names?.[key] || `P${i + 1}`;
    return `${name}: ${value}`;
  }).filter(Boolean).join("\n") : "";
}

function connect() {
  connection.textContent = "Connecting…";
  const socket = new WebSocket(FEED);
  socket.onopen = () => {
    connection.textContent = "Connected; waiting for snapshot";
  };
  socket.onmessage = event => {
    let snapshot;
    try { snapshot = JSON.parse(event.data); } catch { return; }
    if (!snapshot || typeof snapshot.state !== "string") return;
    retryMs = 500;
    connection.textContent = `${snapshot.state} · received ${new Date().toLocaleTimeString()}`;
    render(snapshot);
  };
  socket.onerror = () => socket.close();
  socket.onclose = () => {
    connection.textContent = "Disconnected; reconnecting…";
    scores.textContent = "";
    setTimeout(connect, retryMs);
    retryMs = Math.min(retryMs * 2, 10000);
  };
}
connect();
</script>
```

The receive time above is local observation time, not capture time. This minimal
example does not age out an open-but-idle connection; choose that display policy
for your event. A paused rehearsal feed is allowed to be silent indefinitely.

## Python reader example

Use the installed DDRCV environment, or install `websockets` in your renderer's
environment (`python -m pip install websockets`). Save this as `state_client.py`
and run `python state_client.py`. No DDRCV imports are required.

```python
import asyncio
import json
import websockets

URI = "ws://127.0.0.1:9000"

async def main():
    retry = 0.5
    while True:
        try:
            async with websockets.connect(URI, open_timeout=5, close_timeout=1) as ws:
                print("Connected; waiting for snapshot", flush=True)
                async for message in ws:
                    try:
                        snapshot = json.loads(message)
                    except (ValueError, TypeError):
                        continue
                    if not isinstance(snapshot, dict):
                        continue
                    retry = 0.5
                    # Replace your renderer model here; don't merge old fields.
                    print(json.dumps(snapshot, ensure_ascii=False), flush=True)
        except (OSError, TimeoutError, websockets.exceptions.WebSocketException) as exc:
            print(f"Feed unavailable: {exc}", flush=True)
        # Also back off after a graceful close.
        print("Disconnected; clear/mark renderer output", flush=True)
        await asyncio.sleep(retry)
        retry = min(retry * 2, 10)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
```

## Integration checks

In the workbench, simulate gameplay with two players, only P2, a zero score, and
an unread (`-1`) score. Then simulate selection, results, and unknown state.
Simulation accepts manually supplied scores even outside gameplay; recorded/live
recognition follows the lifetime rules above. A still image is diagnostic-only
and does not advance confirmed gameplay scores.

Connect after a snapshot is already published to check initial delivery. Stop
and restart the publisher to check reconnection and clearing old names/scores.
Finally, rehearse select → splash → gameplay → results with recorded footage or
live capture to verify the actual state and score lifecycle.

Implementation references for maintaining this document:
[publisher](../ddrcv/publish/websocket_publisher.py),
[session lifetime](../ddrcv/apps/tournament_session.py),
[score filter](../ddrcv/score/temporal.py),
[runtime envelope](../ddrcv/apps/tournament_runtime.py),
[workbench producer](../ddrcv/workbench/controller.py),
[name service](../ddrcv/state/player_names.py),
[Results service](../ddrcv/results/service.py), and
[Results records/delivery](../ddrcv/results/delivery.py).
