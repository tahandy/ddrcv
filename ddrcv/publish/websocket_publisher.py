"""Latest-snapshot publisher with bounded startup/shutdown and connection status."""
import asyncio
from copy import deepcopy
import json
import logging
import threading

import websockets


class WebSocketPublisher:
    def __init__(self, host='0.0.0.0', port=9000, delay=0.1, only_send_new=True, logger=None):
        self.host, self.port = host, int(port)
        self.delay, self.only_send_new = delay, only_send_new
        self.logger = logger or logging.getLogger(__name__)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread = None
        self._content, self._version = None, 0
        self._clients, self._running, self._error = 0, False, None

    @classmethod
    def from_config(cls, config, logger=None):
        return cls(**config, logger=logger)

    @property
    def status(self):
        with self._lock:
            return dict(running=self._running, clients=self._clients, host=self.host,
                        port=self.port, error=self._error)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(target=self._run, name='score-publisher', daemon=True)
        self._thread.start()
        if not self._ready.wait(5):
            self.stop()
            raise RuntimeError('Score publisher did not start within five seconds')
        if self._error:
            raise RuntimeError(self._error)

    def send_message(self, json_contents):
        with self._lock:
            self._content = deepcopy(json_contents)
            self._version += 1

    def stop(self):
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=3)
        self._thread = None

    def _run(self):
        try:
            asyncio.run(self._serve())
        except Exception as error:
            self._error = f'Cannot start score feed on {self.host}:{self.port}: {error}. Stop the other driver/simulator or select a free port.'
        finally:
            self._running = False
            self._clients = 0
            self._ready.set()

    async def _serve(self):
        clients = set()

        async def handler(websocket):
            clients.add(websocket)
            self._clients = len(clients)
            try:
                with self._lock:
                    snapshot = self._content
                if snapshot is not None:
                    await websocket.send(json.dumps(snapshot))
                await websocket.wait_closed()
            finally:
                clients.discard(websocket)
                self._clients = len(clients)

        async with websockets.serve(handler, self.host, self.port, close_timeout=.5):
            self._running = True
            self._ready.set()
            last_version = -1
            while not self._stop.is_set():
                with self._lock:
                    snapshot, version = self._content, self._version
                if snapshot is not None and (not self.only_send_new or version != last_version):
                    message = json.dumps(snapshot)
                    if clients:
                        await asyncio.gather(*(client.send(message) for client in tuple(clients)), return_exceptions=True)
                    last_version = version
                await asyncio.sleep(self.delay)
