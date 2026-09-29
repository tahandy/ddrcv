"""One explicit background preparation/readiness operation for an operator UI."""
from copy import deepcopy
import threading

from .config import validate_config


class CatalogPreparation:
    def __init__(self):
        self.lock = threading.Lock()
        self.worker = None
        self.value = dict(phase='idle')
        self.closed = False
        self._description = None
        self._description_key = None

    def start(self, config, *, prepare=False, refresh=False):
        cfg = validate_config(config)
        with self.lock:
            if self.closed:
                raise ValueError('Application is closing')
            if self.worker and self.worker.is_alive():
                raise ValueError('Catalog operation is already running')
            self.value = dict(phase='preparing' if prepare else 'checking')
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
        with self.lock:
            if not self.closed:
                self.value = result
                self._description_key = None

    def status(self):
        with self.lock:
            return deepcopy(self.value)

    def describe(self, config):
        from . import assets
        from .config import assets_root, catalog_path
        cfg = validate_config(config)
        root = assets_root(cfg)
        destination = catalog_path(cfg)
        pointer = destination if destination.exists() or cfg['catalog_file'] else root / 'active' / (assets.selection_key(cfg) + '.json')
        try:
            stat = pointer.stat()
            stamp = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
        except OSError:
            stamp = None
        key = (str(root), str(destination), assets.selection_key(cfg), stamp)
        with self.lock:
            if key == self._description_key:
                return deepcopy(self._description)
        value = assets.describe(cfg)
        with self.lock:
            self._description_key, self._description = key, value
        return deepcopy(value)

    def close(self):
        with self.lock:
            self.closed = True
