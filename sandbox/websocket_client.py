import asyncio
import sys

import websockets
import argparse
import logging

logging.basicConfig(level=logging.INFO)

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
    loop = asyncio.get_event_loop()
    try:
        sys.exit(loop.run_until_complete(listen(args.uri)))
    except KeyboardInterrupt:
        # Optionally show a message if the shutdown may take a while
        print("Attempting graceful shutdown, press Ctrl+C again to exit…", flush=True)

        # Do not show `asyncio.CancelledError` exceptions during shutdown
        # (a lot of these may be generated, skip this if you prefer to see them)
        def shutdown_exception_handler(loop, context):
            if "exception" not in context \
            or not isinstance(context["exception"], asyncio.CancelledError):
                loop.default_exception_handler(context)
        loop.set_exception_handler(shutdown_exception_handler)

        # Handle shutdown gracefully by waiting for all tasks to be cancelled
        tasks = asyncio.gather(*asyncio.Task.all_tasks(loop=loop), loop=loop, return_exceptions=True)
        tasks.add_done_callback(lambda t: loop.stop())
        tasks.cancel()

        # Keep the event loop running until it is either destroyed or all
        # tasks have really terminated
        while not tasks.done() and not loop.is_closed():
            loop.run_forever()
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()