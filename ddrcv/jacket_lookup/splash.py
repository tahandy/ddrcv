"""The bundled splash dHash templates without legacy plotting dependencies."""
from pathlib import Path
import pickle

import numpy as np
from PIL import Image


def dhash(rgb):
    gray = Image.fromarray(rgb).convert('L').resize((9, 8), Image.Resampling.LANCZOS)
    pixels = np.asarray(gray)
    return pixels[:, 1:] > pixels[:, :-1]


class SplashDetector:
    """Equivalent to SongSplash/StateMatcher's 64-bit dHash distance < 10.

    Only trusted package templates are deserialized, never downloaded indexes.
    """
    def __init__(self):
        import ddrcv
        directory = Path(ddrcv.__file__).parent / 'state/world'
        self.templates = []
        for player in (1, 2):
            with (directory/f'song_splash_p{player}.pkl').open('rb') as stream:
                data = pickle.load(stream)
            self.templates.append((data['roi'], dhash(data['glyph'])))

    def match(self, rgb):
        presence = {}
        for player, (roi, template) in enumerate(self.templates, 1):
            x, y, w, h = roi
            presence[f'p{player}_present'] = bool(np.count_nonzero(dhash(rgb[y:y+h,x:x+w]) != template) < 10)
        matched = any(presence.values())
        return matched, presence if matched else None
