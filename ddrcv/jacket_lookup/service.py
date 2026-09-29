"""Shared asynchronous song/chart/name coordinator for maintained producers."""
from copy import deepcopy
import math
import threading
import time

from .config import validate_config
from .threaded import _LatestWorker


class Agreement:
    def __init__(self):
        self.clear()

    def clear(self):
        self.key = None
        self.first = self.last = None
        self.count = 0

    def observe(self, key, timestamp):
        if key is None:
            self.clear()
            return False
        if self.key != key or self.last is None or timestamp - self.last > .75:
            self.key, self.first, self.count = key, timestamp, 0
        self.last = timestamp
        self.count += 1
        return self.count >= 2 and timestamp - self.first >= .2 - 1e-9


class SplashService:
    def __init__(self, config=None, names_config=None, *, names=None, processor=None, lookup=None):
        self.config = validate_config(config)
        if names is None:
            from ddrcv.state.player_names import PlayerNameService
            from .names import LazyNameReader
            names = PlayerNameService(names_config, reader=LazyNameReader(
                names_config, high_qos=self.config['high_qos']))
        self.names = names
        self.lock = threading.RLock()
        self.changed = threading.Event()
        self.closed = False
        self.generation = None
        self.epoch = 0
        self.worker = None
        self.processor = processor
        self.error = None
        self.last_reason = None
        self.timings = {}
        self.completed = 0
        self.song = None
        self.confirmed_candidate = None
        self.song_evidence = Agreement()
        self.chart_evidence = [Agreement(), Agreement()]
        self.presence = (True, True)
        self.last_timestamp = self.last_sample = -math.inf
        self.eligible = False
        if self.config['enabled']:
            try:
                if processor is None:
                    from .assets import processor as create_processor
                    self.processor = create_processor(self.config, lookup=lookup)
                self.worker = _LatestWorker('splash-lookup')
            except Exception as exc:
                self.error = str(exc)

    def has_changes(self):
        return self.changed.is_set() or self.names.changed.is_set()

    def clear_changes(self):
        self.changed.clear()
        self.names.changed.clear()

    def _clear_evidence(self):
        self.song_evidence.clear()
        for evidence in self.chart_evidence:
            evidence.clear()

    def reset(self, generation=None):
        with self.lock:
            self.generation = generation
            self.epoch += 1
            if self.worker:
                self.worker.cancel_pending()
            self.song = self.confirmed_candidate = None
            self.presence = (True, True)
            self._clear_evidence()
            self.last_timestamp = self.last_sample = -math.inf
            self.eligible = False
            self.last_reason = None
            self.names.reset(generation)
            self.changed.set()

    def submit(self, frame, timestamp, raw_state, state, presence, generation):
        with self.lock:
            if generation != self.generation:
                self.reset(generation)
            if self.closed:
                return
            self.names.submit(frame, timestamp, raw_state, state, presence, generation)
            if not self.worker or not math.isfinite(timestamp) or timestamp <= self.last_timestamp:
                return
            self.last_timestamp = timestamp
            if raw_state != 'song_splash' or state != 'song_splash':
                if self.eligible:
                    self.epoch += 1
                    self.worker.cancel_pending()
                    self._clear_evidence()
                self.eligible = False
                return
            self.eligible = True
            if tuple(presence) != self.presence:
                self.presence = tuple(presence)
                self.epoch += 1
                self.worker.cancel_pending()
                self._clear_evidence()
                if self.song:
                    for i, present in enumerate(presence, 1):
                        if not present:
                            self.song['charts'][f'p{i}'] = None
                self.changed.set()
            remaining = [p for p in (1, 2) if presence[p-1] and
                         (not self.song or self.song['charts'][f'p{p}'] is None)]
            if (self.song is not None and not remaining) or timestamp - self.last_sample < .2 - 1e-9:
                return
            if frame.dtype.name != 'uint8' or frame.shape != (720, 1280, 3):
                self.error = 'Expected a uint8 1280x720 BGR splash'
                self.changed.set()
                return
            self.last_sample = timestamp
            epoch = self.epoch
            owned = frame.copy()
            confirmed = deepcopy(self.confirmed_candidate)
            future = self.worker.submit(
                lambda: self.processor.analyze(owned, style=self.config['style'],
                                               confirmed_song=confirmed, remaining_players=remaining))
            future.add_done_callback(lambda f: self._completed(f, generation, epoch, timestamp))

    def _completed(self, future, generation, epoch, timestamp):
        if future.cancelled():
            return
        try:
            result, error = future.result(), None
        except Exception as exc:
            result, error = None, str(exc)
        with self.lock:
            if self.closed or self.epoch != epoch or self.generation != generation:
                return
            self.completed += 1
            self.error = error
            if error:
                self._clear_evidence()
                self.changed.set()
                return
            self.timings = result.get('timings_ms', {})
            self.last_reason = result.get('reason')
            accepted = result.get('accepted', False)
            candidate = result.get('song') if accepted else None
            sid = candidate['song_id'] if candidate else None
            if self.song is None and self.song_evidence.observe(sid, timestamp):
                selected = self.processor.selection['catalog']
                row = next((r for r in selected['records'] if r['song_id'] == sid), None)
                if row is None:
                    row = next((r for r in self.processor.lookup.catalog['records'] if r['song_id'] == sid), {})
                self.song = dict(song_id=sid, title=candidate['name'], artist=row.get('artist'),
                                 catalog=dict(mode=selected['mode'], event=selected['event'],
                                              dataset=selected['metadata_dataset'], commit=selected['commit'],
                                              gallery=self.processor.selection.get('gallery_fingerprint')),
                                 charts=dict(p1=None, p2=None))
                self.confirmed_candidate = deepcopy(candidate)
            for i, evidence in enumerate(self.chart_evidence, 1):
                key = f'p{i}'
                if not self.presence[i-1] or (self.song and self.song['charts'][key] is not None):
                    continue
                chart = result.get('players', {}).get(key, {})
                diff = chart.get('difficulty')
                agreed = evidence.observe((sid, self.config['style'], diff) if sid and diff else None, timestamp)
                if agreed and self.song is not None and self.song['song_id'] == sid:
                    self.song['charts'][key] = dict(
                        style=self.config['style'], difficulty=diff,
                        level=chart.get('metadata_level'), max_ex=chart.get('max_ex'),
                        status=chart['status'],
                        provenance=dict(dataset=chart.get('source_dataset'),
                                        commit=chart.get('source_commit')))
            self.changed.set()

    def snapshot(self):
        with self.lock:
            if self.closed:
                return dict(song=None, player_names=dict(p1=None, p2=None))
            return dict(song=deepcopy(self.song), player_names=self.names.snapshot())

    def status(self):
        with self.lock:
            done = self.song is not None and all(
                not present or self.song['charts'][f'p{i+1}'] is not None
                for i, present in enumerate(self.presence))
            phase = ('closed' if self.closed else 'disabled' if not self.config['enabled'] else 'failed' if self.error else
                     'confirmed' if done else 'recognizing' if self.last_sample != -math.inf else 'ready')
            return dict(phase=phase, error=self.error, reason=self.last_reason,
                        completed=self.completed, timings_ms=deepcopy(self.timings),
                        catalog=deepcopy(getattr(getattr(self.processor, 'lookup', None), 'bundle_info', None)),
                        **(self.worker.status() if self.worker else dict(busy=False, pending=0, replaced=0, alive=False)))

    def threads(self):
        own = (self.worker.thread,) if self.worker else ()
        children = self.processor.threads() if self.processor and hasattr(self.processor, 'threads') else ()
        return (*own, *children, *self.names.threads())

    def close(self, timeout=2):
        deadline = time.monotonic() + max(0, timeout)
        with self.lock:
            self.closed = True
            self.epoch += 1
            self.song = self.confirmed_candidate = None
            self._clear_evidence()
            self.changed.set()
        if self.worker:
            self.worker.close(max(0, deadline-time.monotonic()))
        if self.processor:
            self.processor.close(max(0, deadline-time.monotonic()))
        self.names.close(max(0, deadline-time.monotonic()))
        return not any(w.is_alive() for w in self.threads())
