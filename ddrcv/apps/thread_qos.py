"""Keep latency-sensitive desktop recognition out of Windows power throttling."""
from contextlib import contextmanager
import ctypes
import sys


class _PowerThrottlingState(ctypes.Structure):
    _fields_ = [('Version', ctypes.c_uint32), ('ControlMask', ctypes.c_uint32),
                ('StateMask', ctypes.c_uint32)]


def _request_high_qos():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentThread.restype = ctypes.c_void_p
    kernel.GetCurrentThread.argtypes = []
    signature = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(_PowerThrottlingState), ctypes.c_uint32]
    kernel.GetThreadInformation.argtypes = signature
    kernel.GetThreadInformation.restype = ctypes.c_int
    kernel.SetThreadInformation.argtypes = signature
    kernel.SetThreadInformation.restype = ctypes.c_int
    thread = kernel.GetCurrentThread()
    previous = _PowerThrottlingState(1, 0, 0)
    # ThreadPowerThrottling = 3; EXECUTION_SPEED = 1. Query first so we can
    # restore the caller's exact policy, including system-managed defaults.
    if not kernel.GetThreadInformation(thread, 3, ctypes.byref(previous), ctypes.sizeof(previous)):
        raise ctypes.WinError(ctypes.get_last_error())
    requested = _PowerThrottlingState(1, previous.ControlMask | 1, previous.StateMask & ~1)
    if not kernel.SetThreadInformation(thread, 3, ctypes.byref(requested), ctypes.sizeof(requested)):
        raise ctypes.WinError(ctypes.get_last_error())

    def restore():
        if not kernel.SetThreadInformation(thread, 3, ctypes.byref(previous), ctypes.sizeof(previous)):
            raise ctypes.WinError(ctypes.get_last_error())
    return restore


@contextmanager
def desktop_recognition_qos(enabled, logger):
    """Request HighQoS on this worker only, preserving affinity and priority.

    The tray backend doesn't own the visible panel window. Windows may therefore
    assign it a different power policy from a console/foreground-parent launch.
    This hint is best effort on Windows; other platforms and CLI runs are no-ops.
    """
    restore = None
    if enabled and sys.platform == 'win32':
        try:
            restore = _request_high_qos()
            logger.info('Desktop recognition thread: Windows HighQoS enabled')
        except (AttributeError, OSError) as error:
            logger.debug('Windows recognition HighQoS unavailable: %s', error)
    try:
        yield
    finally:
        if restore is not None:
            try:
                restore()
            except (AttributeError, OSError) as error:
                logger.debug('Could not restore recognition thread power policy: %s', error)
