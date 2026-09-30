"""Cheap configuration validation; no model, gallery, or network initialization."""
from copy import deepcopy
import hashlib
import json
import os
import re
from pathlib import Path

from .catalog import DEFAULT_EVENT, parse_event

DEFAULTS = dict(enabled=False, mode='event', event=DEFAULT_EVENT, style='single',
                catalog_file=None, assets_dir=None, difficulty_method='template', high_qos=True)


def default_assets_dir():
    base = (Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local'))
            if os.name == 'nt' else Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')))
    return base / 'ddrcv' / 'jacket_lookup'


def validate_config(value=None):
    if value is not None and not isinstance(value, dict):
        raise ValueError('song_lookup must be an object')
    cfg = {**DEFAULTS, **deepcopy(value or {})}
    if set(cfg) - set(DEFAULTS):
        raise ValueError('Unknown song_lookup setting')
    for key in ('enabled', 'high_qos'):
        if type(cfg[key]) is not bool:
            raise ValueError(f'song_lookup.{key} must be boolean')
    for key, options in (('mode', ('event', 'full')), ('style', ('single', 'double')),
                         ('difficulty_method', ('template', 'ocr'))):
        if cfg[key] not in options:
            raise ValueError(f'Invalid song_lookup.{key}')
    if not isinstance(cfg['event'], str):
        raise ValueError('song_lookup.event must be a DDR event URL or slug')
    if cfg['mode'] == 'event':
        cfg['event'] = parse_event(cfg['event'])
    for field in ('catalog_file', 'assets_dir'):
        if cfg[field] is not None and (not isinstance(cfg[field], str) or not cfg[field].strip()):
            raise ValueError(f'song_lookup.{field} must be a path or null')
    if cfg['catalog_file'] and Path(cfg['catalog_file']).suffix.lower() != '.ddrcatalog':
        raise ValueError('Catalog file must have the .ddrcatalog extension')
    return cfg


def assets_root(config):
    return Path(config['assets_dir']).expanduser().resolve() if config['assets_dir'] else default_assets_dir()


def selection_key(config):
    return 'event-' + config['event'] if config['mode'] == 'event' else 'full-world'


def catalog_path(config):
    if config.get('catalog_file'):
        return Path(config['catalog_file']).expanduser().resolve()
    return assets_root(config) / 'catalogs' / (selection_key(config) + '.ddrcatalog')


def inspection_key(config):
    """Selection/readiness identity, independent of a disposable UI panel."""
    cfg = validate_config(config)
    fields = (str(assets_root(cfg)), str(catalog_path(cfg)), selection_key(cfg), cfg['difficulty_method'])
    return hashlib.sha256(json.dumps(fields).encode()).hexdigest()


def catalog_stamp(config):
    """Cheap file-change marker; this does not qualify or load the catalog."""
    destination = catalog_path(config)
    paths = [destination]
    if not destination.exists() and not config['catalog_file']:
        root = assets_root(config)
        pointer = root / 'active' / (selection_key(config) + '.json')
        paths = [pointer]
        try:
            data = json.loads(pointer.read_text(encoding='utf-8'))
            if isinstance(data, dict) and re.fullmatch('[0-9a-f]{32}', str(data.get('bundle', ''))):
                paths.append(root / 'bundles' / data['bundle'] / 'selection.json')
                gallery = str(data.get('gallery', ''))
                if re.fullmatch('[0-9a-f]{64}', gallery):
                    paths.extend(root / 'galleries' / gallery / name for name in ('index.json', 'vectors.npz'))
        except (OSError, ValueError):
            pass
    stamps = []
    for path in paths:
        try:
            stat = path.stat()
            stamps.append((str(path), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino))
        except OSError:
            stamps.append((str(path), None))
    return hashlib.sha256(json.dumps(stamps).encode()).hexdigest()
