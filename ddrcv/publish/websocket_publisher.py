import asyncio
import json
import logging
import time
from multiprocessing import Process, Lock, Manager
import websockets


class WebSocketPublisher:
    def __init__(self, host='0.0.0.0', port=9000, delay=0.1, only_send_new=True, logger=None):
        if logger is None:
            self.logger = logging.getLogger('WebSocketPublisher')
        else:
            self.logger = logger

        self.host = host
        self.port = port
        self.delay = delay  # Publishing delay duration to throttle sends
        self.only_send_new = only_send_new
        manager = Manager()
        self.latest_message = manager.dict()
        self.latest_message['content'] = None  # Initialize with None
        self.latest_message['version'] = 0     # Version number to track updates
        self.lock = Lock()
        self.process = None

    @classmethod
    def from_config(cls, config, logger=None):
        if logger is None:
            logger = logging.getLogger('WebSocketPublisher')
        return WebSocketPublisher(**config, logger=logger)

    def start(self):
        self.process = Process(target=self._run_server, args=(self.latest_message, self.lock))
        self.process.start()

    def send_message(self, json_contents):
        with self.lock:
            self.latest_message['content'] = json_contents
            if self.only_send_new:
                self.latest_message['version'] += 1  # Increment version to indicate update
                self.latest_message['version'] %= 32000

    def stop(self):
        if self.process is not None and self.process.is_alive():
            self.process.terminate()
            self.process.join()

    def __del__(self):
        if self is not None:
            self.stop()

    def _run_server(self, latest_message, lock):
        connected_clients = set()
        last_version = -1  # Initialize with an invalid version

        #async def handler(websocket, path):
        async def handler(websocket):
            # Register client
            connected_clients.add(websocket)
            print(f"Client connected: {websocket.remote_address}")
            try:
                await websocket.wait_closed()
            finally:
                connected_clients.remove(websocket)
                print(f"Client disconnected: {websocket.remote_address}")

        async def broadcast_latest_message():
            nonlocal last_version
            while True:
                await asyncio.sleep(self.delay)  # Small delay to prevent tight loop
                with lock:
                    if self.only_send_new:
                        current_version = latest_message['version']
                        if current_version != last_version and latest_message['content'] is not None:
                            # There is a new message to send
                            message = json.dumps(latest_message['content'])
                            last_version = current_version  # Update last_version
                        else:
                            continue  # No new message, skip sending
                    else:
                        message = json.dumps(latest_message['content'])

                if connected_clients:
                    coroutines = [client.send(message) for client in connected_clients]
                    await asyncio.gather(*coroutines)
                    print(f"Sent latest message to {len(connected_clients)} client(s): {message}")

        async def main():
            async with websockets.serve(handler, self.host, self.port):
                print(f"WebSocket server running on ws://{self.host}:{self.port}")
                # Run the broadcast_latest_message task
                await broadcast_latest_message()

        # Run the server event loop
        asyncio.run(main())


if __name__ == "__main__":
    import random

    logging.basicConfig(level=logging.DEBUG)

    # Create a list of messages to send
    data = [
        {"type": "message", "content": "Hello, World!"},
        {"type": "message", "content": "This is WebSockets with Locks"},
        {"type": "message", "content": "Latest Message Only"}
    ]

    # Start the WebSocketPublisher
    pub = WebSocketPublisher(host='0.0.0.0', port=9000, delay=0.1)
    pub.start()

    try:
        while True:
            datum = random.choice(data)
            print(f'Sending message: {datum}')
            pub.send_message(datum)
            # time.sleep(random.randint(3, 9))
            # time.sleep(10)
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        # Stop the WebSocketPublisher once done
        pub.stop()
