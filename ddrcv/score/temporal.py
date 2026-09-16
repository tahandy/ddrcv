"""Score plausibility checks with an optional elapsed-time EX score limit."""

import math
import time


class ScoreTracker:
    """Set max_per_frame=None to accept arbitrarily large upward score jumps."""

    def __init__(self, game_fps=60, max_per_frame=12):
        if game_fps <= 0 or (max_per_frame is not None and max_per_frame <= 0):
            raise ValueError("game_fps must be positive; max_per_frame must be positive or None")
        self.game_fps = game_fps
        self.max_per_frame = max_per_frame
        self.reset()

    def reset(self):
        self.last_reason = 'no_read'
        self.value = None
        self.accepted_at = None

    def update(self, value, now=None):
        now = time.monotonic() if now is None else now
        if value is None:
            self.last_reason = 'absent'
            return None  # Absent player; do not compare None with a number.
        if value < 0:
            self.last_reason = 'no_digits'
            return self.value if self.value is not None else -1
        if self.value is not None:
            if value < self.value:
                self.last_reason = 'decrease'
                return self.value
            if self.max_per_frame is not None:
                elapsed = max(0, now - self.accepted_at)
                frames = max(1, math.ceil(elapsed * self.game_fps))
                if value - self.value > frames * self.max_per_frame:
                    self.last_reason = 'jump_limit'
                    return self.value
        self.last_reason = 'accepted'
        self.value, self.accepted_at = value, now
        return value
