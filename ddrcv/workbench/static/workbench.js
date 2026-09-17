'use strict';
const $ = id => document.getElementById(id);
const stateNames = {
  unknown: 'Unknown', login: 'Login', song_select: 'Song select', song_splash: 'Song splash',
  song_playing: 'Gameplay', song_result: 'Song results', total_result: 'Total results'
};
const reasons = {
  accepted: 'Accepted', jump_limit: 'Increase exceeds EX limit', decrease: 'Lower than accepted score',
  no_digits: 'No digits found', no_read: 'No reading yet', absent: 'Player absent',
  diagnostic_only: 'Image diagnostics only', not_gameplay: 'Waiting for confirmed gameplay'
};
const errors = new Map(), dismissedErrors = new Map();
let initialized = false, lastSequence = -1, lastImages = 0, polling = false, obsPolling = false;
let shutdown = false, current = null, noticeTimer = null, stickyNotice = false;
try { $('show-regions').checked = localStorage.getItem('ddrcv.show-regions') === 'true'; } catch {}
$('show-regions').onchange = () => {
  try { localStorage.setItem('ddrcv.show-regions', String($('show-regions').checked)); } catch {}
  lastSequence = -1;
  poll();
};
const text = (id, value) => { $(id).textContent = value ?? '—'; };
const screenName = state => stateNames[state] || state || '—';
const scoreText = value => value === -1 ? 'Unread' : value ?? '—';
function timeText(seconds) {
  const milliseconds = Math.max(0, Math.round((Number(seconds) || 0) * 1000));
  return `${String(Math.floor(milliseconds / 60000)).padStart(2, '0')}:${String(Math.floor(milliseconds / 1000) % 60).padStart(2, '0')}.${String(milliseconds % 1000).padStart(3, '0')}`;
}
function seekSeconds(value) {
  const match = value.trim().match(/^(?:(\d+):)?(\d+(?:\.\d+)?)$/);
  if (!match || (match[1] !== undefined && Number(match[2]) >= 60)) {
    throw new Error('Enter a time such as 02:14.500, or a number of seconds.');
  }
  return Number(match[1] || 0) * 60 + Number(match[2]);
}
function notice(message, sticky = false) {
  if (stickyNotice && !sticky) return;
  clearTimeout(noticeTimer);
  stickyNotice = sticky;
  text('notice-text', message);
  $('notice').hidden = false;
  if (!sticky) noticeTimer = setTimeout(() => { $('notice').hidden = true; }, 5000);
}
function renderError() {
  const latest = [...errors.values()].at(-1);
  text('error-text', latest);
  $('error').hidden = !latest;
}
function fail(message, key = 'command') {
  // An action error can arrive again in the next status poll.
  if (dismissedErrors.get(key) === message || (key === 'server' && [...dismissedErrors.values()].includes(message))) return;
  errors.set(key, message);
  renderError();
}
function clearError(key) {
  errors.delete(key);
  dismissedErrors.delete(key);
  renderError();
}
function report(error) { fail(error.message, error.control || 'command'); }
async function post(url, data = {}) {
  dismissedErrors.delete(url);
  try {
    const response = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Rehearsal': '1'}, body: JSON.stringify(data)});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || response.statusText);
    clearError(url);
    return result;
  } catch (error) { error.control = url; throw error; }
}
const action = (name, args = {}) => post('/api/action', {action: name, ...args});
function bind(id, fn) {
  $(id).addEventListener('click', () => { dismissedErrors.delete('command'); Promise.resolve().then(fn).catch(report); });
}
function option(value, label = value) {
  const node = document.createElement('option'); node.value = value; node.textContent = label; return node;
}
function sourceControls() {
  const kind = $('kind').value, file = kind === 'video' || kind === 'image';
  $('browse').hidden = !file;
  $('cameras').hidden = kind !== 'camera';
  $('camera-list').hidden = kind !== 'camera' || !$('camera-list').childNodes.length;
  text('path-label', file ? 'File path' : kind === 'camera' ? 'Device index' : 'RTSP URL');
  $('path').placeholder = file ? 'Choose a local recording or image' : kind === 'camera' ? 'Find cameras or enter an index' : 'rtsp://…';
  $('path').inputMode = kind === 'camera' ? 'numeric' : 'text';
}
function modeHelp(mode) {
  text('mode-help', mode === 'ex' ? 'EX: increases limited to 12 points per game frame.' : 'Money: no upward score limit.');
}
for (const [state, name] of Object.entries(stateNames)) {
  $('sim-state').append(option(state, name));
  if (state === 'unknown') continue;
  const label = document.createElement('label'); label.textContent = name;
  const input = document.createElement('input'); input.id = 'map-' + state;
  input.setAttribute('list', 'obs-scenes'); input.placeholder = 'Hold current scene';
  label.append(input); $('scene-map').append(label);
}
$('sim-state').value = 'song_playing';
text('clean-url', location.origin + '/video');
$('kind').onchange = sourceControls;
$('source-form').addEventListener('submit', event => {
  event.preventDefault();
  action('open', {kind: $('kind').value, path: $('path').value, resize_to_720p: $('resize').checked}).catch(report);
});
bind('browse', async () => {
  const data = await post('/api/browse');
  if (data.path) {
    $('path').value = data.path;
    $('kind').value = /\.(png|jpe?g|bmp)$/i.test(data.path) ? 'image' : 'video';
    sourceControls();
  }
});
bind('cameras', async () => {
  const result = await fetch('/api/cameras').then(r => r.json());
  if (result.error) throw new Error(result.error);
  $('camera-list').replaceChildren();
  for (const camera of result) {
    const button = document.createElement('button'); button.textContent = `${camera.index}: ${camera.name}`;
    button.onclick = () => { $('path').value = camera.index; $('path').focus(); };
    $('camera-list').append(button);
  }
  if (!result.length) $('camera-list').textContent = 'No cameras found. Connect a device and try again.';
  sourceControls();
});
for (const button of document.querySelectorAll('[data-action]')) {
  button.onclick = () => action(button.dataset.action).catch(report);
}
bind('play-toggle', () => action(current?.playing ? 'pause' : 'play'));
function playback() {
  action('playback', {speed: Number($('speed').value), loop: $('loop').checked}).catch(report);
}
$('speed').onchange = playback;
$('loop').onchange = playback;
$('score-mode').onchange = () => action('score_mode', {mode: $('score-mode').value}).then(() => {
  modeHelp($('score-mode').value); notice('Score mode changed. Previous readings cleared.');
}).catch(report);
$('timeline').onchange = () => action('seek', {seconds: Number($('timeline').value)}).catch(report);
async function seek() {
  const seconds = seekSeconds($('seek-time').value);
  await action('seek', {seconds});
  $('seek-time').value = timeText(seconds);
  clearError('command');
}
bind('seek', seek);
$('seek-time').onkeydown = event => { if (event.key === 'Enter') { event.preventDefault(); seek().catch(report); } };
bind('notice-dismiss', () => { clearTimeout(noticeTimer); stickyNotice = false; $('notice').hidden = true; });
bind('error-dismiss', () => { for (const [key, value] of errors) dismissedErrors.set(key, value); errors.clear(); renderError(); });
bind('snapshot', async () => { const data = await post('/api/snapshot'); notice('Snapshot saved: ' + data.path, true); });
bind('checks', async () => {
  const checks = await post('/api/checks');
  $('check-results').hidden = false; $('check-list').replaceChildren();
  for (const check of checks) {
    const line = document.createElement('div'); line.className = 'check-item' + (check.ok === false ? ' warning' : '');
    line.textContent = `${check.ok === null ? 'Optional' : check.ok ? 'OK' : 'Check'} — ${check.name}: ${check.detail}`;
    $('check-list').append(line);
  }
  $('check-results').scrollIntoView({block: 'nearest'});
});
bind('checks-dismiss', () => { $('check-results').hidden = true; $('checks').focus(); });
bind('renderer-browse', async () => { const data = await post('/api/browse', {directory: true}); if (data.path) $('renderer-path').value = data.path; });
bind('renderer-start', () => post('/api/renderer', {action: 'start', path: $('renderer-path').value}));
bind('renderer-stop', () => post('/api/renderer', {action: 'stop'}));
bind('publisher-start', () => action('publisher', {port: Number($('port').value)}));
bind('simulate', () => action('simulate', {state: $('sim-state').value, p1_present: $('sim-p1-present').checked, p2_present: $('sim-p2-present').checked, p1_score: Number($('sim-p1').value), p2_score: Number($('sim-p2').value)}));
bind('obs-connect', () => {
  const scene_map = {};
  for (const state of Object.keys(stateNames)) if (state !== 'unknown') scene_map[state] = $('map-' + state).value || null;
  const data = {action: 'connect', host: $('obs-host').value, port: Number($('obs-port').value), scene_map};
  if ($('obs-password').value) data.password = $('obs-password').value;
  return post('/api/obs', data).then(() => { $('obs-password').value = ''; notice('OBS connected. Automation is paused.'); });
});
bind('obs-check', () => post('/api/obs', {action: 'check'}));
bind('obs-enable', () => post('/api/obs', {action: 'automation', enabled: true}));
bind('obs-pause', () => post('/api/obs', {action: 'automation', enabled: false}));
bind('obs-disconnect', () => post('/api/obs', {action: 'disconnect'}));
bind('obs-manual', () => post('/api/obs', {action: 'scene', name: $('manual-scene').value}));
bind('logs-refresh', async () => { const data = await fetch('/api/logs').then(r => r.json()); if (data.error) throw new Error(data.error); text('logs', data.join('\n')); });
bind('shutdown', async () => { await post('/api/shutdown'); shutdown = true; notice('Workbench stopped. You may close this tab.', true); });
bind('results-apply', async () => {
  const values = {enabled: $('results-enabled').checked, discord: $('results-discord').checked,
    rehearsal: $('results-rehearsal').checked};
  if ($('results-webhook').value) values.webhook = $('results-webhook').value;
  await action('results_config', values);
  $('results-webhook').value = '';
  notice('Results settings saved.');
});
let resultsInitialized = false, resultsVersion = '';
function renderResults(status) {
  if (!status) return;
  if (!resultsInitialized) {
    $('results-enabled').checked = status.enabled;
    $('results-discord').checked = status.discord;
    $('results-rehearsal').checked = status.rehearsal;
    resultsInitialized = true;
  }
  text('results-status', `${status.phase} · ${status.webhook_configured ? 'Webhook configured' : 'No webhook'}${status.error ? ' · ' + status.error : ''}`);
  const version = JSON.stringify([status.records, status.discord, status.webhook_configured]);
  if (version === resultsVersion) return;
  resultsVersion = version;
  $('results-list').replaceChildren();
  for (const record of [...status.records].reverse()) {
    const card = document.createElement('article'); card.className = 'result-card';
    const image = document.createElement('img'); image.alt = 'Saved results screenshot';
    image.src = `/api/results/${encodeURIComponent(record.event_id)}/screenshot`;
    image.loading = 'lazy';
    const details = document.createElement('div');
    const heading = document.createElement('h3');
    heading.textContent = record.players.map((p, i) => p.present ? (p.name || `P${i+1} (name unread)`) : `P${i+1} absent`).join(' vs ');
    const scores = document.createElement('p');
    scores.textContent = `${record.score_mode.toUpperCase()}: ` + record.players.map(p => p.present ? (p.score?.toLocaleString() ?? 'unconfirmed') : 'absent').join(' / ');
    const winner = document.createElement('p');
    const o = record.outcome;
    winner.textContent = o.kind === 'tie' ? 'TIE' : o.kind === 'winner' ? `Winner: ${record.players[o.winner].name || 'P'+(o.winner+1)} (+${o.margin} EX)` : 'No confirmed competitive outcome';
    const delivery = document.createElement('p'); delivery.setAttribute('role', 'status');
    delivery.textContent = `${record.delivery.state} · attempts: ${record.delivery.attempts}${record.delivery.error ? ' · '+record.delivery.error : ''}`;
    const evidence = document.createElement('p'); evidence.className = 'muted';
    evidence.textContent = `${record.partial ? 'Partial result' : 'Confirmed result'} · ${record.screenshot_confirmed ? 'Stable screenshot' : 'Screenshot stability unconfirmed'} · ${timeText(record.timestamp)} · ${record.event_id}`;
    details.append(heading, scores, winner, delivery, evidence);
    if (record.delivery.message_url) {
      const link = document.createElement('a'); link.href = record.delivery.message_url;
      link.textContent = 'Open Discord message'; link.target = '_blank'; link.rel = 'noopener'; details.append(link);
    }
    const state = record.delivery.state;
    if (['saved', 'failed', 'sent'].includes(state)) {
      const button = document.createElement('button'); button.textContent = state === 'sent' ? 'Republish this result' : state === 'saved' ? 'Publish saved result' : 'Retry delivery';
      button.disabled = !status.discord || !status.webhook_configured;
      button.onclick = () => action(state === 'sent' ? 'results_republish' : 'results_retry', {event_id: record.event_id}).catch(report);
      details.append(button);
    }
    card.append(image, details); $('results-list').append(card);
  }
}
function init(settings) {
  $('kind').value = settings.source.kind; $('path').value = settings.source.path;
  $('resize').checked = settings.source.resize_to_720p; $('score-mode').value = settings.score_mode;
  $('renderer-path').value = settings.renderer_path; $('port').value = settings.port;
  $('obs-host').value = settings.obs.host; $('obs-port').value = settings.obs.port;
  for (const state of Object.keys(stateNames)) if (state !== 'unknown') $('map-' + state).value = settings.obs.scene_map[state] || '';
  sourceControls(); modeHelp(settings.score_mode); initialized = true;
}
function playbackControls(s) {
  const kind = s.source.kind, video = kind === 'video', live = kind === 'camera' || kind === 'rtsp';
  const ready = video || live, hasFrame = Boolean(s.diagnostics);
  $('play-toggle').disabled = !ready;
  text('play-toggle', s.playing ? 'Pause' : s.phase === 'Ended' ? 'Replay' : 'Play');
  for (const name of ['restart', 'step']) document.querySelector(`[data-action="${name}"]`).disabled = !video;
  document.querySelector('[data-action="stop"]').disabled = !kind;
  for (const id of ['speed', 'loop', 'timeline', 'seek-time', 'seek']) $(id).disabled = !video;
  $('snapshot').disabled = !hasFrame;
  $('show-regions').disabled = !hasFrame;
  $('regions-legend').hidden = !hasFrame || !$('show-regions').checked;
  $('renderer-stop').disabled = !s.renderer.running;
  if (document.activeElement !== $('speed')) $('speed').value = String(s.speed);
  $('loop').checked = s.loop;
}
async function poll() {
  if (polling || shutdown) return;
  polling = true;
  try {
    const response = await fetch('/api/status');
    if (!response.ok) throw new Error(response.statusText);
    const s = await response.json(); current = s;
    if (!initialized) init(s.settings);
    clearError('connection');
    playbackControls(s);
    renderResults(s.results);
    text('phase', s.phase === 'Simulation' ? 'Simulation — recognition bypassed' : s.phase === 'Image' ? 'Still image' : s.phase);
    $('phase').classList.toggle('simulation', s.phase === 'Simulation');
    text('position', `${timeText(s.position)} / ${timeText(s.source.duration)}`);
    if (document.activeElement !== $('timeline')) $('timeline').value = s.position;
    $('timeline').max = s.source.duration || 1;
    const path = s.source.path || '';
    const name = ['video', 'image'].includes(s.source.kind) ? path.split(/[\\/]/).pop() : s.source.kind === 'camera' ? 'Camera ' + path : s.source.kind === 'rtsp' ? 'RTSP stream' : '';
    const sourceInfo = name + (s.source.width ? ` · ${s.source.width} × ${s.source.height}${s.source.resized ? ' → 1280 × 720' : ''}` : '');
    text('source-info', sourceInfo); $('source-info').title = path;
    const d = s.diagnostics || {}, simulated = s.phase === 'Simulation';
    text('raw-state', simulated ? 'Simulated' : screenName(d.raw_state));
    text('confirmed-state', screenName(s.published.state)); text('frame-index', d.frame_index);
    const confirmation = d.stateless ? 'Image diagnostics only. Scores are not published.' : d.warming_up ? 'Warming up: collecting frames to confirm this screen.' : '';
    text('confirmation', confirmation); $('confirmation').hidden = !confirmation;
    for (const [i, player] of ['p1', 'p2'].entries()) {
      text(player + '-presence', !s.source.kind ? '—' : s.published.players?.[i] ? 'Present' : 'Absent');
      text(player + '-raw', scoreText(d.raw_scores?.[player + '_score']));
      text(player + '-published', scoreText(s.published.score?.[player + '_score']));
      const reason = d.decisions?.[player + '_score'];
      text(player + '-decision', simulated ? 'Simulated' : reasons[reason] || reason);
      $(player + '-decision').className = ['jump_limit', 'decrease', 'no_digits'].includes(reason) ? 'warning' : '';
      const glyphs = [...(d.glyphs?.[player + '_debug'] || [])].sort((a, b) =>
        (a.location?.[0] ?? a.bounding_box?.[0] ?? 0) - (b.location?.[0] ?? b.bounding_box?.[0] ?? 0));
      text(player + '-glyphs', glyphs.length ? 'Digit match: ' + glyphs.map(g => `${g.glyph_class} (${Number(g.match_value).toFixed(3)})`).join(' · ') : s.diagnostics ? 'No digit matches' : 'No frame');
    }
    text('performance', s.diagnostics ? `${s.processing_ms.toFixed(1)} ms/frame · ${s.actual_fps} frames/s${s.lagging ? ' · Below requested speed; every frame is kept.' : ''}` : simulated ? 'Simulation is active. Open a source to return to recognition.' : 'Playback is silent. Every recorded frame is processed.');
    $('performance').title = `Video decode: ${s.decode_ms ?? 0} ms; recognition and publication: ${s.recognition_ms ?? 0} ms. Preview delivery runs separately, up to 30 fps.`;
    $('performance').className = s.lagging ? 'warning' : 'muted';
    text('message', JSON.stringify(s.published, null, 2));
    text('feed-status', s.publisher.running ? `Score feed :${s.publisher.port} · ${s.publisher.clients} subscriber${s.publisher.clients === 1 ? '' : 's'}` : 'Score feed stopped: ' + (s.publisher.error || 'not started'));
    text('renderer-status', s.renderer.running ? 'Renderer process: running' : `Renderer process: stopped${s.renderer.exit_code !== null ? ' (exit ' + s.renderer.exit_code + ')' : ''}`);
    text('capture-age', !s.diagnostics || s.frame_age === null ? '' : !s.playing ? 'Playback held at the displayed frame.' : `Last frame ${s.frame_age.toFixed(1)}s ago${s.frame_age > 2 ? ' — check capture' : ''}`);
    if (s.error) fail(s.error, 'server'); else clearError('server');
    // Video delivery is independent of the slower diagnostic/status polling.
    // Replacing the JPEG URL here used to cap the entire preview at 4 fps.
    const previewURL = `/stream.mjpg?view=${$('show-regions').checked ? 'monitored' : 'clean'}`;
    $('preview').hidden = !s.diagnostics;
    if (s.diagnostics) {
      if ($('preview').getAttribute('src') !== previewURL) $('preview').src = previewURL;
    } else $('preview').removeAttribute('src');
    if (s.sequence !== lastSequence && performance.now() - lastImages > 90) {
      lastSequence = s.sequence; lastImages = performance.now();
      for (const [id, view] of [['p1-crop', 'p1'], ['p2-crop', 'p2']]) {
        $(id).hidden = !s.diagnostics;
        if (s.diagnostics) $(id).src = `/frame.jpg?view=${view}&sequence=${s.sequence}`; else $(id).removeAttribute('src');
      }
    }
    $('preview-empty').hidden = Boolean(s.diagnostics);
    text('preview-empty', simulated ? 'Simulation active — no video source' : 'Choose a video or image, then open the source.');
  } catch (error) { fail('Panel disconnected: ' + error.message, 'connection'); }
  finally { polling = false; }
}
async function pollObs() {
  if (obsPolling || shutdown) return;
  obsPolling = true;
  try {
    const response = await fetch('/api/obs');
    if (!response.ok) throw new Error(response.statusText);
    const data = await response.json();
    text('obs-status', data.connected ? `OBS connected · automation ${data.automation ? 'enabled' : 'paused'}` : 'OBS: not connected (optional)');
    text('obs-detail', data.error || `Current scene: ${data.actual_scene || '—'}`);
    $('obs-detail').className = data.error ? 'warning' : 'muted';
    for (const id of ['obs-check', 'obs-disconnect', 'manual-scene']) $(id).disabled = !data.connected;
    $('obs-enable').disabled = !data.connected || data.automation;
    $('obs-pause').disabled = !data.connected || !data.automation;
    $('obs-manual').disabled = !data.connected || !data.scenes.length;
    const names = JSON.stringify(data.scenes);
    if ($('manual-scene').dataset.names !== names) {
      $('manual-scene').replaceChildren(...data.scenes.map(name => option(name)));
      $('obs-scenes').replaceChildren(...data.scenes.map(name => option(name)));
      $('manual-scene').dataset.names = names;
    }
  } catch { text('obs-status', 'OBS status unavailable'); }
  finally { obsPolling = false; }
}
setInterval(poll, 250); setInterval(pollObs, 1500); poll(); pollObs();
