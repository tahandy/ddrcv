"""Nonblocking capture adapter with bounded OCR work and a separate outbox."""
from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
import logging
from pathlib import Path
import threading
import time
from uuid import uuid4

from .delivery import Outbox, redact_error
from .recognition import Evidence, ResultsReader, outcome

LOG = logging.getLogger('ddrcv.results')
DEFAULTS = dict(enabled=False, discord=False, webhook=None, parse_names=True, confidence=.8,
                output_directory=None, include_player_names=True,
                sample_hz=5, settling_seconds=2., min_frames=5, confirmation_seconds=1.,
                max_gap=.75, deadline_seconds=10., only_duo=False, rehearsal=False)


def source_identity(source):
    """Stable file identity without hashing video contents or exposing RTSP credentials."""
    kind = source.get('kind', 'live')
    path = source.get('path', '')
    if kind == 'video':
        resolved = Path(path).resolve()
        stat = resolved.stat()
        value = f'{resolved}|{stat.st_size}|{stat.st_mtime_ns}'
    else:
        value = f'{kind}|{path}|{uuid4().hex}'
    return hashlib.sha256(value.encode()).hexdigest(), kind == 'video'


def load_config(path):
    path = Path(path)
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}


@dataclass
class Episode:
    generation: int
    source_id: str
    mode: str
    recorded: bool
    presence: tuple
    start: float
    end: float
    config: dict
    event_id: str = field(default_factory=lambda: uuid4().hex)
    pending: object = None
    scheduled: bool = False
    finish: bool = False
    finalized: bool = False
    run: int = 0
    evidence_run: int = -1
    last_sample: float = -float('inf')
    evidence: object = field(default_factory=lambda: [[Evidence(), Evidence()], [Evidence(), Evidence()]])
    best: object = None
    best_rank: int = -1
    latest: object = None
    saved: bool = False


class ResultsService:
    def __init__(self, directory, config=None, reader=None, sender=None, notify=None):
        self.config = {**DEFAULTS, **(config or {})}
        self._validate(self.config)
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.notify = notify
        self.reader = reader or ResultsReader(self.config)
        self.error = None
        self.phase = 'idle' if self.config['enabled'] else 'disabled'
        self.generation = 0
        self.source_id, self.recorded, self.mode = '', False, 'ex'
        self.active = None
        self.latched = False
        self.last_timestamp = None
        self.jobs = deque()
        self.busy = False
        self.writes = deque()
        self.interval_writes = set()
        self.persisting = False
        self.closed = False
        self.replaced_frames = 0
        self.deduplicated = 0
        kwargs = {} if sender is None else {'sender': sender}
        self.outbox = Outbox(directory, self.config['webhook'], self.config['discord'],
                             notify=self._announce, **kwargs)
        self.worker = threading.Thread(target=self._run, name='results-ocr', daemon=True)
        self.worker.start()
        self.persistence_worker = threading.Thread(target=self._persist, name='results-persistence', daemon=True)
        self.persistence_worker.start()

    @staticmethod
    def _validate(config):
        import math
        if type(config['parse_names']) is not bool:
            raise ValueError('results.parse_names must be a boolean')
        if type(config['include_player_names']) is not bool:
            raise ValueError('results.include_player_names must be a boolean')
        directory = config['output_directory']
        if directory is not None and (not isinstance(directory, str) or not directory.strip() or '\x00' in directory):
            raise ValueError('Results require a valid screenshot output directory')
        for key in ('sample_hz', 'settling_seconds', 'min_frames', 'confirmation_seconds', 'max_gap', 'deadline_seconds'):
            value = config[key]
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f'Invalid results setting: {key}')
        if not 0 <= config['confidence'] <= 1 or config['sample_hz'] > 5:
            raise ValueError('Results confidence must be 0..1 and sample_hz at most 5')
        if config['discord'] and not config['webhook']:
            raise ValueError('Set results.webhook before enabling Discord')

    def _announce(self):
        if self.notify:
            self.notify()

    def configure(self, **settings):
        with self.lock:
            config = {**self.config, **settings}
            self._validate(config)
            if config == self.config:
                return
            # A settings change must not publish the same live results screen twice.
            saved_episode = self.active if self.active and self.active.finalized else None
            latched = self.latched and (self.active is None or saved_episode is not None)
            self.config = config
            self._reset_locked()
            self.active = saved_episode
            self.latched = latched
        self.outbox.configure(config['webhook'], config['discord'])
        self._announce()

    def reset(self, source_id='', recorded=False, mode='ex'):
        if mode not in ('ex', 'money'):
            raise ValueError('score_mode must be ex or money')
        with self.lock:
            self.source_id, self.recorded, self.mode = source_id, recorded, mode
            self._reset_locked()

    def _reset_locked(self):
        if self.active and self.active.finalized:
            self.interval_writes.add(self.active.event_id)
        self.generation += 1
        self.active = None
        self.latched = False
        self.last_timestamp = None
        self.jobs.clear()
        self.phase = 'idle' if self.config['enabled'] else 'disabled'
        self.changed.notify_all()

    def status(self):
        with self.lock:
            status = dict(phase=self.phase, error=self.error, replaced_frames=self.replaced_frames,
                          deduplicated=self.deduplicated, pending=len(self.jobs), enabled=self.config['enabled'],
                          discord=self.config['discord'], parse_names=self.config['parse_names'],
                          rehearsal=self.config['rehearsal'], webhook_configured=bool(self.config['webhook']))
        outbox = self.outbox.snapshot()
        status['records'] = outbox['records']
        status['error'] = status['error'] or outbox['error']
        return status

    def feed_status(self):
        status = self.status()
        records = status.pop('records')
        status['latest'] = records[-1] if records else None
        return status

    def _schedule(self, episode):
        if episode.scheduled:
            return
        if len(self.jobs) >= 8:
            self.error = 'Results OCR queue saturated; pending result could not be accepted'
            LOG.error(self.error)
            return
        episode.scheduled = True
        self.jobs.append(episode)
        self.changed.notify_all()

    def submit(self, frame, timestamp, raw_state, state, presence=(True, True), frame_index=None):
        """Only copies sampled pixels and updates small in-memory state; never waits on OCR/I/O."""
        with self.lock:
            if self.closed:
                return
            if self.last_timestamp is not None and timestamp <= self.last_timestamp:
                return
            self.last_timestamp = timestamp
            confirmed_other = state not in ('song_result', 'unknown')
            if confirmed_other:
                if self.active:
                    self.finish()
                self.latched = False
                return
            if not self.config['enabled']:
                return
            if raw_state != 'song_result' or state != 'song_result':
                if self.active:
                    self.active.run += 1
                    if timestamp - self.active.start >= self.active.config['deadline_seconds']:
                        self._finalize(self.active)
                return
            if not self.latched:
                self.latched = True
                if self.config['only_duo'] and not all(presence):
                    self.phase = 'single_player_skipped'
                    return
                if not any(presence):
                    return
                existing = self.outbox.find(self.source_id, timestamp, self.mode) if self.recorded else None
                if existing:
                    self.deduplicated += 1
                    self.phase = 'already_saved'
                    return
                self.active = Episode(self.generation, self.source_id, self.mode, self.recorded,
                                      tuple(presence), timestamp, timestamp, deepcopy(self.config))
                self.phase = 'settling'
            ep = self.active
            if ep is None:
                return
            ep.end = timestamp
            if ep.finalized:
                self.outbox.observe_interval(ep.event_id, ep.source_id, ep.mode, ep.start, ep.end)
                if timestamp - ep.last_sample >= .5:
                    ep.last_sample = timestamp
                    self.interval_writes.add(ep.event_id)
                    self.changed.notify_all()
                return
            if timestamp - ep.last_sample < 1 / ep.config['sample_hz'] - 1e-6:
                return
            ep.last_sample = timestamp
            if ep.pending is not None:
                self.replaced_frames += 1
            ep.pending = (frame.copy(), timestamp, frame_index, ep.run)
            if ep.best is None:
                ep.best = self._fallback(ep, ep.pending)
            if timestamp - ep.start >= ep.config['deadline_seconds']:
                self._finalize(ep)
            else:
                self._schedule(ep)

    def finish(self):
        """EOF/stop: finalize retained evidence without inventing additional observations."""
        with self.lock:
            if self.active:
                ep = self.active
                ep.finish = True
                self._finalize(ep)
                self.interval_writes.add(ep.event_id)
                self.active = None
                self.changed.notify_all()

    @staticmethod
    def _fallback(ep, sample):
        frame, timestamp, index, _ = sample
        players = [dict(present=p, name=None, score=None) for p in ep.presence]
        return frame, timestamp, index, players, False

    def flush(self, timeout=5):
        """For replay tests/shutdown only. Never called by the frame loop."""
        deadline = time.monotonic() + timeout
        with self.changed:
            while (self.jobs or self.busy or self.writes or self.interval_writes or self.persisting) and time.monotonic() < deadline:
                self.changed.wait(max(0, deadline - time.monotonic()))
            return not (self.jobs or self.busy or self.writes or self.interval_writes or self.persisting)

    def _run(self):
        while True:
            with self.changed:
                self.changed.wait_for(lambda: self.jobs or self.closed)
                if self.closed:
                    return
                ep = self.jobs.popleft()
                ep.scheduled = False
                sample, ep.pending = ep.pending, None
                self.busy = True
            try:
                if ep.generation != self.generation or ep.finalized or self.closed:
                    continue
                if sample:
                    self._observe(ep, sample)
                if ep.finish and not ep.finalized:
                    self._finalize(ep)
            except Exception as exc:
                self.error = redact_error(exc, self.config.get('webhook'))
                self.phase = 'failed'
                LOG.error('Results processing: %s', self.error)
                self._announce()
            finally:
                with self.changed:
                    self.busy = False
                    self.changed.notify_all()

    def _observe(self, ep, sample):
        frame, timestamp, index, run = sample
        with self.lock:
            if self.closed or ep.finalized or ep.generation != self.generation:
                return
            ep.latest = self._fallback(ep, sample)
            if timestamp - ep.start < ep.config['settling_seconds']:
                ep.best = ep.latest
                return
        try:
            # Only the OCR worker changes reader options; an in-flight old read is
            # rejected below by its episode generation after configuration changes.
            if isinstance(self.reader, ResultsReader):
                self.reader.parse_names = ep.config['parse_names']
            readings = self.reader.read(frame, ep.presence, ep.mode)
        except Exception as exc:
            with self.lock:
                if self.closed or ep.finalized or ep.generation != self.generation:
                    return
                self.error = redact_error(exc, ep.config.get('webhook'))
                self.phase = 'ocr_failed'
            self._announce()
            return
        with self.lock:
            # EOF and shutdown can seal retained evidence while OCR is blocked.
            if self.closed or ep.finalized or ep.generation != self.generation:
                return
            self.error = None
            if ep.evidence_run != run:
                ep.evidence = [[Evidence(), Evidence()], [Evidence(), Evidence()]]
                ep.evidence_run = run
            players = [dict(present=p, name=None, score=None) for p in ep.presence]
            for i, present in enumerate(ep.presence):
                if not present:
                    continue
                for j, field_name in enumerate(('name', 'score')):
                    if field_name == 'name' and not ep.config['parse_names']:
                        continue
                    value = readings[i][field_name]
                    stable = ep.evidence[i][j].observe(value, timestamp, ep.config['min_frames'],
                        ep.config['confirmation_seconds'], ep.config['max_gap'])
                    if stable:
                        players[i][field_name] = value
            complete = all(p['score'] is not None and (not ep.config['parse_names'] or p['name'] is not None)
                           for p in players if p['present'])
            ep.latest = (frame, timestamp, index, players, complete)
            # Keep a frame and its own evidence together; contradictions invalidate fields.
            ep.best = ep.latest
            self.phase = 'confirming'
            if complete:
                self._finalize(ep)

    def _finalize(self, ep):
        with self.lock:
            if self.closed or ep.generation != self.generation or ep.finalized or ep.best is None:
                return
            if len(self.writes) >= 8:
                self.error = 'Results persistence queue saturated; result could not be accepted'
                LOG.error(self.error)
                return
            frame, timestamp, index, players, stable = ep.best
            record = dict(event_id=ep.event_id, source_id=ep.source_id, recorded=ep.recorded,
                interval=[ep.start, ep.end], timestamp=timestamp, frame_index=index, score_mode=ep.mode,
                players=deepcopy(players), parse_names=ep.config['parse_names'],
                output_directory=ep.config['output_directory'], include_player_names=ep.config['include_player_names'],
                partial=not stable, screenshot_confirmed=stable,
                outcome=outcome(players, ep.mode), rehearsal=ep.config['rehearsal'],
                auto_publish=ep.config['discord'], created_at=time.time())
            ep.finalized = True
            ep.pending = None
            self.phase = 'saving'
            # Reserve before disk I/O so an immediate loop/seek cannot create a duplicate.
            self.outbox.observe_interval(ep.event_id, ep.source_id, ep.mode, ep.start, ep.end)
            self.writes.append((ep, record, frame))
            self.changed.notify_all()

    def _persist(self):
        try:
            while True:
                with self.changed:
                    self.changed.wait_for(lambda: self.writes or self.interval_writes or self.closed)
                    if not self.writes and not self.interval_writes and self.closed:
                        return
                    bundle = self.writes.popleft() if self.writes else None
                    event_id = None if bundle else self.interval_writes.pop()
                    self.persisting = True
                try:
                    if bundle:
                        ep, record, frame = bundle
                        self.outbox.save(record, frame)
                        with self.lock:
                            ep.saved = True
                            self.phase = 'saved'
                    else:
                        self.outbox.persist_interval(event_id)
                except Exception as exc:
                    with self.lock:
                        self.error = redact_error(exc, self.config.get('webhook'))
                        self.phase = 'failed'
                        if bundle:
                            ep.finalized = False
                            self.outbox.forget_interval(ep.event_id)
                    LOG.error('Results persistence: %s', self.error)
                finally:
                    with self.changed:
                        self.persisting = False
                        self.changed.notify_all()
                    self._announce()
        finally:
            # Ownership lasts until every possible producer write has finished.
            self.outbox.close(timeout=0)

    def retry(self, event_id, republish=False):
        self.outbox.command('republish' if republish else 'retry', event_id)

    def close(self, timeout=3):
        deadline = time.monotonic() + timeout
        with self.changed:
            if not self.closed:
                self.finish()
                self.closed = True
                self.jobs.clear()
                self.changed.notify_all()
        # A blocked recognizer cannot mutate sealed records or write to disk.
        self.persistence_worker.join(max(0, deadline - time.monotonic()))
        self.outbox.worker.join(max(0, deadline - time.monotonic()))
        self.worker.join(max(0, deadline - time.monotonic()))
