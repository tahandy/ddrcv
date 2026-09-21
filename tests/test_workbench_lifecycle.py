"""Workbench panel ownership and real score-feed port release regressions."""
import importlib.util
import socket
import time
import unittest
from unittest.mock import Mock, patch

from ddrcv.workbench.lifecycle import PanelLifetime


class PanelLifetimeTests(unittest.TestCase):
    def setUp(self):
        self.shutdown = Mock()
        self.timers = []

        def timer_factory(delay, callback):
            timer = Mock(callback=callback)
            self.timers.append(timer)
            return timer

        self.timer_patch = patch('ddrcv.workbench.lifecycle.threading.Timer', side_effect=timer_factory)
        self.timer_patch.start()
        self.addCleanup(self.timer_patch.stop)
        self.lifetime = PanelLifetime(self.shutdown)
        self.addCleanup(self.lifetime.close)

    def test_headless_session_waits_for_first_panel(self):
        self.assertEqual(self.timers, [])
        self.shutdown.assert_not_called()

    def test_only_last_panel_disconnect_shuts_down(self):
        self.assertTrue(self.lifetime.connect())
        self.assertTrue(self.lifetime.connect())
        self.lifetime.disconnect()
        self.assertEqual(self.timers, [])
        self.lifetime.disconnect()
        self.shutdown.assert_not_called()
        self.timers[-1].callback()
        self.shutdown.assert_called_once()
        self.assertFalse(self.lifetime.connect())

    def test_refresh_cancels_shutdown_including_timer_already_waking(self):
        self.lifetime.connect()
        self.lifetime.disconnect()
        old_timer = self.timers[-1]
        self.lifetime.connect()
        old_timer.cancel.assert_called_once()
        old_timer.callback()
        self.shutdown.assert_not_called()
        self.lifetime.disconnect()
        old_timer.callback()  # A cancelled callback cannot shorten the new grace period.
        self.shutdown.assert_not_called()
        self.timers[-1].callback()
        self.shutdown.assert_called_once()

    def test_explicit_exit_cancels_pending_shutdown(self):
        self.lifetime.connect()
        self.lifetime.disconnect()
        self.lifetime.close()
        self.timers[-1].callback()
        self.shutdown.assert_not_called()


@unittest.skipUnless(importlib.util.find_spec('websockets'), 'Requires websockets')
class PublisherShutdownTests(unittest.TestCase):
    def free_port(self):
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            return reservation.getsockname()[1]

    def assert_not_listening(self, port):
        with socket.socket() as probe:
            probe.settimeout(.2)
            self.assertNotEqual(probe.connect_ex(('127.0.0.1', port)), 0)

    def test_long_publish_delay_does_not_delay_port_release_or_restart(self):
        from ddrcv.publish.websocket_publisher import WebSocketPublisher
        publisher = WebSocketPublisher('127.0.0.1', self.free_port(), delay=30)
        self.addCleanup(publisher.stop)
        for _ in range(2):
            publisher.start()
            worker = publisher._thread
            started = time.monotonic()
            publisher.stop()
            self.assertLess(time.monotonic() - started, 2)
            self.assertFalse(worker.is_alive())
            self.assertFalse(publisher.status['running'])
            self.assert_not_listening(publisher.port)

    def test_connected_client_is_closed_and_same_port_can_be_reused(self):
        from websockets.exceptions import ConnectionClosed
        from websockets.sync.client import connect
        from ddrcv.publish.websocket_publisher import WebSocketPublisher
        port = self.free_port()
        publisher = WebSocketPublisher('127.0.0.1', port)
        self.addCleanup(publisher.stop)
        publisher.send_message({'state': 'song_select'})
        publisher.start()
        with connect(f'ws://127.0.0.1:{port}', close_timeout=.5) as client:
            self.assertIn('song_select', client.recv(timeout=2))
            publisher.stop()
            with self.assertRaises(ConnectionClosed):
                client.recv(timeout=2)
            self.assert_not_listening(port)
        replacement = WebSocketPublisher('127.0.0.1', port)
        try:
            replacement.start()
            self.assertTrue(replacement.status['running'])
        finally:
            replacement.stop()

    def test_pending_shutdown_keeps_worker_handle(self):
        from ddrcv.publish.websocket_publisher import WebSocketPublisher
        publisher = WebSocketPublisher('127.0.0.1', self.free_port())
        worker = publisher._thread = Mock()
        worker.is_alive.return_value = True
        with self.assertRaisesRegex(RuntimeError, 'shutdown is still pending'):
            publisher.stop()
        self.assertIs(publisher._thread, worker)


if __name__ == '__main__':
    unittest.main()
