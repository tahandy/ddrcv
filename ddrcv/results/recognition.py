"""Pure crop parsing and temporal evidence. Frames are OpenCV BGR, 1280x720."""
from dataclasses import dataclass
import re

from ddrcv.ocr import RapidOCRRecognizer, prepare_ddr_crop

NAME_BOXES = ((242, 88, 222, 29), (816, 88, 223, 29))
# EX mode: omit the EX label immediately left of these digits.
EX_BOXES = ((348, 347, 167, 57), (875, 347, 168, 57))
MONEY_BOXES = ((269, 348, 246, 56), (797, 348, 246, 56))


def parse_number(text, mode):
    text = text.strip()
    if not re.fullmatch(r'(?:[0-9]{1,7}|[0-9]{1,3}(?:,[0-9]{3}){1,2})', text):
        return None
    value = int(text.replace(',', ''))
    return value if value <= (99999 if mode == 'ex' else 1000000) else None


class ResultsReader:
    def __init__(self, config=None, recognizer=None):
        config = config or {}
        self.confidence = float(config.get('confidence', .8))
        self.parse_names = config.get('parse_names', True)
        self.ocr = recognizer or RapidOCRRecognizer(**config.get('ocr', {}))

    def warmup(self):
        self.ocr.warmup()

    def read(self, frame, presence, mode):
        if frame.shape != (720, 1280, 3):
            raise ValueError('Results OCR requires 1280x720 BGR capture')
        if mode not in ('ex', 'money'):
            raise ValueError('Results score_mode must be ex or money')
        crops, keys = [], []
        for i, present in enumerate(presence):
            if not present:
                continue
            boxes = (NAME_BOXES[i], (EX_BOXES if mode == 'ex' else MONEY_BOXES)[i])
            for field, (x, y, w, h) in zip(('name', 'score'), boxes):
                if field == 'name' and not self.parse_names:
                    continue
                crops.append(prepare_ddr_crop(frame[y:y+h, x:x+w]))
                keys.append((i, field))
        values = [dict(name=None, score=None), dict(name=None, score=None)]
        for (i, field), result in zip(keys, self.ocr.recognize_many(crops)):
            if result.confidence < self.confidence:
                continue
            text = result.text.strip()
            if field == 'name':
                value = text if text and len(text) <= 32 and all(c.isprintable() for c in text) else None
            else:
                value = parse_number(text, mode)
            values[i][field] = value
        return values


@dataclass
class Evidence:
    value: object = None
    start: float = 0
    last: float = -float('inf')
    count: int = 0

    def observe(self, value, timestamp, min_frames=5, span=1., max_gap=.75):
        if timestamp <= self.last:
            return False
        if value is None or value != self.value or timestamp - self.last > max_gap:
            self.value, self.start, self.count = value, timestamp, 0
        self.last = timestamp
        self.count += value is not None
        return value is not None and self.count >= min_frames and timestamp - self.start >= span - 1e-6


def outcome(players, mode):
    if mode != 'ex' or not all(p['present'] and p['score'] is not None for p in players):
        return dict(kind='unavailable', winner=None, margin=None)
    a, b = (p['score'] for p in players)
    return dict(kind='tie' if a == b else 'winner', winner=None if a == b else (0 if a > b else 1), margin=abs(a-b))
