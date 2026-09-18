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
  const response = await fetch(`/api/results/${encodeURIComponent(eventId)}/${encodeURIComponent(candidate)}`, {
    headers: {'X-Desk-Token': token}
  });
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
async function api(path, method = 'GET', body) {
  const r = await fetch('/api/' + path, {
    method,
    headers: {
      'X-Desk-Token': token,
      'Content-Type': 'application/json'
    },
    body: body === undefined ? undefined : JSON.stringify(body)
  });
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
  $('results-summary').textContent = results ? `Results: ${results.last_sent_at ? 'last sent '+new Date(results.last_sent_at * 1000).toLocaleTimeString() : 'no delivery yet'} · ${results.needs_attention || 0} need attention` : 'Results: not started';
  for (const id of ['reset-p1', 'reset-p2']) $(id).disabled = status.phase !== 'Running';
  $('discord-status').textContent = results?.discord ? 'Publishing enabled' : 'Disabled';
  $('results-detail').textContent = results?.error || (results ? `Results: ${title(results.phase)}${results.screenshots_only ? ' · Screenshots only' : ''}${results.latest ? ' · Latest delivery: ' + title(results.latest.delivery?.state) : ''}` : 'Start capture with results enabled to process results.');
  $('apply-results').disabled = status.phase === 'Starting';
  $('read-details').textContent = JSON.stringify({
    raw_scores: status.raw_scores,
    decisions: status.decisions,
    player_names: status.published.player_names,
    player_name_status: status.player_name_status
  }, null, 2);
  if (status.error) error(status.error);
  await refreshHistory();
}
async function poll() {
  clearTimeout(pollTimer);
  if (polling || !nativeVisible || document.hidden) return;
  polling = true;
  try {
    await pollOnce();
  } catch (e) {
    $('connection').textContent = 'Backend unavailable';
    error(e.message);
  } finally {
    polling = false;
    if (nativeVisible && !document.hidden) pollTimer = setTimeout(poll, 250);
  }
}
window.deskVisibility = visible => {
  nativeVisible = visible;
  clearTimeout(pollTimer);
  if (visible && !document.hidden) poll();
};
document.addEventListener('visibilitychange', () => {
  clearTimeout(pollTimer);
  if (!document.hidden && nativeVisible) poll();
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
  const r = await fetch('/api/frame', {
    headers: {
      'X-Desk-Token': token
    }
  });
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
window.addEventListener('pywebviewready', async () => {
  try {
    token = (await window.pywebview.api.session()).token;
    await loadConfig();
    poll();
  } catch (e) {
    error(e.message);
  }
});
