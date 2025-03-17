import os

from ddrcv.ingest.simple_frame_fetcher import SimpleFrameFetcher

os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'

from enum import Enum, auto
from pprint import pprint

from ddrcv.discord.song_results_embed import push_song_results
from ddrcv.misc.screenshot import Screenshot
from ddrcv.ocr import get_ocr_singleton
from ddrcv.state.results_parser import ResultsParser
from ddrcv.state.splash_parser import SplashParser


import logging
import time

import cv2

from ddrcv.ingest.rtsp_frame_fetcher import RTSPFrameFetcher
from ddrcv.jacket_database.database.database import DatabaseLookup
from ddrcv.score.score_extractor import ScoreExtractor
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

    screenshot = Screenshot(config['results']['screenshot_directory'],
                            timestamp_fmt=config['results']['timestamp_format'])

    publish_info = dict()
    publish_info['state'] = 'unknown'

    try:
        while True:
            frame = fetcher.get_frame()
            if frame is not None:
                frame_rgb = frame[..., ::-1].copy()
                state_tag, state_data = state_determination.match(frame[..., ::-1])

                publish_info['state'] = state_tag

                # print(publish_info)
                publisher.send_message(publish_info)

                print(publish_info)

                # # Display the frame (optional)
                # cv2.imshow('RTSP Stream', frame)
                # if cv2.waitKey(1) & 0xFF == ord('q'):
                #     break
            else:
                # Wait until a frame is available
                time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        # Clean up
        fetcher.stop()
        publisher.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    # 1. Set up frame source
    # 2. Set up score publisher
    # 3. Set up state determination
    # 4. Set up score extractor
    config = {
        "ingest": {
            "simple": {
                "uri": 1,
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
                'entry',
                'song_select',
                'gameplay',
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
