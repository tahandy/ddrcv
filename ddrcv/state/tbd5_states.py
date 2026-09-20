"""Compatibility imports for the former tournament-named DDR World recognizer."""
from ddrcv.state.world_states import (
    Login, Results, SimpleState, SongPlaying, SongSelect, SongSplash,
    StateBase, StateRotation, TotalResult, _circular_shift, _resolve_pkl_dir,
    state_factory,
)
