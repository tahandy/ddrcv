import asyncio
import websockets
import argparse
import logging

logging.basicConfig(level=logging.DEBUG)

async def listen(uri):
    async with websockets.connect(uri) as websocket:
        while True:
            message = await websocket.recv()
            print(f"Received message: {message}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simple WebSocket Client")
    # parser.add_argument("uri", type=str, help="WebSocket server URI (e.g., ws://192.168.1.101:9000)", default="ws://localhost:9000")
    # parser.add_argument("--uri", type=str, help="WebSocket server URI (e.g., ws://192.168.1.101:9000)", default="ws://192.168.1.101:9000")
    parser.add_argument("--uri", type=str, help="WebSocket server URI (e.g., ws://192.168.1.101:9000)", default="ws://localhost:9000")
    args = parser.parse_args()

    # Start the WebSocket listener
    asyncio.get_event_loop().run_until_complete(listen(args.uri))
