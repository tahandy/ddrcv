from pathlib import Path

import cv2

from ddrcv.state.state_matcher import StateMatcher


def _resolve_pkl_dir(pkl_dir):
    return Path(__file__).parent / 'sdvx' if pkl_dir is None else Path(pkl_dir)


def _circular_shift(lst, index):
    """Circularly shifts a list to put the element at the given index first."""
    return lst[index:] + lst[:index]


class StateBase:
    def __init__(self, tag, pkl_dir=None):
        self.tag = tag
        self.pkl_dir = _resolve_pkl_dir(pkl_dir)


class SimpleState(StateBase):
    def __init__(self, tag, pkl_file, pkl_dir=None):
        super().__init__(tag, pkl_dir)
        self.matcher = StateMatcher.load(pkl_dir / pkl_file)

    def match(self, rgb_image):
        is_match = self.matcher.match(rgb_image)
        return is_match, None


class Entry(SimpleState):
    def __init__(self, pkl_dir=None):
        super().__init__('entry', 'entry.pkl', pkl_dir=pkl_dir)


# class Gameplay(SimpleState):
#     def __init__(self, pkl_dir=None):
#         super().__init__('gameplay', 'gameplay.pkl', pkl_dir=pkl_dir)


class Gameplay(StateBase):
    def __init__(self, pkl_dir=None):
        super().__init__('gameplay', pkl_dir=pkl_dir)
        self.matchers = [StateMatcher.load(self.pkl_dir / 'gameplay.pkl'),
                         StateMatcher.load(self.pkl_dir / 'gameplay_finishing.pkl'),
                         StateMatcher.load(self.pkl_dir / 'gameplay_finishing_2.pkl'),
                         StateMatcher.load(self.pkl_dir / 'gameplay_finishing_3.pkl')]

    def match(self, rgb_image):
        for idx, matcher in enumerate(self.matchers):
            if matcher.match(rgb_image):
                if idx > 0:
                    self.matchers = _circular_shift(self.matchers, idx)
                return True, None
        return False, None


class SongResult(SimpleState):
    def __init__(self, pkl_dir=None):
        super().__init__('song_result', 'song_result.pkl', pkl_dir=pkl_dir)


class TotalResult(SimpleState):
    def __init__(self, pkl_dir=None):
        super().__init__('total_result', 'total_result.pkl', pkl_dir=pkl_dir)


class SongSelect(StateBase):
    def __init__(self, pkl_dir=None):
        super().__init__('song_select', pkl_dir=pkl_dir)
        self.matchers = [StateMatcher.load(self.pkl_dir / 'song_select_1.pkl'),
                         StateMatcher.load(self.pkl_dir / 'song_select_2.pkl')]

    def match(self, rgb_image):
        for idx, matcher in enumerate(self.matchers):
            if matcher.match(rgb_image):
                if idx > 0:
                    self.matchers = _circular_shift(self.matchers, idx)
                return True, None
        return False, None



def state_factory(tag, **config):
    if not hasattr(state_factory, "mapping"):
        state_factory.mapping = {
            'entry': Entry,
            'song_result': SongResult,
            'total_result': TotalResult,
            'song_select': SongSelect,
            'gameplay': Gameplay
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
                'entry',
                'song_result',
                'total_result',
                'song_select',
                'gameplay'
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

    image = Image.open('../../state_images/sdvx/gameplay_2.png')
    image = np.array(image)

    # state = SongSplash(_resolve_pkl_dir(None))
    state = StateRotation()

    print(state.match(image))


