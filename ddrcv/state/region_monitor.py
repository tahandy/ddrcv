"""Optional per-frame observations of actual matcher calls, without re-running them."""
from contextlib import contextmanager
from contextvars import ContextVar

_regions = ContextVar('monitored_regions', default=None)
_state = ContextVar('monitored_state', default=None)


@contextmanager
def collect_regions():
    regions = []
    token = _regions.set(regions)
    try:
        yield regions
    finally:
        _regions.reset(token)


@contextmanager
def monitor_state(state):
    token = _state.set(state)
    try:
        yield
    finally:
        _state.reset(token)


def record_match(name, roi, matched):
    regions = _regions.get()
    if regions is not None:
        regions.append(dict(kind='state', state=_state.get(), name=name,
                            roi=[int(value) for value in roi], matched=bool(matched)))
