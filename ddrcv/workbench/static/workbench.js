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
let panelConnection = null;
function connectPanel() {
  if (!shutdown && !panelConnection) panelConnection = new EventSource('/api/panel');
}
function disconnectPanel() {
  panelConnection?.close();
  panelConnection = null;
}
window.addEventListener('pagehide', disconnectPanel);
window.addEventListener('pageshow', connectPanel);
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
bind('shutdown', async () => { await post('/api/shutdown'); shutdown = true; disconnectPanel(); notice('Workbench stopped. You may close this tab.', true); });
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
  const song = settings.song_lookup || {};
  $('song-enabled').checked = !!song.enabled;
  $('song-mode').value = song.mode || 'event';
  $('song-event').value = song.event || 'dia_del_ritmo_26';
  $('song-style').value = song.style || 'single';
  $('song-difficulty').value = song.difficulty_method || 'template';
  $('song-assets').value = song.catalog_file || '';
  $('song-qos').checked = song.high_qos !== false;
  sourceControls(); modeHelp(settings.score_mode); initialized = true;
  queueCatalogInfo(0);
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
      text(player + '-name', s.published.player_names?.[player]);
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
    // Poll name updates even while the frame sequence is held or capture is lost.
    const song = s.published.song;
    text('song-title', song ? song.title + (song.artist ? ' · ' + song.artist : '') : 'Song: —');
    text('song-charts', ['p1', 'p2'].map(p => {
      const chart = song?.charts?.[p];
      return p.toUpperCase() + ': ' + (chart ? chart.difficulty + ' · ' + chartExplanation(chart) : '—');
    }).join(' · '));
    showCatalogStatus(s.catalog_preparation || {}, s.song_lookup_status || {});
    const names = s.player_name_status || {};
    const namePhases = {disabled: 'Disabled', initializing: 'Loading OCR model', ready: 'Ready', failed: 'OCR failed', closed: 'Stopped'};
    text('name-status', namePhases[names.phase] || 'Unavailable');
    text('name-error', names.error); $('name-error').hidden = !names.error;
    text('name-screen', names.screen ? screenName(names.screen) : null);
    text('name-worker', names.busy ? 'Reading names' : names.phase === 'ready' ? 'Idle' : null);
    text('name-pending', names.pending);
    text('name-replaced', names.replaced_samples);
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
connectPanel();
setInterval(poll, 250); setInterval(pollObs, 1500); poll(); pollObs();

function songConfig() {
  return {...current?.settings?.song_lookup, enabled: $('song-enabled').checked, mode: $('song-mode').value,
    event: $('song-event').value, style: $('song-style').value,
    difficulty_method: $('song-difficulty').value, catalog_file: $('song-assets').value || null,
    high_qos: $('song-qos').checked};
}
const catalogConfig = songConfig;
function catalogEnvironment() {
  const runtime = current?.song_lookup_status || {}, source = current?.source || {};
  const running = !!source.kind && current?.phase !== 'Simulation';
  return {runtime, applied: current?.settings?.song_lookup || {}, running, starting: false,
    readyText: 'Ready to apply — use Apply / reset recognition below.',
    appliedText: 'Recognition configured — open a camera or video on Playback and setup.',
    pendingText: 'Changes pending — use Apply / reset recognition.',
    activeText: source.kind === 'image' ? 'Still image diagnostics — use video or a camera for live confirmation.' : !current?.playing ? 'Recognition ready — resume playback to read song splashes.' : null,
    button: 'Apply / reset recognition', help: 'Applies song settings and resets recognition and current tracking. ' +
      (!source.kind || current?.phase === 'Simulation' ? 'Then use Playback and setup to open a camera or video.' :
       source.kind === 'image' ? 'A still image is diagnostic only; open a video or camera on Playback for live confirmation.' :
       !current?.playing ? 'Playback is paused; use Play on Playback and setup to continue.' : 'Recognition uses the next song splash.')};
}
function requestCatalogInfo(cfg) { return action('song_info', {config: cfg}); }
async function buildCatalog() { showCatalogStatus(await action('song_build', {config: songConfig()}), current?.song_lookup_status || {}); }
function selectCatalogFields(selected) {
  for (const [id, key] of [['song-assets', 'catalog_file'], ['song-mode', 'mode'], ['song-event', 'event']]) $(id).value = selected[key] ?? '';
  queueCatalogInfo(0);
}
bind('song-build', () => catalogAction(buildCatalog));
bind('song-apply', async () => {
  catalogActivating = true; renderCatalogState(); $('song-activation-error').hidden = true;
  try { await action('song_lookup', {config: songConfig()}); await poll(); }
  catch (e) { $('song-activation-error').textContent = e.message; $('song-activation-error').hidden = false; throw e; }
  finally { catalogActivating = false; renderCatalogState(); }
});
// Catalog status belongs to the backend; the panel only holds the current inspection.
let catalogTimer = null, catalogEpoch = 0, catalogOperationState = '';
let catalogRequestPending = false, catalogActivating = false, catalogLastOperation = {};
let catalogInfo = null, catalogLastRead = 0, catalogReading = 0, catalogCoverageKey = '';
let catalogCommandError = null;
const catalogReasons = {
  unsupported_identity: 'Song is not in the supported artwork library',
  unsupported_artwork: 'Artwork is not supported by this DDRCV version',
  ambiguous_artwork: 'Shared jacket — automatic song identification unavailable',
  duplicate_title_ids: 'Multiple catalog IDs for this title — automatic song identification unavailable',
  shared_jacket: 'Jacket shared by multiple songs or variants — automatic song identification unavailable',
  chart_outside_pool: 'Outside selected pool — check the event or use Full WORLD',
  missing_max_ex: 'Max EX missing from the catalog',
  ambiguous_chart: 'Ambiguous chart match', song_unconfirmed: 'Waiting for song confirmation'
};
function chartExplanation(chart) { return chart.max_ex != null ? 'Max EX ' + chart.max_ex : catalogReasons[chart.status] || 'Max EX unavailable'; }
function eventSlug(value) {
  try { if (value.includes('://')) return new URL(value).hash.replace(/^#game-/, ''); } catch {}
  return value;
}
function catalogKey() {
  const c = catalogConfig();
  return JSON.stringify([c.mode, c.mode === 'event' ? eventSlug(c.event) : null, c.catalog_file || null, c.assets_dir || null, c.difficulty_method]);
}
function settingsKey(c = {}) {
  return JSON.stringify([!!c.enabled, c.mode, c.mode === 'event' ? eventSlug(c.event || '') : null,
    c.catalog_file || null, c.assets_dir || null, c.style, c.difficulty_method, c.high_qos]);
}
function bundleKey(info) { return info ? [info.bundle, info.gallery, info.selection_sha256].map(v => v || '').join(':') : null; }
function catalogName(c) {
  if (c.mode === 'full') return 'Full DDR / WORLD';
  const event = eventSlug(c.event || '');
  return event === 'dia_del_ritmo_26' ? 'Dia Del Ritmo 2026 (dia_del_ritmo_26)' : event || 'Choose an event';
}
function catalogBusy() { return catalogRequestPending || ['preparing', 'checking'].includes(catalogLastOperation.phase); }
function catalogButtons() {
  const busy = catalogBusy();
  for (const id of ['song-build', 'song-load', 'song-build-default', 'song-use-loaded']) $(id).disabled = busy;
  $('song-build').disabled = busy || !!catalogInfo?.selection_mismatch;
}
async function catalogAction(task) {
  if (catalogBusy()) return;
  catalogRequestPending = true;
  catalogCommandError = null;
  catalogButtons();
  try { await task(); }
  catch (e) { catalogCommandError = {key: catalogKey(), message: e.message}; throw e; }
  finally { catalogRequestPending = false; renderCatalogState(); }
}
function catalogMode() {
  const full = $('song-mode').value === 'full';
  $('song-event').disabled = full;
  $('song-event-field').classList.toggle('inactive', full);
  $('song-event-help').textContent = full ? 'Full DDR uses WORLD charts; an event is not needed.' : 'Selected event: ' + catalogName(catalogConfig()) + '. Change this if you are running another event.';
  $('song-event-link').hidden = full;
  $('song-pool-help').hidden = full;
}
function catalogDate(value) {
  if (!value) return 'Not recorded';
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? String(value) : date.toLocaleString();
}
function showCatalogInfo(info) {
  catalogInfo = info;
  $('song-storage-path').textContent = info.catalog_file || '—';
  const link = $('song-catalog-version');
  link.textContent = info.available ? info.commit.slice(0, 12) : '—';
  link.title = info.commit || '';
  if (info.available) link.href = 'https://github.com/noahm/DDRCardDraw/commit/' + encodeURIComponent(info.commit);
  else link.removeAttribute('href');
  $('song-catalog-updated').textContent = info.available ? catalogDate(info.dataset_updated_at) : '—';
  $('song-catalog-prepared').textContent = info.available ? catalogDate(info.packed_at || info.prepared_at) : '—';
  $('song-gallery-version').textContent = info.available ? info.gallery_commit.slice(0, 12) + ' · ' + info.gallery.slice(0, 12) : '—';
  const warnings = info.coverage?.warnings || [];
  $('song-coverage').hidden = !warnings.length;
  $('song-coverage-summary').textContent = `Coverage warnings (${warnings.length}) — affected songs and charts`;
  const coverageKey = JSON.stringify(warnings);
  if (catalogCoverageKey !== coverageKey) {
    catalogCoverageKey = coverageKey;
    $('song-coverage-list').replaceChildren(...warnings.map(item => {
      const li = document.createElement('li');
      li.textContent = [item.title, item.artist, item.style, item.difficulty].filter(Boolean).join(' · ') + ': ' + (catalogReasons[item.detail] || catalogReasons[item.reason] || 'Recognition unavailable');
      return li;
    }));
  }
  $('song-mismatch').hidden = !info.selection_mismatch;
  if (info.selection_mismatch) $('song-mismatch-message').textContent = 'Loaded file: ' + catalogName(info.selection_mismatch) + '. Your selection: ' + catalogName(catalogConfig()) + '.';
  renderCatalogState();
}
function queueCatalogInfo(delay = 200, keep = false) {
  catalogMode();
  clearTimeout(catalogTimer);
  const epoch = ++catalogEpoch, key = catalogKey(), cfg = catalogConfig();
  if (!keep) { catalogInfo = null; $('song-mismatch').hidden = true; $('song-coverage').hidden = true; renderCatalogState(); }
  catalogTimer = setTimeout(async () => {
    catalogTimer = null; catalogReading++;
    try {
      const info = await requestCatalogInfo(cfg);
      if (epoch === catalogEpoch && key === catalogKey()) showCatalogInfo(info);
    } catch (e) {
      if (epoch === catalogEpoch && key === catalogKey()) showCatalogInfo({error: e.message});
    } finally { catalogReading--; catalogLastRead = Date.now(); }
  }, delay);
}
function renderCatalogState() {
  const c = catalogConfig(), env = catalogEnvironment(), runtime = env.runtime;
  const info = catalogInfo, operation = catalogLastOperation;
  const sameBundle = !!info?.available && bundleKey(runtime.catalog) === info.catalog_identity && runtime.catalog_stamp === info.catalog_stamp;
  const sameSettings = settingsKey(c) === settingsKey(env.applied);
  const loaded = sameBundle && ['ready', 'recognizing', 'confirmed'].includes(runtime.phase);
  const verified = info?.validated || (loaded && sameSettings);
  const warnings = info?.coverage?.warnings?.length || 0;
  $('song-catalog-state').textContent = !info ? 'Reading catalog information…' : info.available ?
    catalogName(info) + ' · ' + (verified ? (warnings ? 'Ready with coverage warnings' : 'Catalog validated') : 'Catalog found — checked when activated') +
    (!verified && warnings ? ' · Coverage warnings' : '') : info.error || 'Build or load a catalog to continue.';
  const relevant = !!info?.selection_key && operation.selection_key === info.selection_key;
  const busy = ['preparing', 'checking'].includes(operation.phase);
  const commandError = catalogCommandError?.key === catalogKey() ? catalogCommandError.message : '';
  $('song-operation').hidden = !(commandError || busy || (relevant && operation.error));
  $('song-operation').textContent = commandError || (busy ? (relevant ? operation.message || (operation.phase === 'preparing' ? 'Building catalog…' : 'Validating catalog…') : 'Catalog preparation is running for another selection.') :
    relevant && operation.error ? operation.error + (info?.available ? ' The previous catalog remains available.' : '') : '');
  let readiness;
  if (!c.enabled) readiness = env.applied.enabled ? 'Changes pending — apply to disable recognition.' : 'Recognition disabled — enable it above when your catalog is prepared.';
  else if (!info) readiness = 'Reading the selected catalog…';
  else if (!info.available) readiness = info.selection_mismatch ? 'Resolve the catalog selection in step 2.' : 'Prepare a catalog in step 2 before activating recognition.';
  else if (runtime.error && sameSettings) readiness = 'Recognition error: ' + runtime.error;
  else if (loaded && sameSettings) readiness = env.running ? env.activeText || (runtime.phase === 'confirmed' ? 'Recognition active — song confirmed.' : 'Recognition active — waiting for a song splash.') : env.appliedText;
  else if (env.running || (env.applied.enabled && runtime.catalog)) readiness = env.pendingText;
  else readiness = env.readyText;
  $('song-readiness').textContent = readiness;
  $('song-active-version').textContent = runtime.error ? 'Active session error: ' + runtime.error : runtime.catalog && env.applied.enabled && !['closed', 'disabled'].includes(runtime.phase) ?
    'Applied catalog: ' + catalogName(runtime.catalog) + (!sameBundle && info?.available ? ' · The selected file differs; apply to use it.' : '') + (!env.running ? ' · Camera/video is stopped.' : '') : 'Active session: recognition is not running.';
  $('song-apply').textContent = env.button;
  $('song-activation-help').textContent = env.help;
  $('song-apply').disabled = catalogActivating || env.starting || (c.enabled && (catalogBusy() || !info?.available)) || (!c.enabled && !env.applied.enabled);
  catalogButtons();
}
function showCatalogStatus(operation, runtime) {
  catalogLastOperation = operation;
  renderCatalogState();
  const state = JSON.stringify(operation);
  if (state !== catalogOperationState) {
    catalogOperationState = state;
    if (!['preparing', 'checking'].includes(operation.phase)) queueCatalogInfo(0, true);
  } else if ($('tab-song').getAttribute('aria-selected') === 'true' && Date.now() - catalogLastRead > 3000 && !catalogTimer && !catalogReading) queueCatalogInfo(0, true);
}
for (const id of ['song-mode', 'song-event', 'song-assets', 'song-difficulty']) $(id).addEventListener('input', () => queueCatalogInfo());
for (const id of ['song-enabled', 'song-style', 'song-qos']) $(id).addEventListener('change', renderCatalogState);

const tabs = [...document.querySelectorAll('[role="tab"]')];
function selectTab(tab) {
  for (const item of tabs) {
    const selected = item === tab;
    item.setAttribute('aria-selected', String(selected));
    item.tabIndex = selected ? 0 : -1;
    $(item.getAttribute('aria-controls')).hidden = !selected;
  }
  if (tab.id === 'tab-song' && initialized) queueCatalogInfo(0);
}
for (const tab of tabs) {
  tab.addEventListener('click', () => selectTab(tab));
  tab.addEventListener('keydown', event => {
    let index = tabs.indexOf(tab);
    if (event.key === 'ArrowRight') index = (index + 1) % tabs.length;
    else if (event.key === 'ArrowLeft') index = (index + tabs.length - 1) % tabs.length;
    else if (event.key === 'Home') index = 0;
    else if (event.key === 'End') index = tabs.length - 1;
    else return;
    event.preventDefault();
    selectTab(tabs[index]); tabs[index].focus();
  });
}

bind('song-load', () => catalogAction(async () => {
  const data = await post('/api/browse', {catalog: true});
  if (!data.path) return;
  const epoch = ++catalogEpoch;
  const selected = await action('song_file_config', {config: songConfig(), path: data.path});
  if (epoch !== catalogEpoch) return;
  selectCatalogFields(selected);
  showCatalogStatus(await action('song_check', {config: selected}), current?.song_lookup_status || {});
}));
bind('song-build-default', () => catalogAction(async () => {
  selectCatalogFields({...songConfig(), catalog_file: null}); await buildCatalog();
}));
bind('song-use-loaded', () => catalogAction(async () => {
  const epoch = ++catalogEpoch;
  const selected = await action('song_file_config', {config: songConfig(), path: catalogInfo?.catalog_file || $('song-assets').value});
  if (epoch !== catalogEpoch) return;
  selectCatalogFields(selected);
  showCatalogStatus(await action('song_check', {config: selected}), current?.song_lookup_status || {});
}));
