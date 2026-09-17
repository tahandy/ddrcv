import argparse
import os
from pathlib import Path

from ddrcv.discord.song_results_embed import push_song_results_screenshot

os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'

from ddrcv.apps.recognition_engine import RecognitionEngine
from ddrcv.ingest.file_source import FileSource


import logging
import time

import cv2

from ddrcv.misc.screenshot import Screenshot
from ddrcv.ingest.rtsp_frame_fetcher import RTSPFrameFetcher
from ddrcv.ingest.simple_frame_fetcher import SimpleFrameFetcher
from ddrcv.score.score_extractor import ScoreExtractor
from ddrcv.state.tbd5_states import StateRotation
from ddrcv.publish.websocket_publisher import WebSocketPublisher



def create_frame_fetcher(ingest_config, logger):
    keys = list(ingest_config.keys())

    if len(keys) != 1:
        msg = f'[create_frame_fetcher] Expected exactly one type specifier; got {keys}. Valid options are one of ["simple", "rtsp", "video", "image"].'
        logger.error(msg)
        raise ValueError(msg)

    if keys[0] in ('video', 'image'):
        return FileSource(kind=keys[0], **ingest_config[keys[0]])
    if 'simple' in keys:
        logger.info('[create_frame_fetcher] Creating SimpleFrameFetcher')
        return SimpleFrameFetcher.from_config(dict(ingest_config['simple']), logger=logger)
    elif 'rtsp' in keys:
        logger.info('[create_frame_fetcher] Creating RTSPFrameFetcher')
        return RTSPFrameFetcher.from_config(dict(ingest_config['rtsp']), logger=logger)

    msg = f'[create_frame_fetcher] Failed to find implemented frame fetcher for ingest mode {keys[0]}. Valid options are one of ["simple", "rtsp", "video", "image"].'
    logger.error(msg)
    raise ValueError(msg)


def create_publisher(pub_config, logger):
    keys = list(pub_config.keys())
    if len(keys) != 1:
        msg = f'[create_publisher] Expected exactly one type specifier; got {keys}. Valid options are one of ["websocket"].'
        logger.error(msg)
        raise ValueError(msg)

    if 'websocket' in keys:
        logger.info('[create_publisher] Creating WebSocketPublisher')
        return WebSocketPublisher.from_config(pub_config['websocket'], logger=logger)

    msg = f'[create_publisher] Failed to find implemented publisher for ingest mode {keys[0]}. Valid options are one of ["websocket"].'
    logger.error(msg)
    raise ValueError(msg)


def create_runtime(config, logger, data_dir=None, desktop=False):
    from ddrcv.apps.tournament_runtime import TournamentRuntime
    matcher = StateRotation(**config['state'])
    extractor = ScoreExtractor(config['score_extractor']['glyph_dir'])
    engine = RecognitionEngine(config, matcher=matcher, extractor=extractor)
    fetcher = create_frame_fetcher(config['ingest'], logger)
    try:
        publisher = create_publisher(config['publish'], logger=logger)
        return TournamentRuntime(config, engine, fetcher, publisher, logger,
                                 data_dir=data_dir, clock=time, desktop=desktop,
                                 screenshot_factory=Screenshot,
                                 discord_callback=push_song_results_screenshot)
    except BaseException:
        fetcher.stop()
        raise


def main(config, logger):
    create_runtime(config, logger).run()


from ddrcv.apps.driver_config import default_config, merge_config, read_config, validate_config


def cli():
    parser = argparse.ArgumentParser(description='TBD5 DDR Driver')
    sources = parser.add_mutually_exclusive_group()
    sources.add_argument('--video', type=str, help='Replay a local video at normal speed')
    sources.add_argument('--image', type=str, help='Inspect a still image without temporal confirmation')
    parser.add_argument('--resize-to-720p', action='store_true', help='Resize full 16:9 file footage to 720p')
    sources.add_argument('--choose-camera', action='store_true',
                        help='Choose the camera to use from a list of available cameras')
    parser.add_argument('--debug', action='store_true',
                        help='Turn on debug options')
    parser.add_argument('--config', type=Path, help='JSON overrides for driver settings')
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

    config = default_config()

    if args.config:
        merge_config(config, read_config(args.config))
    if args.video or args.image:
        kind = 'video' if args.video else 'image'
        config['ingest'] = {kind: {'path': args.video or args.image, 'resize_to_720p': args.resize_to_720p}}
    if args.debug:
        config['driver_debug']['render_frame'] = True
    if args.choose_camera:
        config['ingest'] = {'simple': {**config['ingest'].get('simple', {}), 'uri': camera_uri,
                                       'width': 1280, 'height': 720}}

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )

    logger = logging.getLogger('Driver')

    main(validate_config(config), logger)


if __name__ == "__main__":
    cli()
