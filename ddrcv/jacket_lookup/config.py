"""Cheap configuration validation; no model, gallery, or network initialization."""
from copy import deepcopy
import os
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
