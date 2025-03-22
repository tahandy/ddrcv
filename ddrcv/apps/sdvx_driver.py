import argparse
import os

from ddrcv.ingest.simple_frame_fetcher import SimpleFrameFetcher

os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'

from enum import Enum, auto

from ddrcv.misc.screenshot import Screenshot

import logging
import time

import cv2

from ddrcv.ingest.rtsp_frame_fetcher import RTSPFrameFetcher
from ddrcv.state.sdvx_states import StateRotation
from ddrcv.publish.websocket_publisher import WebSocketPublisher


def create_frame_fetcher(ingest_config, logger):
    keys = list(ingest_config.keys())

    if len(keys) > 1:
        msg = f'[create_frame_fetcher] Too many ingest type specifiers {keys}. Valid options are one of ["rtsp"].'
        logger.error(msg)
        raise ValueError(msg)

    if 'simple' in keys:
        logger.info('[create_frame_fetcher] Creating RTSPFrameFetcher')
        return SimpleFrameFetcher.from_config(ingest_config['simple'], logger=logger)
    elif 'rtsp' in keys:
        logger.info('[create_frame_fetcher] Creating RTSPFrameFetcher')
        return RTSPFrameFetcher.from_config(ingest_config['rtsp'], logger=logger)

    msg = f'[create_frame_fetcher] Failed to find implemented frame fetcher for ingest mode {keys[0]}. Valid options are one of ["rtsp"].'
    logger.error(msg)
    raise ValueError(msg)


def create_publisher(pub_config, logger):
    keys = list(pub_config.keys())
    if len(keys) > 1:
        msg = f'[create_publisher] Too many ingest type specifiers {keys}. Valid options are one of ["websocket"].'
        logger.error(msg)
        raise ValueError(msg)

    if 'websocket' in keys:
        logger.info('[create_publisher] Creating WebSocketPublisher')
        return WebSocketPublisher.from_config(pub_config['websocket'], logger=logger)

    msg = f'[create_publisher] Failed to find implemented publisher for ingest mode {keys[0]}. Valid options are one of ["websocket"].'
    logger.error(msg)
    raise ValueError(msg)


class ResultsSubstep(Enum):
    READY = auto()
    PROCESS = auto()
    DONE = auto()


def main(config, logger):
    # Initialize and start the frame fetcher
    # fetcher = RTSPFrameFetcher(rtsp_url, hw_accel=False)
    fetcher = create_frame_fetcher(config['ingest'], logger)
    fetcher.start()

    state_determination = StateRotation(**config['state'])

    publisher = create_publisher(config['publish'], logger=logger)
    publisher.start()

    publish_info = dict()
    publish_info['state'] = 'unknown'

    try:
        while True:
            frame = fetcher.get_frame()
            if frame is not None:
                frame_rgb = frame[..., ::-1].copy()
                state_tag, state_data = state_determination.match(frame_rgb)
                publish_info['state'] = state_tag
                publisher.send_message(publish_info)
            else:
                # Wait until a frame is available
                time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        # Clean up
        fetcher.stop()
        publisher.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='TBD5 DDR Driver')
    parser.add_argument('--choose-camera', action='store_true',
                        help='Choose the camera to use from a list of available cameras')
    parser.add_argument('--debug', action='store_true',
                        help='Turn on debug options')
    args = parser.parse_args()

    camera_uri = 0
    if args.choose_camera:
        from cv2_enumerate_cameras import enumerate_cameras
        valid_indices = []
        print('Available cameras:')
        for camera_info in enumerate_cameras(cv2.CAP_DSHOW):
            print(f'{camera_info.index}: {camera_info.name}')
            valid_indices.append(camera_info.index)

        while True:
            user_input = input("Enter camera index: ")
            value = None
            try:
                value = int(user_input)
            except ValueError:
                print("Invalid input. Please enter a valid integer.")
            else:
                if value in valid_indices:
                    camera_uri = value
                    break
                print(f"Invalid input. Please enter a valid camera index from the list {valid_indices}.")

    config = {
        "ingest": {
            "simple": {
                "uri": camera_uri,
                "queue_size": 1,
                "reconnect_delay": 5,
                "width": 1920,
                "height": 1080,
                "query_delay": 0.03333
            }
        },
        "publish": {
            "websocket": {
                "host": 'localhost',
                "port": 9000,
                "delay": 0.1,
                "only_send_new": True
            }
        },
        "score_extractor": {
            "glyph_dir": None
        },
        "state": {
            "pkl_dir": None,
            "states": [
                'login',
                'song_select',
                'song_playing',
                'song_result',
                'total_result'
            ]
        },
        "results": {
            "screenshot_directory": r'/home/tim/persistent/screenshots',
            "timestamp_format": "%Y%m%d_%H%M",
            "processing_delay": 5,
            "only_duo": False,
            "discord": False
        },
        "driver_debug": {
            "render_frame": False
        }
    }

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )

    logger = logging.getLogger('Driver')

    main(config, logger)
