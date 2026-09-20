# OBS browser overlay example

This standalone example shows how to consume DDRCV's
[WebSocket state feed](../../doc/streaming_state.md): P1/P2 names, raw gameplay
scores, connection status, and time since the last received snapshot. The HTML,
CSS, and JavaScript are a starting point for your own renderer. They use no
external assets, build step, or desktop API, and are not installed in the DDRCV
Python package. Find the example in the repository or source distribution.

For a complete OBS scene collection that switches with these states, see the
[scene-switching example](../obs_scene_switching/README.md).

## OBS setup

1. Start capture in the DDRCV desktop app, CLI, or workbench so the publisher
   is running. The example defaults to `ws://127.0.0.1:9000`.
2. Open `examples/browser_overlay/index.html` in a browser to preview it.
3. In OBS, add a **Browser** source, enable **Local file**, and choose that
   `index.html`. Set **Width: 960**, **Height: 240** and position it over your
   video source. The page background is transparent; the cards are dark.
4. Leave **Shutdown source when not visible** off to keep the connection through
   scene changes. If enabled, the source reconnects when shown. Use **Refresh
   cache of current page** after changing the files. See the
   [OBS Browser Source guide](https://obsproject.com/kb/browser-source).
5. Check both names and scores against the actual game, including a zero score,
   a one-player song, a song transition, and a publisher stop/restart.

Keep `overlay.js` and `overlay.css` beside `index.html`. You can copy these three
files to your own folder and customize them. Closing the desktop panel leaves
capture and the feed running; stopping capture or exiting disconnects the feed.
The existing external renderer integration operates independently of this example.

## Custom connections

Change `data-feed` on the HTML `<body>` to your WebSocket URL, or run the optional
standard-library Python utility from the repository root to make a configured copy:

```bat
python examples/browser_overlay/prepare.py obs-overlay --feed ws://127.0.0.1:9010
```

The script prints the absolute path to the generated `index.html`. Select it as
OBS's local file. Preparing again replaces only the three example assets in the
output folder, so keep custom designs elsewhere. The script runs without DDRCV
installed and does not read desktop configuration; supply the publisher's actual
address and port. After changing the feed, refresh the OBS source.

A browser URL may override the file's endpoint using
`?ws=ws%3A%2F%2F127.0.0.1%3A9010`. Only `ws://` and `wss://` URLs are accepted.
Connect to `127.0.0.1` for an IPv4 publisher bound to `0.0.0.0` on this computer,
or `[::1]` for an IPv6 publisher bound to `::`. For OBS on another computer, copy
all three files there and configure the DDRCV computer's reachable address,
following the feed specification's network setup instructions.

## Display behavior and troubleshooting

- Scores appear during `song_playing` and `song_result`. Other states, including
  unknown future states, show placeholders. Per-song results retain the last
  gameplay score; this is not independent confirmation of the Results-screen score.
- `0` is valid. Missing, null, negative, nonnumeric, fractional, or unsafe integer
  values show `—`. Each snapshot replaces the entire display; resets can lower or
  clear a score. Absent or unspecified players show dimmed P1/P2 placeholders.
- Missing, empty, or invalid names fall back to P1/P2. Confirmed names come from
  `player_names`, so enable **Read names on login/song splash** if desired.
  The separate Results name reader does not populate this overlay.
- Numbers have thousands separators, with no percentage, inferred maximum, or
  EX/Money conversion. The producer/game must use the intended score mode.
- Disconnects immediately clear scores and names. Retries back off from 0.5 to
  10 seconds, resetting after a valid snapshot. Invalid messages clear the
  display and show **Connected · invalid state** until a valid snapshot arrives.
- **Connected** describes the socket only. **Received Ns ago** measures local
  message age, not capture freshness. There is no heartbeat in the feed, so a
  silent connection is allowed and does not automatically erase the snapshot.
  Check the desktop's capture status when the image or scores appear frozen.
- **Disconnected**: start capture; check the publisher address/port, then prepare
  again and refresh OBS if settings changed. **Connected · waiting for state**:
  the socket is open but no snapshot has arrived. Publisher client counts include
  both the preview browser and OBS; close the preview when finished checking.

## Focused validation

From the repository root, run the example asset and utility tests:

```bat
.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_browser_overlay.py -v
```

`tests/test_browser_overlay_ui.py` additionally runs the real page against
`WebSocketPublisher`, including retained snapshots, resets, disconnect/reconnect,
malformed messages, transparency, long names, and bounded reconnection retries. Install
Playwright in a test environment and run `python -m playwright install chromium`,
then use unittest discovery for that file. Set `DDRCV_TEST_BROWSER_CHANNEL=msedge`
to use an installed Microsoft Edge instead. Browser tests skip when Playwright
is absent; they are not runtime dependencies. A browser pass does not replace
the OBS scene rehearsal above.
