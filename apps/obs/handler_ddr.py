"""DDR scene policy, configurable through the OBS JSON settings."""

try:
    from .scene_policy import ScenePolicy
except ImportError:  # Also used by `python -m run` from apps/obs.
    from scene_policy import ScenePolicy


def build_handler(config):
    return ScenePolicy(config.get('DDR_SCENE_MAP'), config.get('SCENE_RETRY_SECONDS', 0.5))


handle_state_change = ScenePolicy()
