"""Shared tournament JSON defaults and validation. No desktop dependencies."""
from copy import deepcopy
import json
import math
from pathlib import Path


def default_config():
    return {
        "ingest": {
            "simple": {
                "uri": 0,
                "queue_size": 1,
                "reconnect_delay": 5,
                "width": 1280,
                "height": 720,
                "query_delay": 0.01
            }
        },
        "publish": {
            "websocket": {
                "host": 'localhost',
                "port": 9000,
                "delay": 0.1,
                "only_send_new": True
            }
        },
        "debounce": {"confirm_seconds": 0.2, "min_frames": 3, "unknown_seconds": 1.0, "max_frame_gap": 0.5, "min_fraction": 0.75},
        "score_filter": {"game_fps": 60, "max_per_frame": 12},
        "score_extractor": {
            "glyph_dir": None
        },
        "state": {
            "pkl_dir": None,
            "states": [
                'song_result',
                'song_playing',
                'song_select',
                'song_splash',
                'total_result',
                'login'
            ]
        },
        "jacket_database": {
            "prebuilt_database": r'/home/tim/persistent/database/db_effnetb0-20241126.pkl',
            "cache_dir": r'/home/tim/persistent/database/cache'
        },
        "results": {
            "enabled": True,
            "parse_names": True,
            "output_directory": "screenshots",
            "include_player_names": True,
            "outbox_directory": ".workbench/results",
            "settling_seconds": 2,
            "only_duo": False,
            "discord": False,
            'webhook': None
        },
        "player_names": {"enabled": False},
        "driver_debug": {
            "render_frame": False
        }
    }



def merge_config(defaults, overrides):
    """Retain legacy partial overrides; selecting ingest replaces its entire union."""
    for key, value in overrides.items():
        if key != 'ingest' and isinstance(value, dict) and isinstance(defaults.get(key), dict):
            merge_config(defaults[key], value)
        else:
            defaults[key] = deepcopy(value)
    return defaults


def normalize_score_mode(overrides):
    """Explicit filter settings win; a mode-only profile selects its preset."""
    result = deepcopy(overrides)
    mode = result.get('score_mode', 'ex')
    if mode not in ('ex', 'money'):
        raise ValueError('score_mode must be ex or money')
    filt = result.setdefault('score_filter', {})
    if not isinstance(filt, dict):
        raise ValueError('score_filter must be an object')
    if 'max_per_frame' not in filt:
        filt['max_per_frame'] = None if mode == 'money' else 12
    # Custom positive limits remain custom; they use the EX results crop.
    result['score_mode'] = 'money' if filt['max_per_frame'] is None else 'ex'
    return result


def normalize_config(overrides):
    if not isinstance(overrides, dict):
        raise ValueError('Configuration must be a JSON object')
    overrides = normalize_score_mode(overrides)
    legacy = overrides.get('results', {})
    if isinstance(legacy, dict):
        if 'outbox_directory' not in legacy and legacy.get('screenshot_directory'):
            legacy['outbox_directory'] = legacy['screenshot_directory']
        if 'settling_seconds' not in legacy and 'processing_delay' in legacy:
            legacy['settling_seconds'] = legacy['processing_delay']
    result = default_config()
    result['obs'] = dict(enabled=False, automation=False, host='localhost', port=4455,
                         password='', scene_map=None)
    result['renderer'] = dict(enabled=False, path=str(Path(__file__).resolve().parents[3] / 'ddr_score_render'))
    return merge_config(result, overrides)


def read_config(path):
    with Path(path).open(encoding='utf-8-sig') as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError('Configuration must be a JSON object')
    return value


def load_config(path):
    return validate_config(read_config(path))


def validate_config(overrides):
    """Validate without opening capture or connecting integrations."""
    config = normalize_config(overrides)
    for section in ('ingest', 'publish', 'debounce', 'score_filter', 'score_extractor',
                    'state', 'results', 'player_names', 'driver_debug', 'obs', 'renderer'):
        if not isinstance(config[section], dict):
            raise ValueError(f'{section} must be an object')
    ingest = config['ingest']
    if len(ingest) != 1 or next(iter(ingest)) not in ('simple', 'rtsp', 'video', 'image'):
        raise ValueError('Select exactly one ingest source: simple, rtsp, video, or image')
    kind, source = next(iter(ingest.items()))
    if not isinstance(source, dict):
        raise ValueError('Ingest source settings must be an object')
    if kind in ('video', 'image'):
        if not isinstance(source.get('path'), str) or not Path(source['path']).expanduser().is_file():
            raise ValueError('Select an existing local video or image file')
        boolean(source, 'resize_to_720p', False)
    if kind == 'rtsp' and (not isinstance(source.get('rtsp_url'), str) or not source['rtsp_url'].startswith(('rtsp://', 'rtsps://'))):
        raise ValueError('RTSP source requires an rtsp:// or rtsps:// URL')
    if kind == 'simple':
        if type(source.get('uri')) is not int or source['uri'] < 0:
            raise ValueError('Camera index must be a nonnegative integer')
        if source.get('width', 1280) != 1280 or source.get('height', 720) != 720:
            raise ValueError('Live capture must be 1280x720')
    for key, minimum in (('queue_size', 1), ('reconnect_delay', 0), ('query_delay', 0)):
        if key in source:
            number(source[key], f'ingest.{key}', minimum)
    if 'queue_size' in source and type(source['queue_size']) is not int:
        raise ValueError('queue_size must be an integer')
    if set(config['publish']) != {'websocket'} or not isinstance(config['publish']['websocket'], dict):
        raise ValueError('publish must contain websocket settings')
    pub = config['publish']['websocket']
    port(pub.get('port'), 'publish.websocket.port')
    if not isinstance(pub.get('host'), str) or not pub['host'].strip():
        raise ValueError('Publisher host must not be empty')
    number(pub.get('delay'), 'publish.websocket.delay', 0, strict=True)
    boolean(pub, 'only_send_new', True)
    filt = config['score_filter']
    number(filt['game_fps'], 'score_filter.game_fps', 0, strict=True)
    if filt['max_per_frame'] is not None:
        number(filt['max_per_frame'], 'score_filter.max_per_frame', 0, strict=True)
    from ddrcv.state.temporal import StateDebouncer
    if type(config['debounce'].get('min_frames')) is not int:
        raise ValueError('debounce.min_frames must be an integer')
    StateDebouncer(**config['debounce'])
    for key in ('confirm_seconds', 'unknown_seconds', 'max_frame_gap', 'min_fraction'):
        number(config['debounce'][key], 'debounce.' + key, 0)
    result = config['results']
    from ddrcv.state.player_names import validate_config as validate_names
    config['player_names'] = validate_names(config['player_names'])
    for key in ('enabled', 'discord', 'only_duo', 'parse_names', 'include_player_names'):
        boolean(result, key, False)
    if not isinstance(result.get('outbox_directory'), str) or not result['outbox_directory']:
        raise ValueError('Results require an outbox directory')
    if not isinstance(result.get('output_directory'), str) or not result['output_directory'].strip():
        raise ValueError('Results require a screenshot output directory')
    from ddrcv.results.service import ResultsService, DEFAULTS as RESULTS_DEFAULTS
    ResultsService._validate({**RESULTS_DEFAULTS, **result})
    boolean(config['driver_debug'], 'render_frame', False)
    obs = config['obs']
    boolean(obs, 'enabled', False)
    boolean(obs, 'automation', False)
    port(obs.get('port'), 'obs.port')
    if not isinstance(obs.get('host'), str) or not obs['host'].strip():
        raise ValueError('OBS host must not be empty')
    if not isinstance(obs.get('password'), str):
        raise ValueError('OBS password must be a string')
    scene_map = obs.get('scene_map')
    if scene_map is not None and (not isinstance(scene_map, dict) or any(v is not None and not isinstance(v, str) for v in scene_map.values())):
        raise ValueError('OBS scene_map must map states to scene names or null')
    boolean(config['renderer'], 'enabled', False)
    if not isinstance(config['renderer'].get('path'), str):
        raise ValueError('Renderer path must be a string')
    return config


def number(value, name, minimum, strict=False):
    if type(value) not in (int, float) or not math.isfinite(value) or value < minimum or (strict and value == minimum):
        raise ValueError(f'{name} must be a finite number {">" if strict else ">="} {minimum}')


def port(value, name):
    if type(value) is not int or not 1 <= value <= 65535:
        raise ValueError(f'{name} must be an integer from 1 to 65535')


def boolean(section, key, default):
    if type(section.get(key, default)) is not bool:
        raise ValueError(f'{key} must be true or false')


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    temporary.replace(path)
