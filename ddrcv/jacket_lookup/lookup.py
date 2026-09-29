"""Conservative image identity and per-player chart resolution."""
from __future__ import annotations

from pathlib import Path
from io import BytesIO
import json
import re
import time
from threading import Lock

import cv2
import numpy as np

from .catalog import ChartIndex, sha256
from .images import crop, DIFFICULTY_ROIS
from .features import Encoder, PortableEncoder, resize


def correlation(query, reference):
    border = 4
    target = query[border:-border, border:-border]
    return _correlation(target, cv2.cvtColor(target, cv2.COLOR_BGR2GRAY), reference,
                        cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY))


def _correlation(target, target_gray, reference, reference_gray):
    gray = cv2.matchTemplate(reference_gray, target_gray, cv2.TM_CCOEFF_NORMED)
    color = cv2.matchTemplate(reference, target, cv2.TM_CCOEFF_NORMED)
    return float(np.max(.8*gray + .2*color))


class Lookup:
    def __init__(self, index_dir, *, model_dir=None, thresholds=None, encoder_factory=Encoder):
        began = time.perf_counter()
        index_dir = Path(index_dir)
        self._initialize((index_dir / 'index.json').read_bytes(),
                         (index_dir / 'vectors.npz').read_bytes(), model_dir=model_dir,
                         thresholds=thresholds, encoder_factory=encoder_factory, began=began)

    @classmethod
    def from_bytes(cls, metadata, arrays, *, thresholds=None):
        instance = cls.__new__(cls)
        instance._initialize(metadata, arrays, thresholds=thresholds)
        return instance

    def _initialize(self, metadata, arrays_data, *, model_dir=None, thresholds=None,
                    encoder_factory=Encoder, began=None):
        began = time.perf_counter() if began is None else began
        self.meta = json.loads(metadata)
        if thresholds and thresholds.get('index_sha256') and thresholds['index_sha256'] != sha256(metadata):
            raise ValueError('Threshold profile belongs to another index; recalibrate or select its matching profile')
        self.catalog = self.meta['catalog']
        if sha256(arrays_data) != self.meta['arrays_sha256']:
            raise ValueError('Index array checksum mismatch')
        with np.load(BytesIO(arrays_data), allow_pickle=False) as arrays:
            self.vectors = arrays['vectors'].copy()
            self.images = arrays['images'].copy()
        if encoder_factory is Encoder and self.meta['fingerprint'] == PortableEncoder.fingerprint:
            encoder_factory = PortableEncoder
        self.encoder = encoder_factory(self.meta['method'], self.meta['size'], model_dir)
        if self.encoder.fingerprint != self.meta['fingerprint']:
            raise ValueError('Index encoder fingerprint mismatch; rebuild index')
        self.entries = self.meta['entries']
        if len(self.vectors) != len(self.entries) or len(self.images) != len(self.entries):
            raise ValueError('Index entry/array mismatch')
        if thresholds and thresholds.get('gallery_fingerprint'):
            from .fingerprint import gallery_fingerprint
            if gallery_fingerprint(self.meta, self.vectors, self.images) != thresholds['gallery_fingerprint']:
                raise ValueError('Gallery does not match its frozen acceptance profile')
        self.thresholds = thresholds
        self._charts = ChartIndex(self.catalog)
        self._reference_grays = [None] * len(self.images)
        self._splash_detector = None
        self._default_recognizer = None
        self._component_lock = Lock()
        self.cold_seconds = time.perf_counter()-began

    def _get_splash_detector(self):
        if self._splash_detector is None:
            with self._component_lock:
                if self._splash_detector is None:
                    from .splash import SplashDetector
                    self._splash_detector = SplashDetector()
        return self._splash_detector

    def _get_recognizer(self):
        if self._default_recognizer is None:
            with self._component_lock:
                if self._default_recognizer is None:
                    from ddrcv.ocr.rapid import RapidOCRRecognizer
                    self._default_recognizer = RapidOCRRecognizer(allow_download=False, num_threads=1)
        return self._default_recognizer

    def _verify_correlation(self, target, target_gray, index):
        reference_gray = self._reference_grays[index]
        if reference_gray is None:
            reference_gray = cv2.cvtColor(self.images[index], cv2.COLOR_BGR2GRAY)
            self._reference_grays[index] = reference_gray
        return _correlation(target, target_gray, self.images[index], reference_gray)

    def _prepare_verification(self, query):
        target = np.ascontiguousarray(query[4:-4, 4:-4])
        return target, cv2.cvtColor(target, cv2.COLOR_BGR2GRAY)

    def _verify_candidate(self, context, index, similarities):
        return self._verify_correlation(*context, index)

    def lookup(self, image, *, color_order='bgr', exclude_song_ids=(), top_k=5):
        began = time.perf_counter()
        if color_order not in ('bgr', 'rgb'):
            raise ValueError('color_order must be bgr or rgb')
        if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3 or min(image.shape[:2]) < 8:
            raise ValueError('Expected a non-empty uint8 HxWx3 jacket crop')
        query = resize(image if color_order == 'bgr' else image[..., ::-1], self.meta['size'])
        vector = self.encoder.encode(query)
        encoded = time.perf_counter()
        similarities = self.vectors @ vector
        excluded = set(exclude_song_ids)
        if excluded:
            valid = np.array([not excluded.intersection(e['songs']) for e in self.entries])
            similarities[~valid] = -np.inf
        ranked = np.argsort(-similarities)[:max(16, top_k*2)]
        ranked = [int(i) for i in ranked if np.isfinite(similarities[i])]
        searched = time.perf_counter()
        context = self._prepare_verification(query)
        scored = []
        for index in ranked:
            score = self._verify_candidate(context, index, similarities)
            scored.append((score, index))
        scored.sort(reverse=True)
        # Aggregate all artwork aliases before computing distinct-song margins.
        candidates = {}
        for score, index in scored:
            entry = self.entries[index]
            identities = entry['songs'] or {f"unmapped:{entry['sha256']}": None}
            for sid, name in identities.items():
                if sid not in candidates:
                    candidates[sid] = dict(song_id=sid, name=name, score=score,
                        descriptor_score=float(similarities[index]), index=index,
                        jackets=entry['paths'], shared_artwork=len(identities) > 1)
        ordered = sorted(candidates.values(), key=lambda c: -c['score'])
        best = ordered[0] if ordered else None
        margin = best['score']-ordered[1]['score'] if len(ordered) > 1 else 0.0
        reason = 'uncalibrated'
        if not best:
            reason = 'empty_catalog'
        elif best['name'] is None:
            reason = 'unmapped_artwork'
        elif best['shared_artwork']:
            reason = 'ambiguous_artwork'
        elif self.thresholds:
            reason = ('low_similarity' if best['score'] < self.thresholds['score'] else
                      'small_margin' if margin < self.thresholds['margin'] else 'matched')
        ended = time.perf_counter()
        return dict(accepted=reason == 'matched', reason=reason,
            song=best if reason == 'matched' else None, candidates=ordered[:top_k],
            margin=margin, thresholds=self.thresholds,
            timings_ms=dict(encode=(encoded-began)*1000, search=(searched-encoded)*1000,
                            verify=(ended-searched)*1000, total=(ended-began)*1000))


DIFFICULTIES = ('beginner', 'basic', 'difficult', 'expert', 'challenge')


def parse_difficulty(text, confidence, minimum=.85):
    # Exact class tokens plus the visible level; no fuzzy correction of uncertain OCR.
    cleaned = re.sub(r'[^a-z0-9 ]', '', text.lower())
    match = re.fullmatch(r'\s*(beginner|basic|difficult|expert|challenge)\s*(\d{1,2})\s*', cleaned)
    if not match or confidence < minimum or not 1 <= int(match[2]) <= 20:
        return None
    return dict(difficulty=match[1], level=int(match[2]))


def _splash_parts(lookup, frame, style):
    if style not in ('single', 'double') or frame.shape != (720, 1280, 3):
        raise ValueError('Expected a 1280x720 splash and explicit single/double style')
    matched, presence = lookup._get_splash_detector().match(frame[..., ::-1])
    if not matched:
        return None
    players = [p for p in (1, 2) if presence[f'p{p}_present']]
    return crop(frame), players, [crop(frame, DIFFICULTY_ROIS[p-1]) for p in players]


def _read_difficulty(lookup, rois, recognizer, difficulty_reader):
    if difficulty_reader is None:
        ocr = recognizer or lookup._get_recognizer()
        started = time.perf_counter()
        readings = ocr.recognize_many(rois, color_order='bgr')
        parsed = [(parse_difficulty(r.text, r.confidence),
                   dict(ocr_text=r.text, ocr_score=r.confidence)) for r in readings]
        method = 'ocr'
    else:
        started = time.perf_counter()
        readings = [difficulty_reader.recognize(roi) for roi in rois]
        parsed = [(dict(difficulty=r['difficulty']) if r['accepted'] else None,
                   dict(recognition=r)) for r in readings]
        method = 'template'
    return method, parsed, (time.perf_counter()-started)*1000


def _finish_splash(lookup, result, players, readings, style, began):
    method, parsed_readings, elapsed = readings
    joining = time.perf_counter()
    result['difficulty_method'] = method
    result['players'] = {}
    for p, (parsed, evidence) in zip(players, parsed_readings):
        chart = dict(status='uncertain_chart', max_ex=None)
        if parsed and result['accepted']:
            chart = lookup._charts.resolve(result['song']['song_id'], style,
                                          parsed['difficulty'], parsed.get('level'))
        elif parsed:
            chart['status'] = 'song_unconfirmed'
        result['players'][f'p{p}'] = dict(style=style, **(parsed or {}), **chart, **evidence)
    elapsed += (time.perf_counter()-joining)*1000
    result['timings_ms']['difficulty'] = elapsed
    result['timings_ms'][method] = elapsed
    result['timings_ms']['splash_total'] = (time.perf_counter()-began)*1000
    return result


def lookup_splash(lookup, frame, *, style='single', recognizer=None, difficulty_reader=None):
    began = time.perf_counter()
    parts = _splash_parts(lookup, frame, style)
    if parts is None:
        return dict(accepted=False, reason='not_splash', players={}, timings_ms=dict(total=(time.perf_counter()-began)*1000))
    jacket, players, rois = parts
    result = lookup.lookup(jacket)
    readings = _read_difficulty(lookup, rois, recognizer, difficulty_reader)
    return _finish_splash(lookup, result, players, readings, style, began)
