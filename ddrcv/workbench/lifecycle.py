"""Stop a browser-owned workbench after its last control panel disconnects."""
import threading


class PanelLifetime:
    def __init__(self, shutdown, grace_seconds=3):
        self.shutdown = shutdown
        self.grace_seconds = grace_seconds
        self._lock = threading.Lock()
        self._panels = 0
        self._timer = None
        self._closed = False

    def connect(self):
        with self._lock:
            if self._closed:
                return False
            if self._timer:
                self._timer.cancel()
                self._timer = None
            self._panels += 1
            return True

    def disconnect(self):
        with self._lock:
            self._panels -= 1
            if self._panels == 0 and not self._closed:
                timer = threading.Timer(self.grace_seconds, lambda: self._shutdown_if_empty(timer))
                timer.daemon = True
                self._timer = timer
                timer.start()

    def _shutdown_if_empty(self, timer):
        with self._lock:
            if self._panels or self._closed or self._timer is not timer:
                return
            self._closed = True
        self.shutdown()

    def close(self):
        with self._lock:
            self._closed = True
            if self._timer:
                self._timer.cancel()
