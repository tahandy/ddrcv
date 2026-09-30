"""Persistent desk state; the window is only a client."""
from collections import deque
from copy import deepcopy
import logging
from pathlib import Path
import re
import threading

from ddrcv.apps.driver_config import normalize_config, validate_config, write_json, load_config

MASK = '[unchanged secret]'


def mask_config(value, key=''):
    if any(word in key.lower() for word in ('password', 'webhook', 'secret', 'token')):
        return MASK if value else value
    if isinstance(value, dict):
        return {k: mask_config(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [mask_config(v) for v in value]
    if key == 'rtsp_url' and isinstance(value, str) and '@' in value:
        return MASK
    return value


def restore_secrets(value, previous):
    if value == MASK:
        return deepcopy(previous)
    if isinstance(value, dict):
        previous = previous if isinstance(previous, dict) else {}
        return {k: restore_secrets(v, previous.get(k)) for k, v in value.items()}
    return value


def draft_config(config):
    """Allow unfinished field values, but keep the editor's structure usable."""
    candidate = normalize_config(config)
    for key in ('publish', 'score_filter', 'obs', 'renderer', 'state', 'results', 'driver_debug', 'score_extractor', 'debounce'):
        if not isinstance(candidate.get(key), dict):
            raise ValueError(f'{key} must be an object')
    ingest = candidate.get('ingest')
    if (not isinstance(ingest, dict) or len(ingest) != 1
            or next(iter(ingest)) not in ('simple', 'rtsp', 'video', 'image')
            or not isinstance(next(iter(ingest.values())), dict)):
        raise ValueError('Draft requires exactly one source settings object')
    if not isinstance(candidate['publish'].get('websocket'), dict):
        raise ValueError('publish.websocket must be an object')
    return candidate


class DeskLogs(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.lines = deque(maxlen=200)
        self.secrets = set()
        self.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))

    def remember(self, value, key=''):
        if isinstance(value, dict):
            for k, v in value.items():
                self.remember(v, k)
        elif isinstance(value, str) and value and (any(k in key.lower() for k in ('password', 'webhook', 'secret', 'token')) or key == 'rtsp_url'):
            self.secrets.add(value)

    def scrub(self, text):
        for secret in sorted(tuple(self.secrets), key=len, reverse=True):
            text = text.replace(secret, '[redacted]')
        return re.sub(r'(rtsps?://)[^\s/@]+@', r'\1[redacted]@', text)

    def emit(self, record):
        self.lines.append(self.scrub(self.format(record)))


class Desk:
    def __init__(self, data_dir, runtime_factory=None):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.data_dir / 'desk.json'
        self.lock = threading.RLock()
        self.operations = threading.Lock()
        self.closed = False
        self.runtime = None
        from ddrcv.jacket_lookup.operations import CatalogPreparation
        self.catalog_preparation = CatalogPreparation()
        self.log = logging.getLogger('ddrcv.desktop')
        self.logs = DeskLogs()
        logging.getLogger().addHandler(self.logs)
        self.error = None
        self.last_path = ''
        self.preferences = dict(width=1120, height=800)
        self.applied = normalize_config({})
        self.draft = deepcopy(self.applied)
        self.runtime_factory = runtime_factory
        if self.state_file.exists():
            import json
            try:
                saved = json.loads(self.state_file.read_text(encoding='utf-8'))
                self.applied = normalize_config(saved.get('applied', {}))
                self.draft = draft_config(saved.get('draft', deepcopy(self.applied)))
                if not isinstance(self.draft, dict):
                    raise ValueError('Saved draft must be an object')
                self.last_path = saved.get('last_path', '')
                self.preferences.update(saved.get('preferences', {}))
            except (ValueError, OSError, TypeError) as error:
                self.error = f'Saved settings could not be restored: {error}'
        self.logs.remember(self.applied)
        self.logs.remember(self.draft)

    def _persist(self):
        write_json(self.state_file, dict(applied=self.applied, draft=self.draft,
                                        last_path=self.last_path, preferences=self.preferences))

    def config(self):
        with self.lock:
            from ddrcv.publish.obs_policy import DEFAULT_SCENE_MAP
            return dict(draft=mask_config(deepcopy(self.draft)), last_path=self.last_path,
                        default_scene_map=deepcopy(DEFAULT_SCENE_MAP),
                        pending=self.draft != self.applied, preferences=deepcopy(self.preferences))

    def reveal_secret(self, path):
        if path not in ('obs.password', 'results.webhook'):
            raise ValueError('Unknown credential field')
        section, key = path.split('.')
        with self.lock:
            return self.draft[section].get(key) or ''

    def edit(self, config):
        if not isinstance(config, dict):
            raise ValueError('Configuration must be a JSON object')
        with self.lock:
            candidate = draft_config(restore_secrets(config, self.draft))
            self.logs.remember(candidate)
            old = self.draft
            self.draft = candidate
            try:
                self._persist()
            except Exception:
                self.draft = old
                raise
        return self.config()

    def load(self, path):
        config = load_config(path)
        with self.lock:
            self.logs.remember(config)
            self.draft, self.last_path = config, str(Path(path).resolve())
            self._persist()
        return self.config()

    def save(self, path=None):
        with self.lock:
            config = validate_config(self.draft)
            target = path or self.last_path
            if not target:
                raise ValueError('Choose a file with Save As first')
            # Saved profiles work from CLI regardless of its current directory.
            for section, key in ((next(iter(config['ingest'].values())), 'path'),
                                 (config['state'], 'pkl_dir'), (config['score_extractor'], 'glyph_dir'),
                                 (config['results'], 'screenshot_directory'), (config['results'], 'outbox_directory'),
                                 (config['results'], 'output_directory'),
                                 (config['renderer'], 'path'), (config['song_lookup'], 'assets_dir'),
                                 (config['song_lookup'], 'catalog_file')):
                if section.get(key):
                    section[key] = str(Path(section[key]).expanduser().resolve())
            write_json(target, config)
            self.last_path = str(Path(target).resolve())
            self.draft = config
            self._persist()
        return self.config()

    def prepare_song_lookup(self, config=None, *, prepare=False, refresh=False):
        with self.lock:
            config = deepcopy(self.draft['song_lookup'] if config is None else config)
        return self.catalog_preparation.start(config, prepare=prepare, refresh=refresh)

    def _prepare(self, config):
        if self.runtime_factory:
            return self.runtime_factory(config)
        from ddrcv.apps.driver_ddr import create_runtime
        return create_runtime(config, self.log, data_dir=self.data_dir, desktop=True)

    def apply(self, start=False):
        with self.operations:
            if self.closed:
                raise ValueError('Application is shutting down')
            if start and self.runtime and self.runtime.thread and not self.runtime.finished.is_set():
                raise ValueError('Driver is already running; use Apply and Restart for edits')
            with self.lock:
                candidate = validate_config(deepcopy(self.draft))
            # Decode file/template validation happens before stopping the running session.
            prepared = self._prepare(candidate)
            old = self.runtime
            running = old is not None and old.thread is not None and not old.finished.is_set()
            try:
                if old:
                    old.stop()
                with self.lock:
                    self.applied = candidate
                    self.draft = deepcopy(candidate)
                    self._persist()
                self.runtime = prepared
                self.error = None
                if start or running:
                    prepared.start()
            except Exception:
                prepared.stop()
                raise
        return self.status()

    def start(self):
        if self.runtime and self.runtime.thread and not self.runtime.finished.is_set():
            raise ValueError('Driver is already running; use Apply and Restart for edits')
        return self.apply(start=True)

    def _request_stop(self):
        runtime = self.runtime
        event = getattr(runtime, 'stop_requested', None)
        if event is not None:
            event.set()  # Cancel a pending camera probe before waiting for its API operation.

    def stop(self):
        self._request_stop()
        with self.operations:
            if self.runtime:
                self.runtime.stop()
        return self.status()

    def switch_source(self):
        with self.operations:
            if self.closed:
                raise ValueError('Application is shutting down')
            runtime = self.runtime
            if runtime is None or runtime.phase != 'Running':
                raise ValueError('Start the driver before switching cameras')
            with self.lock:
                # Only ingest is applied. Unrelated (even unfinished) draft edits
                # remain pending and cannot restart integrations or the publisher.
                candidate = deepcopy(self.applied)
                candidate['ingest'] = deepcopy(self.draft['ingest'])
                ingest = validate_config(candidate)['ingest']
            runtime.switch_source(ingest)
            with self.lock:
                self.applied['ingest'] = deepcopy(ingest)
                self._persist()
        return self.status()

    def integration(self, action, **args):
        runtime = self.runtime
        if runtime is None:
            raise ValueError('Start the driver before controlling integrations')
        return runtime.integrations.command(action, **args)

    def test_discord_webhook(self):
        from ddrcv.results.delivery import redact_error, send_test_message
        with self.lock:
            if self.closed:
                raise ValueError('Application is shutting down')
            webhook = self.draft['results'].get('webhook')
        if not isinstance(webhook, str) or not webhook.strip():
            raise ValueError('Enter a Discord webhook URL first')
        # Network I/O stays on the API thread, without capture or desk locks.
        try:
            send_test_message(webhook.strip())
        except Exception as error:
            raise ValueError(redact_error(error, webhook.strip())) from None
        return dict(ok=True, message='Test message sent to Discord. Check your channel.')

    def apply_results(self):
        """Apply only the Results tab controls, preserving unrelated draft edits."""
        keys = ('enabled', 'discord', 'webhook', 'parse_names', 'screenshots_only', 'allow_replay_duplicates', 'output_directory', 'include_player_names')
        with self.operations:
            if self.closed:
                raise ValueError('Application is shutting down')
            with self.lock:
                settings = {key: deepcopy(self.draft['results'][key]) for key in keys}
                candidate = deepcopy(self.applied)
                candidate['results'].update(settings)
                validate_config(candidate)
            runtime = self.runtime
            if runtime and runtime.thread and not runtime.finished.is_set():
                runtime.configure_results(settings)
            elif runtime:
                runtime.config['results'].update(settings)
            with self.lock:
                self.applied['results'].update(settings)
                self._persist()
        return self.status()

    def set_names(self, scope, enabled):
        if scope not in ('player_names', 'results') or type(enabled) is not bool:
            raise ValueError('Select a name switch and a boolean value')
        key = 'enabled' if scope == 'player_names' else 'parse_names'
        with self.operations:
            if self.closed:
                raise ValueError('Application is shutting down')
            runtime = self.runtime
            running = runtime and runtime.thread and not runtime.finished.is_set()
            if running:
                if scope == 'results':
                    runtime.configure_results({key: enabled})
                else:
                    runtime.control('names', enabled)
            elif runtime:
                runtime.config[scope][key] = enabled
            with self.lock:
                self.applied[scope][key] = enabled
                self.draft[scope][key] = enabled
                self._persist()
        return self.status()

    def set_screenshots_only(self, enabled):
        if type(enabled) is not bool:
            raise ValueError('Screenshots only must be a boolean')
        with self.operations:
            if self.closed:
                raise ValueError('Application is shutting down')
            runtime = self.runtime
            if runtime and runtime.thread and not runtime.finished.is_set():
                runtime.configure_results({'screenshots_only': enabled})
            elif runtime:
                runtime.config['results']['screenshots_only'] = enabled
            with self.lock:
                self.applied['results']['screenshots_only'] = enabled
                self.draft['results']['screenshots_only'] = enabled
                self._persist()
        return self.status()

    def reset_score(self, player):
        if type(player) is not int or player not in (1, 2):
            raise ValueError('Select player 1 or 2')
        if not self.runtime:
            raise ValueError('Start capture before resetting a score')
        self.runtime.control('reset_score', player - 1)
        return self.status()

    def results_history(self):
        service = self.runtime.results if self.runtime else None
        if service is None:
            return dict(records=[], delivery_available=False, needs_attention=0)
        return service.status()

    def results_action(self, action, event_id, confirmed=False):
        if action not in ('retry', 'republish', 'retry_names'):
            raise ValueError('Unknown result action')
        if action == 'republish' and confirmed is not True:
            raise ValueError('Confirm creating another Discord post')
        runtime = self.runtime
        service = runtime.results if runtime else None
        if service is None or service.closed or runtime.phase != 'Running':
            raise ValueError('Start capture with results enabled before sending or retrying')
        service.outbox.command(action, event_id)
        return self.results_history()

    def results_image(self, event_id, candidate):
        service = self.runtime.results if self.runtime else None
        if service is None:
            raise ValueError('No results service')
        with service.outbox.lock:
            record = service.outbox.records.get(event_id)
            if record is None:
                raise ValueError('Unknown result event')
            allowed = {'screenshot', *(item['id'] for item in record.get('alternatives', []))}
            if candidate not in allowed or candidate not in ('screenshot', 'alternative-1', 'alternative-2'):
                raise ValueError('Unknown screenshot candidate')
            return service.outbox.directory / event_id / (candidate + '.png')

    def status(self):
        runtime = self.runtime
        status = runtime.status() if runtime else dict(phase='Stopped', published=dict(state='unknown', players=[True, True], score=None),
                    raw_state='unknown', raw_scores=None, decisions={}, frame_age=None,
                    capture_stale=True, score_age=[None, None], sequence=0, fps=0, processing_ms=0,
                    processing_fps=None, processing_avg_ms=None, source_fps=None,
                    publisher=dict(running=False, clients=0), obs=dict(connected=False, automation=False),
                    renderer=dict(running=False))
        with self.lock:
            pending = self.draft != self.applied
            limit = self.applied['score_filter']['max_per_frame']
        status.update(pending=pending, score_mode='Money' if limit is None else 'EX' if limit == 12 else 'Custom',
                      error=self.logs.scrub(str(status.get('error') or self.error or '')) or None)
        status['catalog_preparation'] = self.catalog_preparation.status()
        with self.lock:
            status['applied_song_lookup'] = deepcopy(self.applied['song_lookup'])
        status['source'] = mask_config(status.get('source', deepcopy(self.applied['ingest'])))
        status['source_error'] = self.logs.scrub(str(status.get('source_error') or '')) or None
        for integration in ('obs', 'renderer'):
            if status.get(integration, {}).get('error'):
                status[integration]['error'] = self.logs.scrub(str(status[integration]['error']))
        return status

    def snapshot(self):
        return self.runtime.snapshot() if self.runtime else (None, {})

    def close(self):
        self._request_stop()
        with self.operations:
            self.closed = True
            self.catalog_preparation.close()
            if self.runtime:
                self.runtime.stop()
            with self.lock:
                self._persist()
        logging.getLogger().removeHandler(self.logs)
