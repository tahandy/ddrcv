"""Default worker scheduling hints for CPU splash recognition."""
from contextlib import nullcontext
import logging

from .configuration import WORKING_CONFIG


def worker_qos(enabled=WORKING_CONFIG.high_qos):
    if not enabled:
        return nullcontext()
    from ddrcv.apps.thread_qos import desktop_recognition_qos
    return desktop_recognition_qos(True, logging.getLogger(__name__))


def run_with_qos(enabled, function, *args, **kwargs):
    with worker_qos(enabled):
        return function(*args, **kwargs)
