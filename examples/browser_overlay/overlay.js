/* Plain WebSocket snapshots. No API token, build step, external fonts or scripts. */
'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const placeholder = '—';
  const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  let socket = null, retryTimer = null, retryMs = 500, stopped = false;
  let lastReceived = null;

  function connection(kind, text) {
    $('status').dataset.connection = kind;
    $('connection').textContent = text;
  }

  function render(snapshot = {}) {
    const visible = ['song_playing', 'song_result'].includes(snapshot.state);
    for (let i = 0; i < 2; i++) {
      const key = `p${i + 1}`;
      const present = Array.isArray(snapshot.players) && snapshot.players[i] === true;
      const name = object(snapshot.player_names) ? snapshot.player_names[key] : null;
      const raw = object(snapshot.score) ? snapshot.score[`${key}_score`] : null;
      $(key).dataset.present = String(present);
      $(`${key}-name`).textContent = present && typeof name === 'string' && name.trim() ? name.trim() : key.toUpperCase();
      $(`${key}-score`).textContent = visible && present && Number.isSafeInteger(raw) && raw >= 0
        ? raw.toLocaleString('en-US') : placeholder;
    }
  }

  function clear() {
    render();
    lastReceived = null;
    $('received').textContent = '';
  }

  let feed;
  try {
    feed = new URL(new URLSearchParams(location.search).get('ws') ?? document.body.dataset.feed);
    if (!['ws:', 'wss:'].includes(feed.protocol) || feed.username || feed.password || feed.hash) throw Error();
  } catch {
    clear();
    connection('invalid', 'Invalid feed URL · use ws://host:port');
    return;
  }

  function reconnect() {
    if (stopped || retryTimer !== null) return;
    clear();
    connection('disconnected', 'Disconnected · reconnecting…');
    retryTimer = setTimeout(() => {
      retryTimer = null;
      connect();
    }, retryMs);
    retryMs = Math.min(retryMs * 2, 10000);
  }

  function connect() {
    if (stopped) return;
    connection('connecting', 'Connecting…');
    let current;
    try {
      current = new WebSocket(feed.href);
    } catch {
      reconnect();
      return;
    }
    socket = current;
    current.onopen = () => {
      if (socket !== current || stopped) return;
      connection('connected', 'Connected · waiting for state');
    };
    current.onmessage = event => {
      if (socket !== current || stopped) return;
      let snapshot;
      try { snapshot = JSON.parse(event.data); } catch { snapshot = null; }
      if (!object(snapshot) || typeof snapshot.state !== 'string') {
        clear();
        connection('invalid', 'Connected · invalid state');
        return;
      }
      retryMs = 500;
      // Every message replaces all displayed fields, including nulls and omissions.
      render(snapshot);
      lastReceived = Date.now();
      $('received').textContent = 'Received just now';
      const states = {song_playing: 'Gameplay', song_result: 'Song results', song_select: 'Song select',
        song_splash: 'Song splash', login: 'Login', total_result: 'Total results', unknown: 'Unknown screen'};
      const screen = Object.hasOwn(states, snapshot.state) ? states[snapshot.state] : 'Unknown screen';
      connection('connected', `Connected · ${screen}`);
    };
    current.onerror = () => {
      if (socket !== current || stopped) return;
      socket = null;
      current.close();
      reconnect();
    };
    current.onclose = () => {
      if (socket !== current || stopped) return;
      socket = null;
      reconnect();
    };
  }

  // Receive age is observational: the protocol has no capture heartbeat.
  const ageTimer = setInterval(() => {
    if (lastReceived !== null) {
      const seconds = Math.max(0, Math.floor((Date.now() - lastReceived) / 1000));
      $('received').textContent = `Received ${seconds}s ago`;
    }
  }, 1000);
  window.addEventListener('pagehide', () => {
    stopped = true;
    clearTimeout(retryTimer);
    clearInterval(ageTimer);
    if (socket) socket.close();
  });
  clear();
  connect();
})();
