"""Reconcile OBS with the current confirmed DDR state."""

import logging
import time


DEFAULT_SCENE_MAP = {
    'song_select': 'Commentator',
    'song_splash': 'Gameplay',
    'song_playing': 'Gameplay',
    'song_result': 'Gameplay',
    'total_result': 'Commentator',
    'login': 'Commentator',
}


class ScenePolicy:
    def __init__(self, scene_map=None, retry_seconds=0.5, clock=time.monotonic):
        self.scene_map = dict(DEFAULT_SCENE_MAP if scene_map is None else scene_map)
        if 'unknown' in self.scene_map and self.scene_map['unknown'] is not None:
            raise ValueError("unknown must hold the current scene; omit it or use null")
        if any(value is not None and (not isinstance(value, str) or not value.strip())
               for value in self.scene_map.values()):
            raise ValueError("Scene names must be nonempty strings or null")
        if retry_seconds <= 0:
            raise ValueError("Scene retry interval must be positive")
        self.last_error = None
        self.retry_seconds = retry_seconds
        self.clock = clock
        self._next_check = 0
        self.logger = logging.getLogger('apps.obs.scene_policy')

    def __call__(self, prev, curr, client, override=False):
        # The previous screen is deliberately irrelevant. Repeated messages,
        # startup mid-song, and returning from manual control all converge.
        if override:
            self._next_check = 0
            return
        target = self.scene_map.get(curr.get('state', 'unknown'))
        now = self.clock()
        if target is None or now < self._next_check:
            return
        self._next_check = now + self.retry_seconds
        try:
            actual = client.get_current_program_scene().current_program_scene_name
            if actual != target:
                client.set_current_program_scene(target)
                self.logger.info("OBS scene changed to %s", target)
            self.last_error = None
        except Exception as error:
            detail = f"Cannot switch to {target}: {error}"
            if detail != self.last_error:
                self.logger.exception("OBS scene reconciliation failed; will retry")
            self.last_error = detail
