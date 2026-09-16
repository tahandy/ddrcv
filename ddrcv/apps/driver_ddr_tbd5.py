import argparse
import os
import json
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


def main(config, logger):
    # Construct everything before starting background work, so configuration or
    # missing-template errors cannot leave a camera thread running.
    state_determination = StateRotation(**config['state'])
    score_extractor = ScoreExtractor(config['score_extractor']['glyph_dir'])
    engine = RecognitionEngine(config, matcher=state_determination, extractor=score_extractor)
    session = engine.session
    fetcher = create_frame_fetcher(config['ingest'], logger)
    publisher = create_publisher(config['publish'], logger=logger)
    result_config = config.get('results', {})
    screenshot = None
    if result_config.get('enabled', False) and result_config.get('discord', False) and not result_config.get('webhook'):
        raise ValueError('Set results.webhook explicitly before enabling Discord publication')
    if result_config.get('enabled', False):
        screenshot = Screenshot(result_config['screenshot_directory'],
                                timestamp_fmt=result_config['timestamp_format'])
    previous_state = 'unknown'
    try:
        fetcher.start()
        publisher.start()
        while True:
            frame = fetcher.get_frame()
            if frame is None:
                if isinstance(fetcher, FileSource) and fetcher.ended:
                    break
                time.sleep(0.01)
                continue
            now = fetcher.source_time if isinstance(fetcher, FileSource) else time.monotonic()
            still = isinstance(fetcher, FileSource) and fetcher.kind == 'image'
            result = engine.process(frame, now, diagnostics=still, stateless=still)
            frame_rgb = frame[..., ::-1].copy()
            info = result['published']
            if still:
                logger.info('Image diagnostics: %s', result)
            if info['state'] != previous_state:
                logger.info('Confirmed state: %s -> %s', previous_state, info['state'])
                previous_state = info['state']
            # Publish before optional screenshot/Discord work. The settling
            # delay is a deadline, not a sleep that stalls screen detection.
            publisher.send_message(info)
            if (screenshot is not None
                    and session.screenshot_due(now, result_config['processing_delay'])
                    and (not result_config.get('only_duo', False) or all(info['players']))):
                screenshot_file = screenshot.save(frame_rgb)
                session.results_saved = True
                logger.info('Results screenshot: %s', screenshot_file)
                if result_config.get('discord', False):
                    try:
                        push_song_results_screenshot(title='Results', screenshot_path=screenshot_file,
                                                     webhook_url=result_config.get('webhook'))
                    except Exception:
                        logger.exception('Discord publication failed; screenshot remains saved')
            if config['driver_debug']['render_frame']:
                cv2.imshow('DDR Capture', frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
    except KeyboardInterrupt:
        pass
    finally:
        fetcher.stop()
        publisher.stop()
        if config['driver_debug']['render_frame']:
            cv2.destroyAllWindows()


def merge_config(defaults, overrides):
    for key, value in overrides.items():
        if key != 'ingest' and isinstance(value, dict) and isinstance(defaults.get(key), dict):
            merge_config(defaults[key], value)
        else:
            defaults[key] = value
    return defaults


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

    config = {
        "ingest": {
            "simple": {
                "uri": camera_uri,
                "queue_size": 1,
                "reconnect_delay": 5,
                "width": 1280,
                "height": 720,
                "query_delay": 0.01
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
        "debounce": {"confirm_seconds": 0.2, "min_frames": 3, "unknown_seconds": 1.0, "max_frame_gap": 0.5, "min_fraction": 0.75},
        "score_filter": {"game_fps": 60, "max_per_frame": 12},
        "score_extractor": {
            "glyph_dir": None
        },
        "state": {
            "pkl_dir": None,
            "states": [
                'song_result',
                'song_playing',
                'song_select',
                'song_splash',
                'total_result',
                'login'
            ]
        },
        "jacket_database": {
            "prebuilt_database": r'/home/tim/persistent/database/db_effnetb0-20241126.pkl',
            "cache_dir": r'/home/tim/persistent/database/cache'
        },
        "results": {
            "enabled": False,
            "screenshot_directory": r'D:\TBD5\screenshots',
            "timestamp_format": "%Y%m%d_%H%M",
            "processing_delay": 5,
            "only_duo": False,
            "discord": False,
            'webhook': None
        },
        "driver_debug": {
            "render_frame": args.debug
        }
    }

    if args.config:
        with args.config.open(encoding='utf-8') as stream:
            merge_config(config, json.load(stream))
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

    main(config, logger)


if __name__ == "__main__":
    cli()
