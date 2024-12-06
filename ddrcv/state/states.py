from pathlib import Path

import cv2

from ddrcv.state.state_matcher import StateMatcher


def _resolve_pkl_dir(pkl_dir):
    return Path(__file__).parent / 'data' if pkl_dir is None else Path(pkl_dir)


def _circular_shift(lst, index):
    """Circularly shifts a list to put the element at the given index first."""
    return lst[index:] + lst[:index]


class StateBase:
    def __init__(self, tag, pkl_dir=None):
        self.tag = tag
        self.pkl_dir = _resolve_pkl_dir(pkl_dir)


class Caution(StateBase):
    def __init__(self, pkl_dir=None):
        super().__init__('caution', pkl_dir=pkl_dir)
        self.matcher = StateMatcher.load(pkl_dir / 'caution.pkl')

    def match(self, rgb_image):
        is_match = self.matcher.match(rgb_image)
        return is_match, None


class StageRank(StateBase):
    """
    DEPRECATED. Old version prior to November 2024
    """
    def __init__(self, pkl_dir=None):
        super().__init__('stage_rank', pkl_dir=pkl_dir)
        self.matcher = StateMatcher.load(self.pkl_dir / 'stage_rank.pkl')

    def match(self, rgb_image):
        is_match = self.matcher.match(rgb_image)
        return is_match, None


class SongPlaying(StateBase):
    def __init__(self, pkl_dir=None):
        super().__init__('song_playing', pkl_dir=pkl_dir)
        self.matcher = StateMatcher.load(pkl_dir / 'gameplay.pkl')

        # Lane identification
        # Each player lane is (luckily) buffered by two vertical gutters, a few pixels wide, that are black-ish. This is
        # independent of the customizable background brightness. Knowing if the lanes are present is extremely helpful
        # when extracting the score. This is because if the player FCs the song, there is a huge high-brightness
        # burst effect that propagates down to the score zone and corrupts the numeral extraction. This effect
        # is coincident with the fading of the lanes, and the gutters are gone a few frames before the numerals are
        # corrupted. Thus, the presence of the player lanes gives us a confident prediction on the quality of the
        # input to the score extractor (i.e. only extract the score if the gutter is present).
        self.p1_col = 68
        self.p2_col = 788
        self.row_range = (115, 165)  # Use more than 1 pixel to help avoid any compression artifacts

        # This should be set pretty high to give as many frames as possible to the score extractor, because the
        # digit change isn't instantaneous -- while the UI doesn't blur the digits, it does interpolate which digit
        # should be shown every frame. If we instantly say that gutters have disappeared (e.g. 5/100), it seems like
        # we miss a frame or two and do not have the final score. However, if it's set too high, there's a chance that
        # we trigger too late and get hit by that stupid rocket. However, I think triggering too late is less likely
        # than triggering too early, as long as we're close to realtime FPS.
        # The darklights of the BG clouds are V=~35, and the other BG elements are V > 90.
        self.black_max = 80 / 100

    def match(self, rgb_image):
        is_match = self.matcher.match(rgb_image)
        data = None
        if is_match:
            gutters_present = self._is_gutter_present(rgb_image, self.p1_col) or \
                              self._is_gutter_present(rgb_image, self.p2_col)
            data = {'lanes_present': gutters_present}

        return is_match, data

    def _is_gutter_present(self, rgb_image, col):
        hsv = cv2.cvtColor(rgb_image[self.row_range[0]:self.row_range[1], col:col+1, ...], cv2.COLOR_RGB2HSV)
        v = hsv[..., -1] / 255  # OpenCV Val is in [0, 255]
        v_max = v.max()
        return v_max < self.black_max


class SongSelect(StateBase):
    def __init__(self, pkl_dir=None):
        super().__init__('song_select', pkl_dir=pkl_dir)
        self.matcher1 = StateMatcher.load(pkl_dir / 'song_select.pkl')
        self.matcher2 = StateMatcher.load(pkl_dir / 'song_options.pkl')

    def match(self, rgb_image):
        if self.matcher1.match(rgb_image):
            return True, None
        if self.matcher2.match(rgb_image):
            return True, None
        return False, None


class SongSplash(StateBase):
    def __init__(self, pkl_dir=None):
        super().__init__('song_splash', pkl_dir=pkl_dir)
        self.matcher_p1 = StateMatcher.load(pkl_dir / 'song_splash_p1.pkl')
        self.matcher_p2 = StateMatcher.load(pkl_dir / 'song_splash_p2.pkl')

    def match(self, rgb_image):
        p1 = self.matcher_p1.match(rgb_image)
        p2 = self.matcher_p2.match(rgb_image)
        is_match = p1 or p2
        if is_match:
            return True, {'p1_present': p1, 'p2_present': p2}
        return False, None


class Results(StateBase):
    def __init__(self, pkl_dir=None):
        super().__init__('results', pkl_dir=pkl_dir)
        self.matcher = StateMatcher.load(self.pkl_dir / 'results.pkl')

    def match(self, rgb_image):
        is_match = self.matcher.match(rgb_image)
        return is_match, None


class TotalResult(StateBase):
    def __init__(self, pkl_dir=None):
        super().__init__('total_result', pkl_dir=pkl_dir)
        self.matcher = StateMatcher.load(self.pkl_dir / 'total_result.pkl')

    def match(self, rgb_image):
        is_match = self.matcher.match(rgb_image)
        return is_match, None


def state_factory(tag, **config):
    if not hasattr(state_factory, "mapping"):
        state_factory.mapping = {
            'caution': Caution,
            'stage_rank': StageRank,
            'song_playing': SongPlaying,
            'song_select': SongSelect,
            'song_splash': SongSplash,
            'results': Results,
            'total_result': TotalResult
        }

    constructor = state_factory.mapping.get(tag, None)
    if constructor is None:
        raise NotImplementedError(f'[state_factory] Failed to find state with tag {tag}')

    return constructor(**config)


class StateRotation:
    def __init__(self, pkl_dir=None, states=None):
        # Put these in order of typical appearance in a playthrough.
        # This will let us circshift the buffer, so that the most recently found state
        # will be the first checked on the next pass -- this lets us skip any potentially expensive steps
        # unless necessary.
        pkl_dir = _resolve_pkl_dir(pkl_dir)
        if states is None:
            states = [
                # 'stage_rank',
                'results',
                'song_playing',
                'song_select',
                'song_splash',
                'total_result'
            ]

        self.states = list()
        for tag in states:
            self.states.append(state_factory(tag, pkl_dir=pkl_dir))

    def match(self, rgb_image):
        """
        :param rgb_image:
        :return: (tag, data). Will return ('unknown', None) if the state can not be determined.
        """
        best_idx = 0
        is_match = False
        data = None
        state_tag = 'unknown'

        for ii, matcher in enumerate(self.states):
            is_match, data = matcher.match(rgb_image)
            if is_match:
                best_idx = ii
                state_tag = matcher.tag
                break

        if not is_match:
            data = None

        if best_idx > 0:
            self.states = _circular_shift(self.states, best_idx)

        return state_tag, data


if __name__ == "__main__":
    from PIL import Image
    import numpy as np

    image = Image.open('../../state_images/song_splash_updated_p2.png')
    image = Image.open('../../state_images/total_result_updated.png')
    image = np.array(image)

    # state = SongSplash(_resolve_pkl_dir(None))
    state = StateRotation()

    print(state.match(image))


