"""Optional parallel splash stages and a bounded, generation-aware async adapter."""
from __future__ import annotations

from concurrent.futures import Future
from copy import deepcopy
import math
import threading
import time

import numpy as np

from .lookup import _finish_splash, _read_difficulty, _splash_parts
from .execution import worker_qos, run_with_qos
from .configuration import WORKING_CONFIG


class _LatestWorker:
    """One running call plus at most one pending call, with bounded shutdown."""
    def __init__(self, name):
        self.condition = threading.Condition()
        self.pending = None
        self.closed = False
        self.busy = False
        self.replaced = 0
        self.thread = threading.Thread(target=self._run, name=name, daemon=True)
        self.thread.start()

    def submit(self, function, *args, replace=True):
        future = Future()
        with self.condition:
            if self.closed:
                raise RuntimeError('Splash worker is closed')
            if self.pending is not None:
                if not replace:
                    raise RuntimeError('Splash worker already has a pending task')
                self.pending[0].cancel()
                self.replaced += 1
            self.pending = (future, function, args)
            self.condition.notify()
        return future

    def cancel_pending(self):
        with self.condition:
            if self.pending is not None:
                self.pending[0].cancel()
                self.pending = None

    def _run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda:self.closed or self.pending is not None)
                if self.closed:
                    return
                future, function, args = self.pending
                self.pending = None
                self.busy = True
            if future.set_running_or_notify_cancel():
                try:
                    result = function(*args)
                except BaseException as error:
                    future.set_exception(error)
                else:
                    future.set_result(result)
            with self.condition:
                self.busy = False

    def status(self):
        with self.condition:
            return dict(busy=self.busy, pending=int(self.pending is not None),
                        replaced=self.replaced, alive=self.thread.is_alive())

    def close(self, timeout=1):
        with self.condition:
            self.closed = True
            if self.pending is not None:
                self.pending[0].cancel()
                self.pending = None
            self.condition.notify_all()
        self.thread.join(timeout=max(0,timeout))
        return not self.thread.is_alive()


class ThreadedSplashLookup:
    """Run jacket lookup and difficulty reading concurrently for one sample.

    Calls on one instance serialize; use LatestSplashService to keep callers
    nonblocking. Give this instance exclusive use of its Lookup during analysis.
    """
    def __init__(self, lookup, *, recognizer=None, difficulty_reader=None, high_qos=WORKING_CONFIG.high_qos):
        if type(high_qos) is not bool:
            raise ValueError("high_qos must be boolean")
        self.lookup = lookup
        self.high_qos = high_qos
        self.recognizer = recognizer
        self.difficulty_reader = difficulty_reader
        self._difficulty = _LatestWorker('splash-difficulty')
        self._call_lock = threading.Lock()
        self._closed = False

    def analyze(self, frame, *, style='single', confirmed_song=None, remaining_players=None):
        with self._call_lock, worker_qos(self.high_qos):
            if self._closed:
                raise RuntimeError('Threaded splash lookup is closed')
            began = time.perf_counter()
            parts = _splash_parts(self.lookup,frame,style)
            if parts is None:
                return dict(accepted=False,reason='not_splash',players={},
                            timings_ms=dict(total=(time.perf_counter()-began)*1000))
            jacket,players,rois = parts
            if remaining_players is not None:
                selected = [(p, roi) for p, roi in zip(players, rois) if p in remaining_players]
                players = [p for p, _ in selected]
                rois = [roi for _, roi in selected]
            future = self._difficulty.submit(run_with_qos,self.high_qos,_read_difficulty,self.lookup,rois,
                self.recognizer,self.difficulty_reader,replace=False)
            try:
                result = (dict(accepted=True, reason='confirmed_song', song=confirmed_song,
                               candidates=[], timings_ms=dict(encode=0., search=0., verify=0., total=0.))
                          if confirmed_song is not None else self.lookup.lookup(jacket))
            finally:
                # Drain this sample's difficulty work even when jacket lookup
                # fails; a later sample must never consume its readings.
                readings = future.result()
            return _finish_splash(self.lookup,result,players,readings,style,began)

    def close(self, timeout=1):
        self._closed = True
        return self._difficulty.close(timeout)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class LatestSplashService:
    """Copy/enqueue quickly; publish only complete results for the current song.

    One active sample and one replaceable pending sample bound work and memory.
    Caller supplies the song generation, and must reset on seek/source changes.
    Names remain in the existing independent PlayerNameService.
    """
    def __init__(self, processor):
        self.processor = processor
        self._worker = _LatestWorker('splash-lookup')
        self._lock = threading.RLock()
        self.changed = threading.Event()
        self._generation = None
        self._epoch = 0
        self._sequence = 0
        self._last_timestamp = -math.inf
        self._closed = False
        self._latest = None

    def reset(self, generation):
        with self._lock:
            if self._closed:
                raise RuntimeError('Splash service is closed')
            self._generation = generation
            self._epoch += 1
            self._last_timestamp = -math.inf
            self._latest = None
            self._worker.cancel_pending()
            self.changed.set()

    def submit(self, frame, timestamp, generation, *, style='single'):
        if frame.dtype != np.uint8 or frame.shape != (720,1280,3):
            raise ValueError('Expected a uint8 1280x720 BGR splash')
        if style not in ('single','double') or not math.isfinite(timestamp):
            raise ValueError('Invalid style or timestamp')
        with self._lock:
            if self._closed:
                raise RuntimeError('Splash service is closed')
            if generation != self._generation:
                self.reset(generation)
            if timestamp <= self._last_timestamp:
                return None
            self._last_timestamp = timestamp
            self._sequence += 1
            sequence,epoch = self._sequence,self._epoch
            # Copy before returning: capture is free to reuse its input buffer.
            owned = frame.copy()
            future = self._worker.submit(lambda:self.processor.analyze(owned,style=style))
            future.add_done_callback(lambda completed:self._completed(
                completed,generation,epoch,sequence,timestamp))
            return sequence

    def _completed(self, future, generation, epoch, sequence, timestamp):
        if future.cancelled():
            return
        try:
            result,error = future.result(),None
        except Exception as exc:
            result,error = None,str(exc)
        with self._lock:
            if self._closed or epoch != self._epoch or generation != self._generation:
                return
            self._latest = dict(generation=generation,sequence=sequence,timestamp=timestamp,
                                result=result,error=error)
            self.changed.set()

    def snapshot(self):
        with self._lock:
            return deepcopy(self._latest)

    def status(self):
        with self._lock:
            return dict(generation=self._generation,closed=self._closed,**self._worker.status())

    def close(self, timeout=1):
        started = time.monotonic()
        with self._lock:
            self._closed = True
            self._epoch += 1
            self._latest = None
            self.changed.set()
        stopped = self._worker.close(timeout)
        remaining = max(0,timeout-(time.monotonic()-started))
        processor_stopped = self.processor.close(remaining)
        return stopped and processor_stopped

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
