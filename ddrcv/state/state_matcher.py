import pickle
from pathlib import Path

from ddrcv.state.hash_matcher import HashMatcher


class StateMatcher:
    def __init__(self, name, roi, rgb_glyph, threshold_distance=5):
        """
        :param name:
        :param roi: (x, y, w, h)
        :param rgb_glyph:
        :param threshold_distance:
        """
        self.name = name
        self.roi = roi
        self.glyph = rgb_glyph.copy()
        self.threshold_distance = threshold_distance
        self.hash_matcher = HashMatcher(self.glyph, threshold_distance=self.threshold_distance)

    def match(self, rgb_image):
        return self.hash_matcher.match_roi(rgb_image, self.roi)

    def serialize(self):
        output = {
            'name': self.name,
            'roi': self.roi,
            'glyph': self.glyph.copy(),
            'threshold': self.threshold_distance
        }
        return output

    def save(self, pkl_dir=None):
        if pkl_dir is None:
            pkl_dir = Path(__file__).parent / 'data'
        else:
            pkl_dir = Path(pkl_dir)

        pkl_file = pkl_dir / f'{self.name}.pkl'

        with open(pkl_file, 'wb') as fid:
            pickle.dump(self.serialize(), fid)

    @classmethod
    def load(cls, pkl_file):
        with open(pkl_file, 'rb') as fid:
            params = pickle.load(fid)
        # return StateMatcher(params['name'], params['roi'], params['glyph'], threshold_distance=params['threshold'])
        return StateMatcher(params['name'], params['roi'], params['glyph'], threshold_distance=10)
