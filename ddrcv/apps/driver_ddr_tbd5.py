import argparse
import os
from pathlib import Path

from ddrcv.discord.song_results_embed import push_song_results, push_song_results_screenshot

os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'

from enum import Enum, auto


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
    score_extractor = ScoreExtractor(config['score_extractor']['glyph_dir'])
    # db = DatabaseLookup.from_prebuilt('../jacket_database/output/db_effnetb0.pkl')
    # db = DatabaseLookup.from_prebuilt(config['jacket_database']['prebuilt_database'],
    #                                   encoder_cache=config['jacket_database']['cache_dir'])
    publisher = create_publisher(config['publish'], logger=logger)
    publisher.start()

    screenshot = None
    if 'results' in config and config['results'].get('enabled', False):
        screenshot = Screenshot(config['results']['screenshot_directory'],
                                timestamp_fmt=config['results']['timestamp_format'])
        Path(config['results']['screenshot_directory']).mkdir(parents=True, exist_ok=True)


    # reader = get_ocr_singleton()  # this needs to run only once to load the model into memory
    # results_parser = ResultsParser(reader, db)
    # splash_parser = SplashParser(reader, db, do_name=False)

    publish_info = dict()
    publish_info['state'] = 'unknown'
    publish_info['players'] = (True, True)
    publish_info['song'] = None
    publish_info['score'] = None

    results_substep = ResultsSubstep.READY

    try:
        while True:
            frame = fetcher.get_frame()
            if frame is not None:
                frame_rgb = frame[..., ::-1].copy()
                state_tag, state_data = state_determination.match(frame_rgb)

                publish_info['state'] = state_tag

                # ----------------------------------------------
                # SONG SELECT
                # Use this as a temporal point to reset state
                # ----------------------------------------------
                if state_tag == 'song_select':
                    publish_info['players'] = (True, True)
                    publish_info['song'] = None
                    publish_info['score'] = None

                # ----------------------------------------------
                # SONG SPLASH
                # Determine player presence, difficulty levels, and song
                # ----------------------------------------------
                if state_tag == 'song_splash':
                    score_extractor.set_presence(state_data['p1_present'], state_data['p2_present'])
                    publish_info['players'] = (state_data['p1_present'], state_data['p2_present'])

                    # ret = splash_parser.parse(frame_rgb, publish_info['players'])
                    # publish_info['song'] = {
                    #     'song': str(ret['song']),
                    #     'confidence': ret['song_confidence'],
                    #     'p1_info': ret['p1'],
                    #     'p2_info': ret['p2']
                    # }

                # ----------------------------------------------
                # SONG PLAYING
                # Realtime score extraction
                # ----------------------------------------------
                if state_tag == 'song_playing':
                    if state_data['lanes_present']:
                        score_ret = score_extractor.extract(frame_rgb, debug=False)
                        publish_info['score'] = score_ret['data']
                        # print(publish_info)

                # ----------------------------------------------
                # RESULTS
                # Screenshot, parse, and publish song results
                # ----------------------------------------------
                if screenshot is not None and state_tag == 'song_result':
                    # Need to disable any results processing if we only want duo mode and
                    # only one player is present
                    results_enabled = True
                    if config['results']['only_duo']:
                        if not (publish_info['players'][0] and publish_info['players'][1]):
                            results_enabled = False
                            print('Skipping results')

                    if results_enabled:
                        # There is an zoom wipe and score tally animation that we need to skip past,
                        # so we break the results section into substeps.
                        # Additionally, we only fully process the results screen once, or we risk getting
                        # duplicate images if multiple processing attempts span different minutes/seconds (depending on
                        # provided time format).
                        if results_substep == ResultsSubstep.READY:
                            time.sleep(config['results']['processing_delay'])
                            results_substep = ResultsSubstep.PROCESS
                        elif results_substep == ResultsSubstep.PROCESS:
                            screenshot_file = screenshot.save(frame_rgb)
                            # score_results = results_parser.parse(frame_rgb)
                            # pprint(score_results)
                            if config['results'].get('discord', False):
                                # push_song_results(score_results, screenshot_path=screenshot_file)
                                push_song_results_screenshot(title='Test', screenshot_path=screenshot_file, webhook_url=config['results'].get('webhook', None))
                            print('screenshot_file: ', screenshot_file)
                            results_substep = ResultsSubstep.DONE

                if state_tag != 'song_result':
                    results_substep = ResultsSubstep.READY

                # print(publish_info)
                publisher.send_message(publish_info)

                # Display the frame (optional)
                if config['driver_debug']['render_frame']:
                    cv2.imshow('RTSP Stream', frame)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break
            else:
                # Wait until a frame is available
                time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        # Clean up
        fetcher.stop()
        publisher.stop()
        if config['driver_debug']['render_frame']:
            cv2.destroyAllWindows()


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
            "discord": True,
            'webhook': None
        },
        "driver_debug": {
            "render_frame": args.debug
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
