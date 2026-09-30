'use strict';
const $ = id => document.getElementById(id);
let token = '',
  config = {},
  loaded = false,
  nativeVisible = true,
  status = {},
  polling = false,
  pollTimer = null,
  saveTimer = null,
  saveChain = Promise.resolve(),
  advancedDirty = false,
  sceneDirty = false,
  previewUrl = null,
  switchingSource = false,
  sourceRevision = null;
let historyVersion = '', historyBusy = false, historyEpoch = 0, historyUrls = [];
let configRevision = 0;
let bridgeReady = false, initializing = false, initTimer = null, sessionRefresh = null, pollFailures = 0;

class DeskConnectionError extends Error {
  constructor(message, connectionMessage = message) {
    super(message);
    this.connectionMessage = connectionMessage;
  }
}

async function refreshSession() {
  if (!sessionRefresh) {
    sessionRefresh = Promise.resolve().then(() => window.pywebview.api.session()).then(session => {
      if (!session?.token) throw Error('Missing session');
      token = session.token;
    }).catch(() => {
      throw new DeskConnectionError('Desktop session unavailable. Close and reopen this panel.');
    }).finally(() => { sessionRefresh = null; });
  }
  await sessionRefresh;
}

function secretVisibility(button, visible) {
  $(button.dataset.reveal).type = visible ? 'text' : 'password';
  button.setAttribute('aria-pressed', String(visible));
  const label = `${visible ? 'Hide' : 'Show'} ${button.dataset.label}`;
  button.setAttribute('aria-label', label);
  button.title = label;
}

function clearHistory() {
  historyEpoch++;
  historyVersion = '';
  historyUrls.forEach(url => URL.revokeObjectURL(url));
  historyUrls = [];
  $('results-list').replaceChildren();
}
function historyVisible() {
  return nativeVisible && $('results-history').open && !$('panel-results').hidden;
}
async function historyImage(eventId, candidate, parent, epoch) {
  const response = await deskRequest(`results/${encodeURIComponent(eventId)}/${encodeURIComponent(candidate)}`);
  if (!response.ok) throw Error('Saved screenshot could not be loaded');
  const blob = await response.blob();
  if (epoch !== historyEpoch || !historyVisible()) return;
  const url = URL.createObjectURL(blob);
  historyUrls.push(url);
  const image = document.createElement('img');
  image.src = url;
  image.alt = candidate === 'screenshot' ? 'Saved results screenshot' : 'Alternative results screenshot';
  parent.append(image);
}
async function refreshHistory() {
  if (!historyVisible() || historyBusy) return;
  historyBusy = true;
  try {
    const data = await api('results');
    if (!historyVisible()) return;
    const records = [...data.records].reverse();
    const allowed = data.delivery_available && data.discord && data.webhook_configured;
    const version = JSON.stringify([allowed, records.map(r => [r.event_id, r.revision, r.players, r.delivery,
      r.name_update, r.alternatives, r.export_error])]);
    $('history-status').textContent = !data.delivery_available ? 'Start capture with results enabled to send or retry.' :
      !allowed ? 'Enable Discord publishing to send or retry saved results.' :
      `${records.length} recent or unresolved result(s)`;
    if (version === historyVersion) return;
    clearHistory();
    historyVersion = version;
    const epoch = historyEpoch;
    for (const r of records) {
      const card = document.createElement('article'); card.className = 'result-card';
      const heading = document.createElement('p');
      heading.textContent = `${new Date(r.created_at * 1000).toLocaleString()} · ${r.score_mode.toUpperCase()} · ` +
        (r.screenshots_only ? 'Screenshots only' : r.players.map((p, i) => p.present ? `${p.name || 'P'+(i+1)}: ${p.score ?? 'unconfirmed'}` : `P${i+1}: absent`).join(' / '));
      const detail = document.createElement('p'); detail.className = 'quiet';
      const update = r.name_update || {};
      detail.textContent = `Delivery: ${title(r.delivery.state)}${r.delivery.error ? ' · '+r.delivery.error : ''}` +
        (update.state && update.state !== 'idle' ? ` · Name update: ${title(update.state)}${update.error ? ' · '+update.error : ''}` : '') +
        (r.players.some(p => p.present && !p.name) && r.parse_names !== false ? ' · Names incomplete' : '') +
        (!r.screenshots_only && !r.screenshot_confirmed ? ' · Scores/screenshot unconfirmed' : '') +
        (r.export_error ? ' · Screenshot export warning: '+r.export_error : '');
      card.append(heading, detail);
      const picture = document.createElement('div'); card.append(picture);
      historyImage(r.event_id, 'screenshot', picture, epoch).catch(e => { if (epoch === historyEpoch) detail.textContent += ' · '+e.message; });
      const buttons = document.createElement('div'); buttons.className = 'toolbar wrap';
      function command(label, action) {
        const button = document.createElement('button'); button.textContent = label; button.disabled = !allowed;
        button.onclick = async () => {
          if (action === 'republish' && !confirm('Create another Discord post for this result?')) return;
          button.disabled = true;
          try {
            await api('action', 'POST', {action:'results_command', command:action, event_id:r.event_id, confirmed:action === 'republish'});
            historyVersion = ''; await refreshHistory();
          } catch (e) { error(e.message); button.disabled = !allowed; }
        };
        buttons.append(button);
      }
      if (r.delivery.state === 'saved') command('Send saved result', 'retry');
      if (r.delivery.state === 'failed') command('Retry delivery', 'retry');
      if (update.state === 'failed' && r.delivery.state === 'sent') command('Retry name update', 'retry_names');
      if (r.delivery.message_url) {
        const link = document.createElement('a'); link.textContent = 'Open Discord message';
        link.href = r.delivery.message_url; link.target = '_blank'; link.rel = 'noopener'; buttons.append(link);
      }
      card.append(buttons);
      if (r.delivery.state === 'sent' || (r.alternatives || []).length) {
        const more = document.createElement('details'), summary = document.createElement('summary');
        summary.textContent = 'More recovery options'; more.append(summary);
        if (r.delivery.state === 'sent') {
          const group = document.createElement('div'); group.className = 'toolbar';
          const before = buttons.childNodes.length; command('Republish', 'republish');
          group.append(buttons.childNodes[before]); more.append(group);
        }
        let loaded = false;
        more.ontoggle = () => {
          if (!more.open || loaded || !historyVisible()) return;
          loaded = true;
          for (const alternative of r.alternatives || [])
            historyImage(r.event_id, alternative.id, more, epoch).catch(e => error(e.message));
        };
        card.append(more);
      }
      $('results-list').append(card);
    }
  } finally { historyBusy = false; }
}

function error(message) {
  $('error').textContent = message || '';
  $('error').hidden = !message;
}
async function deskRequest(path, method = 'GET', body) {
  if (!token || (!loaded && !(path === 'config' && method === 'GET'))) {
    throw new DeskConnectionError('Desktop panel is still connecting. Try again shortly.');
  }
  const send = async () => {
    try {
      return await fetch('/api/' + path, {
        method,
        headers: {'X-Desk-Token': token, 'Content-Type': 'application/json'},
        body: body === undefined ? undefined : JSON.stringify(body)
      });
    } catch {
      // A write may already have reached the backend. Never replay it on network failure.
      throw new DeskConnectionError(method === 'GET' ?
        'Cannot reach the desktop backend. Try again once connected.' :
        'Connection interrupted. The action may have completed; check its status before trying again.',
        'Reconnecting to desktop backend…');
    }
  };
  const sentToken = token;
  let response = await send();
  if (response.status === 403 && (await response.clone().json()).error === 'Invalid desk session') {
    if (token === sentToken) await refreshSession();
    // Authentication rejected the request before any action; retry only with a refreshed token.
    if (token !== sentToken) response = await send();
    if (response.status === 403) {
      throw new DeskConnectionError('Desktop session expired. Close and reopen this panel.');
    }
  }
  return response;
}
async function api(path, method = 'GET', body) {
  const r = await deskRequest(path, method, body);
  if (!r.ok) {
    let d;
    try {
      d = await r.json();
    } catch {
      d = {
        error: r.statusText
      };
    }
    throw Error(d.error);
  }
  return r.status === 204 ? null : r.json();
}

function get(path) {
  return path.split('.').reduce((v, k) => v?.[k], config);
}

function set(path, value) {
  let keys = path.split('.'),
    obj = config;
  for (const k of keys.slice(0, -1)) {
    obj[k] ??= {};
    obj = obj[k];
  }
  obj[keys.at(-1)] = value;
}

function kind() {
  return Object.keys(config.ingest || {})[0] || 'simple';
}

function source() {
  return config.ingest[kind()];
}

function renderConfig(data) {
  configRevision++;
  document.querySelectorAll('[data-reveal]').forEach(button => secretVisibility(button, false));
  config = data.draft;
  loaded = true;
  advancedDirty = false;
  sceneDirty = false;
  $('profile').textContent = data.last_path || 'Unsaved configuration';
  for (const el of document.querySelectorAll('[data-path]')) {
    const value = get(el.dataset.path);
    if (el.type === 'checkbox') el.checked = !!value;
    else el.value = value ?? '';
  }
  $('source-kind').value = kind();
  $('camera-index').value = source()?.uri ?? 0;
  $('rtsp-url').value = source()?.rtsp_url ?? '';
  $('media-path').value = source()?.path ?? '';
  $('resize').checked = !!source()?.resize_to_720p;
  const limit = get('score_filter.max_per_frame');
  $('score-mode').value = limit === null ? 'money' : limit === 12 ? 'ex' : 'custom';
  $('scene-map').value = JSON.stringify(config.obs?.scene_map ?? data.default_scene_map ?? null, null, 2);
  updateAdvanced();
  sourceFields();
  queueCatalogInfo(0);
}

function sourceFields() {
  for (const el of document.querySelectorAll('.source-simple')) el.hidden = kind() !== 'simple';
  for (const el of document.querySelectorAll('.source-rtsp')) el.hidden = kind() !== 'rtsp';
  for (const el of document.querySelectorAll('.source-file')) el.hidden = !['video', 'image'].includes(kind());
  sourceStatus();
}

function sourceStatus() {
  const activeKind = Object.keys(status.source || {})[0];
  const active = status.source?.[activeKind];
  const switching = switchingSource || status.source_switching;
  $('switch-source').disabled = switching || status.phase !== 'Running' || !['simple', 'rtsp'].includes(kind());
  $('switch-source').textContent = switching ? 'Checking new camera…' : 'Switch camera';
  $('active-source').textContent = activeKind === 'simple' ? `Active camera: ${active.uri}` : activeKind === 'rtsp' ? 'Active source: RTSP' : activeKind ? `Active source: ${title(activeKind)}` : 'Capture stopped';
  $('source-feedback').textContent = status.source_error || (switching ? 'Current source continues until the new camera is ready.' : '');
  $('source-feedback').className = status.source_error ? 'quiet failed' : 'quiet';
}

// Tabs only change visibility; one shared draft and one status poller survive navigation.
const tabs = [...document.querySelectorAll('[role="tab"]')];
function selectTab(tab) {
  for (const item of tabs) {
    const selected = item === tab;
    item.setAttribute('aria-selected', String(selected));
    item.tabIndex = selected ? 0 : -1;
    $(item.getAttribute('aria-controls')).hidden = !selected;
  }
  if (tab.id === 'tab-song' && loaded) queueCatalogInfo(0);
  if (!historyVisible()) clearHistory();
  else refreshHistory().catch(e => error(e.message));
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
    selectTab(tabs[index]);
    tabs[index].focus();
  });
}

function displayConfig(value, key = '') {
  if (/(password|webhook|secret|token)/i.test(key) || (key === 'rtsp_url' && typeof value === 'string' && value.includes('@'))) {
    return value ? '[unchanged secret]' : value;
  }
  if (Array.isArray(value)) return value.map(item => displayConfig(item));
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, displayConfig(v, k)]));
  return value;
}

function updateAdvanced() {
  if (!advancedDirty) $('config-json').value = JSON.stringify(displayConfig(config), null, 2);
}

function collectJSON() {
  if (advancedDirty) {
    config = JSON.parse($('config-json').value);
    advancedDirty = false;
  }
  if (sceneDirty) {
    config.obs.scene_map = JSON.parse($('scene-map').value);
    sceneDirty = false;
  }
}

function scheduleSave() {
  if (!loaded) return;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => flush().catch(e => error(e.message)), 200);
  updateAdvanced();
  $('pending').textContent = 'Draft changes';
}
async function flush() {
  clearTimeout(saveTimer);
  collectJSON();
  updateAdvanced();
  const value = JSON.parse(JSON.stringify(config));
  if (value.song_lookup?.catalog_file === '') value.song_lookup.catalog_file = null;
  if (value.song_lookup?.assets_dir === '') value.song_lookup.assets_dir = null;
  const request = saveChain.catch(() => {}).then(() => api('config', 'PUT', value));
  saveChain = request;
  const saved = await request;
  if (JSON.stringify(config) === JSON.stringify(value)) {
    config = saved.draft;
    updateAdvanced();
  }
}
async function act(action) {
  await flush();
  if (action === 'apply' && ['Running', 'Starting'].includes(status.phase) && !confirm('Apply configuration and restart capture? Current score tracking will reset.')) return;
  await api('action', 'POST', {
    action
  });
  await loadConfig();
  await pollOnce();
}
async function loadConfig() {
  renderConfig(await api('config'));
}

function title(value) {
  return String(value ?? 'unknown').replaceAll('_', ' ').replace(/\b\w/g, x => x.toUpperCase());
}

function age(value) {
  return value == null ? 'No accepted read' : value < 1 ? 'Read just now' : `${value.toFixed(1)} s since accepted read`;
}
async function pollOnce() {
  status = await api('status');
  $('connection').textContent = 'Connected locally';
  $('phase').textContent = status.phase;
  $('phase').className = 'badge ' + (status.phase === 'Running' ? 'running' : status.error ? 'error' : '');
  $('mode').textContent = status.score_mode;
  $('state').textContent = title(status.published.state);
  $('raw-state').textContent = 'Raw: ' + title(status.raw_state);
  for (let i = 0; i < 2; i++) {
    const value = status.published.score?.[`p${i+1}_score`];
    $(`p${i+1}-presence`).textContent = status.published.players[i] ? 'Yes' : 'No';
    $(`p${i+1}`).textContent = !status.published.players[i] || value == null || value < 0 ? '—' : value.toLocaleString();
    $(`p${i+1}-age`).textContent = age(status.score_age[i]);
    $(`p${i+1}-name`).textContent = status.published.player_names?.[`p${i+1}`] ?? '—';
  }
  const song = status.published.song;
  $('song-title').textContent = song ? song.title + (song.artist ? ' · ' + song.artist : '') : 'Song: —';
  $('song-charts').textContent = ['p1', 'p2'].map(p => {
    const chart = song?.charts?.[p];
    return p.toUpperCase() + ': ' + (chart ? title(chart.difficulty) + ' · ' + chartExplanation(chart) : '—');
  }).join(' · ');
  showCatalogStatus(status.catalog_preparation || {}, status.song_lookup_status || {});
  const names = status.player_name_status || {};
  const namePhases = {disabled: 'Disabled', initializing: 'Loading OCR model', ready: names.busy ? 'Reading names' : 'Ready', failed: 'OCR failed', closed: 'Stopped'};
  $('name-status').textContent = 'Name recognition: ' + (namePhases[names.phase] || 'Stopped') + (names.error ? ' · ' + names.error : '');
  $('name-status').className = names.error ? 'failed' : 'quiet';
  $('capture').textContent = status.frame_age == null ? 'Waiting for capture' : `${status.capture_stale?'Stale capture':'Capture healthy'} · ${status.frame_age.toFixed(1)} s old`;
  $('capture').className = status.capture_stale ? 'stale' : '';
  $('publisher').textContent = status.publisher.running ? `Publishing · ${status.publisher.clients} client(s)` : 'Publisher stopped';
  let capacity;
  const timingActive = status.phase === 'Running' && status.frame_age != null && status.frame_age <= 1;
  if (!timingActive) {
    capacity = status.phase === 'Running' ? (status.frame_age == null ? 'waiting for frames' : 'no recent frames') :
      status.phase === 'Ended' ? 'playback ended' : status.phase === 'Starting' ? 'starting capture' : 'capture stopped';
  } else if (Number.isFinite(status.processing_fps) && status.processing_fps > 0) {
    capacity = `${status.processing_fps.toFixed(1)} fps (${status.processing_avg_ms.toFixed(1)} ms/frame)`;
  } else if (!('processing_fps' in status) && Number.isFinite(status.processing_ms) && status.processing_ms > 0) {
    // A reopened panel can connect to a backend started before this UI update.
    // Its timing is the latest frame, so do not label it as the new rolling average.
    capacity = `${(1000 / status.processing_ms).toFixed(1)} fps (${status.processing_ms.toFixed(1)} ms, last frame)`;
  } else {
    capacity = 'waiting for timing sample';
  }
  const sourceRate = status.source_fps == null ? '' : ` · File: ${status.source_fps.toFixed(1)} fps`;
  $('throughput').textContent = `Processing capacity: ${capacity} · Throughput: ${(timingActive ? status.fps : 0).toFixed(1)} fps${sourceRate} · ${status.sequence} frames`;
  $('pending').textContent = status.pending ? 'Draft changes · not applied' : 'Configuration applied';
  $('apply').textContent = ['Running', 'Starting'].includes(status.phase) ? 'Apply and Restart' : 'Apply configuration';
  $('start').disabled = ['Running', 'Starting'].includes(status.phase);
  $('stop').disabled = !['Running', 'Starting'].includes(status.phase);
  $('apply').disabled = switchingSource || !!status.source_switching;
  sourceStatus();
  if (sourceRevision !== null && status.source_revision !== sourceRevision) closeSnapshot();
  sourceRevision = status.source_revision;
  $('obs-status').textContent = status.obs.connected ? (status.obs.automation ? 'Automating' : 'Connected · manual') : 'Disconnected';
  $('automation').textContent = status.obs.automation ? 'Pause automation' : 'Enable automation';
  $('obs-detail').textContent = status.obs.error || (status.obs.actual_scene ? `Current scene: ${status.obs.actual_scene}` : 'OBS itself is never closed by this app.');
  const scenes = status.obs.scenes || [];
  if (JSON.stringify(scenes) !== $('scene').dataset.scenes) {
    $('scene').replaceChildren(...scenes.map(name => new Option(name, name)));
    $('scene').dataset.scenes = JSON.stringify(scenes);
  }
  $('renderer-status').textContent = status.renderer.running ? 'Running' : 'Stopped';
  $('renderer-detail').textContent = status.renderer.error || 'Capture its window in OBS after checking the output.';
  const results = status.results;
  const replaySaved = results?.phase === 'already_saved';
  const replayPolicy = results?.allow_replay_duplicates ? ' · Replay repeats enabled' : '';
  const replayNotice = 'Replay already saved · no new screenshot or automatic Discord post';
  $('results-summary').textContent = results ? `Results: ${replaySaved ? replayNotice : results.last_sent_at ? 'last sent '+new Date(results.last_sent_at * 1000).toLocaleTimeString() : 'no delivery yet'} · ${results.needs_attention || 0} need attention${replayPolicy}` : 'Results: not started';
  for (const id of ['reset-p1', 'reset-p2']) $(id).disabled = status.phase !== 'Running';
  $('discord-status').textContent = results?.discord ? 'Publishing enabled' : 'Disabled';
  $('results-detail').textContent = results?.error || (replaySaved ? `${replayNotice}. Open Recent results & recovery to view the saved screenshot. For replay testing, enable Allow repeat screenshots and Discord posts from recordings and apply results settings. For one additional post, use Republish.` : results ? `Results: ${title(results.phase)}${replayPolicy}${results.screenshots_only ? ' · Screenshots only' : ''}${results.latest ? ' · Latest delivery: ' + title(results.latest.delivery?.state) : ''}` : 'Start capture with results enabled to process results.');
  $('apply-results').disabled = status.phase === 'Starting';
  $('read-details').textContent = JSON.stringify({
    raw_scores: status.raw_scores,
    decisions: status.decisions,
    player_names: status.published.player_names,
    player_name_status: status.player_name_status,
    song: status.published.song,
    song_lookup: status.song_lookup_status
  }, null, 2);
  if (status.error) error(status.error);
  await refreshHistory();
}
async function poll() {
  clearTimeout(pollTimer);
  if (!loaded || !token || polling || !nativeVisible || document.hidden) return;
  polling = true;
  try {
    await pollOnce();
    pollFailures = 0;
  } catch (e) {
    pollFailures++;
    $('connection').textContent = e instanceof DeskConnectionError ? e.connectionMessage : 'Backend unavailable';
    if (!(e instanceof DeskConnectionError)) error(e.message);
  } finally {
    polling = false;
    if (nativeVisible && !document.hidden) pollTimer = setTimeout(poll,
      pollFailures ? Math.min(5000, 500 * 2 ** Math.min(pollFailures, 4)) : 250);
  }
}
window.deskVisibility = visible => {
  nativeVisible = visible;
  clearTimeout(pollTimer);
  if (visible && !document.hidden) loaded ? poll() : initialize();
};
document.addEventListener('visibilitychange', () => {
  clearTimeout(pollTimer);
  if (!document.hidden && nativeVisible) loaded ? poll() : initialize();
});
window.deskClose = async () => {
  try {
    if (loaded) await flush();
    await window.pywebview.api.close_ready();
  } catch (e) {
    error('Draft could not be saved: ' + e.message);
    if (confirm('The latest edits could not be saved. Close this window without saving them?')) {
      await window.pywebview.api.close_ready();
    }
  }
};

function handle(id, fn) {
  $(id).addEventListener('click', async () => {
    error('');
    try {
      await fn();
    } catch (e) {
      error(e.message);
    }
  });
}
for (const button of document.querySelectorAll('[data-reveal]')) handle(button.id, async () => {
  const input = $(button.dataset.reveal);
  if (input.type === 'text') {
    secretVisibility(button, false);
    return;
  }
  if (input.value === '[unchanged secret]') {
    const revision = configRevision;
    const previous = input.value;
    button.disabled = true;
    try {
      await flush();
      const result = await api('config/secret', 'POST', {path: input.dataset.path});
      // A profile load or edit while the request runs takes precedence.
      if (revision !== configRevision || input.value !== previous) return;
      input.value = result.value;
    } finally { button.disabled = false; }
  }
  secretVisibility(button, true);
});
for (const el of document.querySelectorAll('[data-path]')) el.addEventListener('input', async () => {
  if (['player_names.enabled', 'results.parse_names', 'results.screenshots_only'].includes(el.dataset.path)) {
    const previous = get(el.dataset.path);
    const enabled = el.checked;
    el.disabled = true;
    try {
      await flush();
      await api('action', 'POST', el.dataset.path === 'results.screenshots_only' ?
        {action:'set_screenshots_only', enabled} : {action:'set_names', scope:el.dataset.path.split('.')[0], enabled});
      set(el.dataset.path, enabled); updateAdvanced(); await pollOnce();
    } catch (e) { el.checked = !!previous; error(e.message); }
    finally { el.disabled = false; }
    return;
  }
  set(el.dataset.path, el.type === 'checkbox' ? el.checked : el.type === 'number' ? Number(el.value) : el.value);
  if (el.dataset.path === 'results.discord' && el.checked) {
    set('results.enabled', true);
    document.querySelector('[data-path="results.enabled"]').checked = true;
  } else if (el.dataset.path === 'results.enabled' && !el.checked) {
    set('results.discord', false);
    document.querySelector('[data-path="results.discord"]').checked = false;
  }
  if (el.dataset.path.startsWith('results.')) $('results-feedback').textContent = 'Results changes pending';
  scheduleSave();
});
$('source-kind').addEventListener('change', () => {
  const k = $('source-kind').value;
  config.ingest = {
    [k]: k === 'simple' ? {
      uri: 0,
      width: 1280,
      height: 720,
      queue_size: 1,
      reconnect_delay: 5,
      query_delay: .01
    } : k === 'rtsp' ? {
      rtsp_url: '',
      queue_size: 1,
      reconnect_delay: 5,
      hw_accel: true
    } : {
      path: '',
      resize_to_720p: false
    }
  };
  sourceFields();
  $('camera-index').value = 0;
  $('rtsp-url').value = '';
  $('media-path').value = '';
  $('resize').checked = false;
  scheduleSave();
});
for (const [id, key, type] of [
    ['camera-index', 'uri', 'number'],
    ['rtsp-url', 'rtsp_url', 'text'],
    ['media-path', 'path', 'text'],
    ['resize', 'resize_to_720p', 'checkbox']
  ]) $(id).addEventListener('input', () => {
  source()[key] = type === 'number' ? Number($(id).value) : type === 'checkbox' ? $(id).checked : $(id).value;
  scheduleSave();
});
$('score-mode').addEventListener('change', () => {
  if ($('score-mode').value === 'custom') {
    error('Set a custom score_filter.max_per_frame in Advanced driver configuration.');
    return;
  }
  set('score_filter.max_per_frame', $('score-mode').value === 'money' ? null : 12);
  scheduleSave();
});
$('scene-map').addEventListener('input', () => {
  sceneDirty = true;
  scheduleSave();
});
$('config-json').addEventListener('input', () => {
  advancedDirty = true;
  clearTimeout(saveTimer);
});
handle('use-json', async () => {
  await flush();
  await loadConfig();
});
handle('start', () => act('start'));
for (const player of [1, 2]) handle(`reset-p${player}`, () => api('action', 'POST', {action:'reset_score', player}));
$('results-history').addEventListener('toggle', () => {
  if (historyVisible()) refreshHistory().catch(e => error(e.message));
  else clearHistory();
});
handle('stop', () => api('action', 'POST', {
  action: 'stop'
}));
handle('apply', () => act('apply'));
handle('test-discord-webhook', async () => {
  const button = $('test-discord-webhook');
  if (button.disabled) return;
  button.disabled = true;
  $('discord-test-feedback').textContent = 'Sending test message…';
  try {
    await flush();
    const result = await api('action', 'POST', {action: 'test_discord_webhook'});
    $('discord-test-feedback').textContent = result.message;
  } catch (e) {
    $('discord-test-feedback').textContent = 'Webhook test failed: ' + e.message;
  } finally {
    button.disabled = false;
  }
});
handle('apply-results', async () => {
  await flush();
  await api('action', 'POST', {action: 'apply_results'});
  await pollOnce();
  $('results-feedback').textContent = 'Results settings applied';
});
handle('switch-source', async () => {
  if (switchingSource) return;
  switchingSource = true;
  sourceStatus();
  try {
    await flush();
    await api('action', 'POST', {action: 'switch_source'});
    // Do not reload the editor: edits made while the new camera opens stay intact.
    await pollOnce();
  } finally {
    switchingSource = false;
    sourceStatus();
  }
});
handle('scan', async () => {
  const cameras = await api('cameras');
  $('cameras').replaceChildren(new Option('Select a camera', ''), ...cameras.map(c => new Option(`${c.index}: ${c.name}`, c.index)));
});
$('cameras').addEventListener('change', () => {
  if ($('cameras').value !== '') {
    $('camera-index').value = $('cameras').value;
    source().uri = Number($('cameras').value);
    scheduleSave();
  }
});
handle('browse-media', async () => {
  const p = await window.pywebview.api.pick('media');
  if (p) {
    source().path = p;
    $('media-path').value = p;
    scheduleSave();
  }
});
handle('browse-renderer', async () => {
  const p = await window.pywebview.api.pick('directory');
  if (p) {
    set('renderer.path', p);
    document.querySelector('[data-path="renderer.path"]').value = p;
    scheduleSave();
  }
});
handle('browse-results', async () => {
  const p = await window.pywebview.api.pick('directory');
  if (p) {
    set('results.output_directory', p);
    document.querySelector('[data-path="results.output_directory"]').value = p;
    $('results-feedback').textContent = 'Results changes pending';
    scheduleSave();
  }
});
handle('open-config', async () => {
  await flush();
  const p = await window.pywebview.api.pick('config');
  if (p) renderConfig(await api('config/file', 'POST', {
    action: 'load',
    path: p
  }));
});
async function save(as) {
  await flush();
  let path = null;
  if (as || $('profile').textContent === 'Unsaved configuration') path = await window.pywebview.api.pick('save', 'tournament.json');
  if ((as || $('profile').textContent === 'Unsaved configuration') && !path) return;
  renderConfig(await api('config/file', 'POST', {
    action: 'save',
    path
  }));
}
handle('save-config', () => save(false));
handle('save-as', () => save(true));
handle('snapshot', async () => {
  const r = await deskRequest('frame');
  if (r.status === 204) throw Error('No captured frame is available yet. Start capture first.');
  if (!r.ok) throw Error('Snapshot request failed');
  const meta = JSON.parse(r.headers.get('X-Frame-Metadata'));
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = URL.createObjectURL(await r.blob());
  $('frame').src = previewUrl;
  $('preview').hidden = false;
  $('snapshot').textContent = 'Refresh frame';
  $('frame-caption').textContent = `Frame ${meta.sequence} · captured ${new Date(meta.captured_at*1000).toLocaleTimeString()} · ${meta.age_seconds.toFixed(2)} s old when requested`;
});
function closeSnapshot() {
  $('preview').hidden = true;
  $('frame').removeAttribute('src');
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = null;
  $('snapshot').textContent = 'View stream';
}
handle('hide-preview', closeSnapshot);
for (const el of document.querySelectorAll('[data-action]')) el.addEventListener('click', async () => {
  error('');
  try {
    await api('integration', 'POST', {
      action: el.dataset.action
    });
  } catch (e) {
    error(e.message);
  }
});
handle('automation', () => api('integration', 'POST', {
  action: 'obs_automation',
  enabled: !status.obs.automation
}));
handle('manual-scene', () => api('integration', 'POST', {
  action: 'obs_scene',
  name: $('scene').value
}));
$('about-open').addEventListener('click', () => $('about-dialog').showModal());

handle('exit', async () => {
  if (confirm('Exit application and stop capture, publishing, and owned integrations?')) {
    await flush();
    await api('action', 'POST', {
      action: 'exit',
      confirmed: true
    });
  }
});
document.querySelector('details').addEventListener('toggle', async e => {
  if (e.target.open) {
    try {
      $('logs').textContent = (await api('logs')).join('\n');
    } catch (err) {
      error(err.message);
    }
  }
});
async function initialize() {
  clearTimeout(initTimer);
  if (!bridgeReady || loaded || initializing || !nativeVisible || document.hidden) return;
  initializing = true;
  let retry = false;
  try {
    await refreshSession();
    await loadConfig();
    poll();
  } catch (e) {
    retry = e instanceof DeskConnectionError;
    $('connection').textContent = retry ? e.connectionMessage : 'Backend unavailable';
    if (!retry) error(e.message);
  } finally {
    initializing = false;
    if (retry) initTimer = setTimeout(initialize, 1000);
  }
}
window.addEventListener('pywebviewready', () => {
  bridgeReady = true;
  initialize();
});

function catalogConfig() {
  return {...config.song_lookup, enabled: $('song-enabled').checked, mode: $('song-mode').value,
    event: $('song-event').value, catalog_file: $('song-assets').value || null,
    style: $('song-style').value, difficulty_method: $('song-difficulty').value, high_qos: $('song-qos').checked};
}
function catalogEnvironment() {
  const running = ['Running', 'Starting'].includes(status.phase);
  return {runtime: status.song_lookup_status || {}, applied: status.applied_song_lookup || {}, running,
    readyText: 'Ready to start — use Start in the window header.', appliedText: 'Ready to start — use Start in the window header.',
    pendingText: running ? 'Changes pending — use Apply and Restart in the window header.' : 'Changes pending — use Apply configuration or Start in the window header.',
    help: 'Song settings apply with the controls in the window header.'};
}
function requestCatalogInfo(cfg) { return api('action', 'POST', {action: 'song_info', config: cfg}); }
async function buildCatalog() {
  const cfg = catalogConfig();
  await flush();
  showCatalogStatus(await api('action', 'POST', {action: 'song_build', config: cfg}), status.song_lookup_status || {});
}
function selectCatalogFields(selected) {
  for (const [id, key] of [['song-assets', 'catalog_file'], ['song-mode', 'mode'], ['song-event', 'event']]) {
    $(id).value = selected[key] ?? '';
    set('song_lookup.' + key, selected[key]);
  }
  scheduleSave(); queueCatalogInfo(0);
}
handle('song-build', () => catalogAction(buildCatalog));
// Catalog status belongs to the backend; the panel only holds the current inspection.
let catalogTimer = null, catalogEpoch = 0, catalogOperationState = '';
let catalogRequestPending = false, catalogLastOperation = {};
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
  $('song-activation-help').textContent = env.help;
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

handle('song-load', () => catalogAction(async () => {
  const path = await window.pywebview.api.pick('catalog');
  if (!path) return;
  const epoch = ++catalogEpoch;
  const selected = await api('action', 'POST', {action: 'song_file_config', config: catalogConfig(), path});
  if (epoch !== catalogEpoch) return;
  selectCatalogFields(selected);
  await flush();
  showCatalogStatus(await api('action', 'POST', {action: 'song_check', config: selected}), status.song_lookup_status || {});
}));
handle('song-build-default', () => catalogAction(async () => {
  selectCatalogFields({...catalogConfig(), catalog_file: null});
  await buildCatalog();
}));
handle('song-use-loaded', () => catalogAction(async () => {
  const epoch = ++catalogEpoch;
  const selected = await api('action', 'POST', {action: 'song_file_config', config: catalogConfig(), path: catalogInfo?.catalog_file || $('song-assets').value});
  if (epoch !== catalogEpoch) return;
  selectCatalogFields(selected); await flush();
  showCatalogStatus(await api('action', 'POST', {action: 'song_check', config: selected}), status.song_lookup_status || {});
}));
