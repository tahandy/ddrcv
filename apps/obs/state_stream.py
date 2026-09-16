"""Reconnectable state feed; connector injection keeps it testable without OBS."""

import asyncio
import json
import logging


async def consume_states(connect, uri, stop_event, on_message, on_connection,
                         reconnect_delay=1.0):
    logger = logging.getLogger(__name__)
    while not stop_event.is_set():
        try:
            async with connect(uri, open_timeout=3, close_timeout=1) as websocket:
                on_connection(True)
                while not stop_event.is_set():
                    try:
                        raw = await asyncio.wait_for(websocket.recv(), timeout=0.25)
                    except asyncio.TimeoutError:
                        continue
                    if stop_event.is_set():
                        break
                    try:
                        message = json.loads(raw)
                    except (ValueError, TypeError):
                        logger.warning("Ignoring invalid state JSON")
                        continue
                    if not isinstance(message, dict) or not isinstance(message.get('state'), str):
                        logger.warning("Ignoring message without a state label")
                        continue
                    on_message(message)
        except Exception as error:
            logger.warning("State feed disconnected: %s; retrying", error)
        finally:
            on_connection(False)
        # Check the stop request while backing off, so desk controls respond.
        deadline = asyncio.get_running_loop().time() + reconnect_delay
        while not stop_event.is_set() and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.05)
