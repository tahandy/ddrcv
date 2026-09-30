"""One explicit background preparation/readiness operation for an operator UI."""
from copy import deepcopy
import threading

from .config import catalog_stamp, inspection_key, validate_config


class CatalogPreparation:
    def __init__(self):
        self.lock = threading.Lock()
        self.worker = None
        self.value = dict(phase='idle')
        self.closed = False
        self.validated = {}
        self._description = None
        self._description_key = None

    def start(self, config, *, prepare=False, refresh=False):
        cfg = validate_config(config)
        with self.lock:
            if self.closed:
                raise ValueError('Application is closing')
            if self.worker and self.worker.is_alive():
                raise ValueError('Catalog operation is already running')
            self.value = dict(phase='preparing' if prepare else 'checking', selection_key=inspection_key(cfg))
            self.worker = threading.Thread(target=self._run, args=(cfg, prepare, refresh),
                                           name='catalog-preparation', daemon=True)
            self.worker.start()
        return self.status()

    def _progress(self, message):
        with self.lock:
            if not self.closed:
                self.value['message'] = message

    def _run(self, config, prepare, refresh):
        from . import assets
        try:
            result = (assets.prepare(config, refresh=refresh, progress=self._progress)
                      if prepare else assets.check(config))
        except Exception as exc:
            result = dict(ok=False, phase='failed', error=str(exc))
        result['selection_key'] = inspection_key(config)
        with self.lock:
            if not self.closed:
                if result.get('ok') and result.get('catalog_stamp'):
                    self.validated[result['selection_key']] = (result['catalog_stamp'], result['catalog_identity'])
                elif not prepare:
                    self.validated.pop(result['selection_key'], None)
                self.value = result
                self._description_key = None

    def status(self):
        with self.lock:
            return deepcopy(self.value)

    def describe(self, config):
        from . import assets
        cfg = validate_config(config)
        selection = inspection_key(cfg)
        stamp = catalog_stamp(cfg)
        key = (selection, stamp)
        with self.lock:
            if key == self._description_key:
                return deepcopy(self._description)
        value = assets.describe(cfg)
        value['catalog_stamp'] = stamp
        with self.lock:
            value['validated'] = bool(value.get('available') and self.validated.get(selection) == (stamp, value.get('catalog_identity')))
            self._description_key, self._description = key, value
        return deepcopy(value)

    def close(self):
        with self.lock:
            self.closed = True
