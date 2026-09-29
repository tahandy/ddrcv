"""Bounded background login/splash OCR; no model work on the capture thread."""
from copy import deepcopy
import math
import threading
import time

from ddrcv.ocr import RapidOCRRecognizer, prepare_ddr_crop
from ddrcv.results.recognition import Evidence

NAME_BOXES = ((62, 463, 211, 34), (1006, 463, 212, 34))
# Each login band includes the DANCER NAME label and its name line. The label
# distinguishes the profile from league/card subpages sharing the login marker.
LOGIN_BOXES = ((212, 190, 338, 50), (646, 190, 338, 50))
SCREEN_BOXES = dict(song_splash=NAME_BOXES, login=LOGIN_BOXES)
DEFAULTS = dict(enabled=False, confidence=.8, sample_hz=5., min_frames=3,
                confirmation_seconds=.4, max_gap=.75, ocr={})


def validate_config(config=None):
    cfg = {**DEFAULTS, **deepcopy(config or {})}
    if type(cfg['enabled']) is not bool:
        raise ValueError('player_names.enabled must be boolean')
    for key in ('confidence', 'sample_hz', 'confirmation_seconds', 'max_gap'):
        value = cfg[key]
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError('Invalid player_names.' + key)
    if cfg['confidence'] > 1 or cfg['sample_hz'] > 5:
        raise ValueError('player_names confidence must be <=1 and sample_hz <=5')
    if type(cfg['min_frames']) is not int or cfg['min_frames'] < 2:
        raise ValueError('player_names.min_frames must be an integer >=2')
    if not isinstance(cfg['ocr'], dict):
        raise ValueError('player_names.ocr must be an object')
    RapidOCRRecognizer(**cfg['ocr'])  # Validates options without loading anything.
    return cfg


class PlayerNameReader:
    def __init__(self, config, recognizer=None):
        self.config = config
        self.ocr = recognizer or RapidOCRRecognizer(**config['ocr'])

    def warmup(self):
        self.ocr.warmup()

    def read(self, crops):
        values = {}
        keys = list(crops)
        readings = self.ocr.recognize_many([prepare_ddr_crop(crops[k]) for k in keys])
        for key, reading in zip(keys, readings):
            values[key] = self._name(reading)
        return values

    def read_login(self, crops):
        lines, keys = [], list(crops)
        for key in keys:
            band = crops[key]
            # The label may be cyan on green: don't white-text-trim it.
            lines.extend((band[:18, :125], prepare_ddr_crop(band[21:50, 8:338])))
        readings = self.ocr.recognize_many(lines)
        values = {key: None for key in keys}
        for i, key in enumerate(keys):
            label, name = readings[2*i:2*i+2]
            if (label.confidence >= self.config['confidence'] and
                    ''.join(label.text.upper().split()) == 'DANCERNAME'):
                values[key] = self._name(name)
        return values

    def _name(self, reading):
        text = reading.text.strip()
        return text if (reading.confidence >= self.config['confidence'] and
                        0 < len(text) <= 32 and all(c.isprintable() for c in text)) else None


# Preserve the earlier splash-reader import for existing callers.
SplashNameReader = PlayerNameReader


class PlayerNameService:
    def __init__(self, config=None, reader=None):
        self.config = validate_config(config)
        from ddrcv.jacket_lookup.names import LazyNameReader
        self.reader = reader if reader is not None else LazyNameReader(self.config)
        self.lock = threading.Condition()
        self.changed = threading.Event()
        self.closed = False
        self.pending = None
        self.busy = False
        self.generation = None
        self.screen = None
        self.run = 0
        self.presence = (True, True)
        self.names = dict(p1=None, p2=None)
        self.evidence = [Evidence(), Evidence()]
        self.last_timestamp = self.last_sample = -float('inf')
        self.replaced = 0
        self.error = None
        self.ready = False
        self.worker = None
        if self.config['enabled']:
            self.worker = threading.Thread(target=self._run, name='player-name-ocr', daemon=True)
            self.worker.start()

    def configure_enabled(self, enabled):
        if type(enabled) is not bool:
            raise ValueError('player_names.enabled must be boolean')
        with self.lock:
            if self.closed:
                raise ValueError('Name recognition is stopped')
            if enabled == self.config['enabled']:
                return
            self.config['enabled'] = enabled
            self.error = None
            self.reset(self.generation)
            if enabled and self.worker is None:
                self.worker = threading.Thread(target=self._run, name='player-name-ocr', daemon=True)
                self.worker.start()
            self.lock.notify_all()

    def reset(self, generation=None):
        with self.lock:
            self.generation = generation
            self.screen = None
            self.run += 1
            self.pending = None
            self.names = dict(p1=None, p2=None)
            self.evidence = [Evidence(), Evidence()]
            self.presence = (True, True)
            self.last_timestamp = self.last_sample = -float('inf')
            self.changed.set()

    def submit(self, frame, timestamp, raw_state, state, presence, generation):
        with self.lock:
            if self.closed:
                return
            if generation != self.generation:
                self.reset(generation)
            if timestamp <= self.last_timestamp:
                return
            self.last_timestamp = timestamp
            # Login evidence is useful through selection, but is not a fallback
            # for a song whose splash was missed (the existing per-song policy).
            if self.screen == 'login' and state in ('song_playing', 'song_result'):
                self.reset(generation)
                self.last_timestamp = timestamp
                return
            if not self.config['enabled'] or self.error:
                return
            if tuple(presence) != self.presence:
                self.presence = tuple(presence)
                self.run += 1
                self.pending = None
                self.evidence = [Evidence(), Evidence()]
                for key, present in zip(('p1', 'p2'), presence):
                    if not present:
                        self.names[key] = None
                self.changed.set()
            if raw_state != state or state not in SCREEN_BOXES:
                # Clean departures may finish the final sample. Interrupted
                # evidence must not bridge an unknown/wipe interval.
                if state in SCREEN_BOXES or state == 'unknown':
                    self.run += 1
                    self.pending = None
                    self.evidence = [Evidence(), Evidence()]
                return
            if self.screen != state:
                self.screen = state
                self.run += 1
                self.pending = None
                self.evidence = [Evidence(), Evidence()]
                self.names = dict(p1=None, p2=None)
                self.last_sample = -float('inf')
                self.changed.set()
            if timestamp - self.last_sample < 1 / self.config['sample_hz'] - 1e-6:
                return
            if frame.shape != (720, 1280, 3):
                raise ValueError('Player name OCR requires 1280x720 BGR capture')
            crops = {}
            for i, (present, box) in enumerate(zip(presence, SCREEN_BOXES[state])):
                if present and self.names['p' + str(i + 1)] is None:
                    x, y, w, h = box
                    crops[i] = frame[y:y+h, x:x+w].copy()
            if not crops:
                return
            self.last_sample = timestamp
            self.replaced += self.pending is not None
            self.pending = (self.generation, self.run, timestamp, state, crops)
            self.lock.notify()

    def snapshot(self):
        with self.lock:
            return dict(self.names)

    def status(self):
        with self.lock:
            phase = ('disabled' if not self.config['enabled'] else 'closed' if self.closed else
                     'failed' if self.error else 'ready' if self.ready else 'initializing')
            return dict(phase=phase, error=self.error, pending=int(self.pending is not None),
                        busy=self.busy, replaced_samples=self.replaced, screen=self.screen)

    def _run(self):
        while True:
            with self.lock:
                self.lock.wait_for(lambda: self.closed or (self.config['enabled'] and not self.error
                                   and (not self.ready or self.pending is not None)))
                if self.closed:
                    return
                warming = not self.ready
                epoch = self.run
                if not warming:
                    generation, run, timestamp, screen, crops = self.pending
                    self.pending = None
                    self.busy = True
            try:
                if warming:
                    self.reader.warmup()
                    with self.lock:
                        self.ready = True
                        self.changed.set()
                    continue
                readings = self.reader.read_login(crops) if screen == 'login' else self.reader.read(crops)
            except Exception as error:
                with self.lock:
                    self.busy = False
                    if self.closed:
                        return
                    if epoch != self.run:
                        continue
                    self.error = str(error)
                    self.pending = None
                    self.changed.set()
                continue
            with self.lock:
                self.busy = False
                if self.closed or not self.config['enabled'] or generation != self.generation or run != self.run:
                    continue
                for i in crops:
                    key = 'p' + str(i + 1)
                    if self.names[key] is not None:
                        continue
                    if self.evidence[i].observe(readings.get(i), timestamp,
                            self.config['min_frames'], self.config['confirmation_seconds'], self.config['max_gap']):
                        self.names[key] = readings[i]
                        self.changed.set()

    def close(self, timeout=1):
        with self.lock:
            self.closed = True
            self.run += 1
            self.pending = None
            self.lock.notify_all()
        deadline = time.monotonic() + max(0, timeout)
        if self.worker:
            self.worker.join(timeout=max(0, deadline - time.monotonic()))
        closer = getattr(self.reader, 'close', None) if callable(getattr(type(self.reader), 'close', None)) else None
        if closer:
            closer(timeout=max(0, deadline - time.monotonic()))
        return not any(worker.is_alive() for worker in self.threads())

    def threads(self):
        children = self.reader.threads() if callable(getattr(type(self.reader), 'threads', None)) else ()
        return tuple(w for w in (self.worker, *children) if isinstance(w, threading.Thread))
