"""Temporal confirmation of screen labels, independent of image matching."""

from collections import deque
import time


class StateDebouncer:
    def __init__(self, confirm_seconds=0.2, min_frames=3,
                 unknown_seconds=1.0, max_frame_gap=0.5, min_fraction=0.75):
        if (confirm_seconds <= 0 or unknown_seconds <= 0 or min_frames < 1
                or max_frame_gap <= 0 or not 0.5 < min_fraction <= 1):
            raise ValueError("Invalid state debounce settings")
        self.confirm_seconds = confirm_seconds
        self.min_frames = min_frames
        self.unknown_seconds = unknown_seconds
        self.max_frame_gap = max_frame_gap
        self.min_fraction = min_fraction
        self.state = 'unknown'
        self.data = None
        self._history = deque()
        self._started = None
        self._last_frame = None

    def update(self, tag, data=None, now=None):
        now = time.monotonic() if now is None else now
        # A capture interruption is not evidence that a candidate persisted.
        gap = self._last_frame is not None and now - self._last_frame > self.max_frame_gap
        if self._started is None or gap:
            self._history.clear()
            self._started = now
        self._last_frame = now
        self._history.append((now, tag))
        cutoff = now - max(self.confirm_seconds, self.unknown_seconds)
        while self._history and self._history[0][0] < cutoff:
            self._history.popleft()
        if tag == self.state:
            self.data = data
            return self.state, self.data
        delay = self.unknown_seconds if tag == 'unknown' else self.confirm_seconds
        votes = [label for timestamp, label in self._history if timestamp >= now - delay]
        support = votes.count(tag)
        # Require a full observation window, multiple matching frames, and a
        # majority. Brief unknowns or wrong labels need not restart the window.
        if (now - self._started >= delay and support >= self.min_frames
                and support / len(votes) >= self.min_fraction):
            self.state, self.data = tag, data
        return self.state, self.data
