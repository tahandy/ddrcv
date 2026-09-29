"""Compatibility import of the packaged implementation."""
import sys
from ddrcv.jacket_lookup import configuration as _core
sys.modules[__name__] = _core
