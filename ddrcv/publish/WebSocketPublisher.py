import asyncio
import json
import time
from multiprocessing import Process, Lock, Manager
import websockets

class Publisher:
    def __init__(self, host='127.0.0.1', port=9000, delay=0.1):
        self.host = host
        self.port = port
        manager = Manager()
        self.latest_message = manager.dict()
        self.latest_message['content'] = None  # Initialize with None
        self.latest_message['version'] = 0     # Version number to track updates
        self.lock = Lock()
        self.process = None
        self.delay = delay  # Publishing delay duration to throttle sends

    def start(self):
        self.process = Process(target=self._run_server, args=(self.latest_message, self.lock))
        self.process.start()

    def send_message(self, json_contents):
        with self.lock:
            self.latest_message['content'] = json_contents
            self.latest_message['version'] += 1  # Increment version to indicate update

    def stop(self):
        if self.process and self.process.is_alive():
            self.process.terminate()
            self.process.join()

    def _run_server(self, latest_message, lock):
        connected_clients = set()
        last_version = -1  # Initialize with an invalid version

        async def handler(websocket, path):
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
                    current_version = latest_message['version']
                    if current_version != last_version and latest_message['content'] is not None:
                        # There is a new message to send
                        message = json.dumps(latest_message['content'])
                        last_version = current_version  # Update last_version
                    else:
                        continue  # No new message, skip sending
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

    # Create a list of messages to send
    data = [
        {"type": "message", "content": "Hello, World!"},
        {"type": "message", "content": "This is WebSockets with Locks"},
        {"type": "message", "content": "Latest Message Only"}
    ]

    # Start the Publisher
    pub = Publisher(delay=0.01)
    pub.start()

    try:
        while True:
            datum = random.choice(data)
            print(f'Sending message: {datum}')
            pub.send_message(datum)
            # time.sleep(random.randint(3, 9))
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        # Stop the Publisher once done
        pub.stop()
