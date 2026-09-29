"""Name reader with one persistent OCR worker per player."""
from __future__ import annotations

import threading
import time

from .threaded import _LatestWorker
from .execution import run_with_qos
from .configuration import WORKING_CONFIG


def _drain(futures):
    """Finish every branch before returning or propagating a sample's error."""
    results, error = {}, None
    for key, future in futures.items():
        try:
            results[key] = future.result()
        except Exception as exc:
            if error is None:
                error = exc
    if error is not None:
        raise error
    return results


class PerPlayerNameReader:
    """PlayerNameReader-compatible API, using two independent model instances.

    read/read_login are blocking; run them on a name-service worker, independently
    of chart lookup. Calls on one reader serialize, so no unbounded queue forms.
    A supplied factory must create a fresh reader with its own recognizer per call.
    """
    def __init__(self, config=None, *, reader_factory=None, high_qos=WORKING_CONFIG.high_qos):
        from ddrcv.state.player_names import PlayerNameReader, validate_config

        if type(high_qos) is not bool:
            raise ValueError("high_qos must be boolean")
        config = dict(config or {})
        config['ocr'] = {'num_threads': WORKING_CONFIG.name_threads, **config.get('ocr', {}),
                         'allow_download': False}
        self.config = validate_config(config)
        self.high_qos = high_qos
        factory = reader_factory or PlayerNameReader
        self.readers = [factory(self.config) for _ in range(2)]
        if self.readers[0] is self.readers[1]:
            raise ValueError('Each player needs an independent reader')
        if (getattr(self.readers[0], 'ocr', None) is not None and
                self.readers[0].ocr is getattr(self.readers[1], 'ocr', None)):
            raise ValueError('Each player needs an independent OCR recognizer')
        self._workers = [_LatestWorker(f'splash-name-p{i+1}') for i in range(2)]
        self._lock = threading.Lock()
        self._closed = False

    def _check_open(self):
        if self._closed:
            raise RuntimeError('Per-player name reader is closed')

    def warmup(self):
        with self._lock:
            self._check_open()
            _drain({i:worker.submit(run_with_qos, self.high_qos, self.readers[i].warmup, replace=False)
                    for i, worker in enumerate(self._workers)})

    def _read(self, crops, method):
        with self._lock:
            self._check_open()
            if any(type(key) is not int or key not in (0, 1) for key in crops):
                raise ValueError('Name crops must use player keys 0 and/or 1')
            owned = {key: image.copy() for key, image in crops.items()}
            results = _drain({key:self._workers[key].submit(
                run_with_qos, self.high_qos, getattr(self.readers[key], method), {key:image}, replace=False)
                for key, image in owned.items()})
            return {key:results[key][key] for key in owned}

    def read(self, crops):
        return self._read(crops, 'read')

    def read_login(self, crops):
        return self._read(crops, 'read_login')

    def threads(self):
        return tuple(worker.thread for worker in self._workers)

    def close(self, timeout=1):
        self._closed = True
        deadline = time.monotonic() + max(0, timeout)
        stopped = [worker.close(max(0, deadline-time.monotonic()))
                   for worker in self._workers]
        return all(stopped)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class LazyNameReader:
    """Defer both OCR sessions/workers until the name service actually needs them."""
    def __init__(self, config=None, *, high_qos=True):
        self.config = config
        self.high_qos = high_qos
        self._reader = None
        self._closed = False
        self._guard = threading.Lock()

    def _get(self):
        with self._guard:
            if self._closed:
                raise RuntimeError('Name reader is closed')
            if self._reader is None:
                self._reader = PerPlayerNameReader(self.config, high_qos=self.high_qos)
            return self._reader

    def warmup(self):
        return self._get().warmup()

    def read(self, crops):
        return self._get().read(crops)

    def read_login(self, crops):
        return self._get().read_login(crops)

    def threads(self):
        with self._guard:
            return tuple(w.thread for w in self._reader._workers) if self._reader else ()

    def close(self, timeout=1):
        with self._guard:
            self._closed = True
            reader = self._reader
        return reader.close(timeout) if reader else True
