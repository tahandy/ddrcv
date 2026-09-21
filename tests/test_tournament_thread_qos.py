"""Thread-local Windows power policy, without requiring Windows in unit tests."""
import ctypes
from unittest import TestCase
from unittest.mock import Mock, patch

from ddrcv.apps import thread_qos


class ThreadQoSTests(TestCase):
    def test_windows_desktop_requests_and_restores_even_on_error(self):
        restore = Mock()
        with patch.object(thread_qos.sys, 'platform', 'win32'), patch.object(
                thread_qos, '_request_high_qos', return_value=restore) as request:
            with self.assertRaisesRegex(ValueError, 'recognition failed'):
                with thread_qos.desktop_recognition_qos(True, Mock()):
                    request.assert_called_once_with()
                    restore.assert_not_called()
                    raise ValueError('recognition failed')
            restore.assert_called_once_with()

    def test_cli_and_other_platforms_do_not_touch_policy(self):
        for enabled, platform in ((False, 'win32'), (True, 'linux'), (True, 'darwin')):
            with self.subTest(enabled=enabled, platform=platform), patch.object(
                    thread_qos.sys, 'platform', platform), patch.object(thread_qos, '_request_high_qos') as request:
                with thread_qos.desktop_recognition_qos(enabled, Mock()):
                    pass
                request.assert_not_called()

    def test_unsupported_api_and_restore_failure_do_not_break_capture(self):
        with patch.object(thread_qos.sys, 'platform', 'win32'):
            for error in (AttributeError('unavailable'), OSError('denied')):
                with patch.object(thread_qos, '_request_high_qos', side_effect=error):
                    with thread_qos.desktop_recognition_qos(True, Mock()):
                        pass
            with patch.object(thread_qos, '_request_high_qos', return_value=Mock(side_effect=OSError('denied'))):
                with self.assertRaisesRegex(ValueError, 'original failure'):
                    with thread_qos.desktop_recognition_qos(True, Mock()):
                        raise ValueError('original failure')

    def test_native_request_changes_only_execution_speed_and_restores_exact_policy(self):
        kernel = Mock()
        kernel.GetCurrentThread.return_value = 123
        def query(handle, kind, ptr, size):
            self.assertEqual((handle, kind, size), (123, 3, 12))
            state = ctypes.cast(ptr, ctypes.POINTER(thread_qos._PowerThrottlingState)).contents
            state.Version, state.ControlMask, state.StateMask = 1, 3, 3
            return 1
        writes = []
        def apply(handle, kind, ptr, size):
            self.assertEqual((handle, kind, size), (123, 3, 12))
            state = ctypes.cast(ptr, ctypes.POINTER(thread_qos._PowerThrottlingState)).contents
            writes.append((state.Version, state.ControlMask, state.StateMask))
            return 1
        kernel.GetThreadInformation.side_effect = query
        kernel.SetThreadInformation.side_effect = apply
        with patch.object(ctypes, 'WinDLL', return_value=kernel, create=True):
            restore = thread_qos._request_high_qos()
            self.assertEqual(writes, [(1, 3, 2)])
            restore()
            self.assertEqual(writes, [(1, 3, 2), (1, 3, 3)])
