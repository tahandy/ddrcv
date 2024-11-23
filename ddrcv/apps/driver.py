import os
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

# from ddrcv.diagnostics.diagnostics_logger import DiagnosticsLogger
# from ddrcv.diagnostics.diagnostics_wrapper import DiagnosticsWrapper
from ddrcv.injest.rtsp_frame_fetcher import RTSPFrameFetcher
from ddrcv.jacket_database.database.database import DatabaseLookup
from ddrcv.score.score_extractor import ScoreExtractor
from ddrcv.state.states import StateRotation
from ddrcv.publish.websocket_publisher import WebSocketPublisher


def create_frame_fetcher(ingest_config, logger):
    keys = list(ingest_config.keys())

    if len(keys) > 1:
        msg = f'[create_frame_fetcher] Too many ingest type specifiers {keys}. Valid options are one of ["rtsp"].'
        logger.error(msg)
        raise ValueError(msg)

    if 'rtsp' in keys:
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
    db = DatabaseLookup.from_prebuilt(config['jacket_database']['prebuilt_database'],
                                      encoder_cache=config['jacket_database']['cache_dir'])
    publisher = create_publisher(config['publish'], logger=logger)
    publisher.start()

    screenshot = Screenshot(config['results']['screenshot_directory'],
                            timestamp_fmt=config['results']['timestamp_format'])

    reader = get_ocr_singleton()  # this needs to run only once to load the model into memory
    results_parser = ResultsParser(reader, db)
    splash_parser = SplashParser(reader, db, do_name=False)

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
                state_tag, state_data = state_determination.match(frame[..., ::-1])

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

                    ret = splash_parser.parse(frame_rgb, publish_info['players'])
                    publish_info['song'] = {
                        'song': str(ret['song']),
                        'confidence': ret['song_confidence'],
                        'p1_info': ret['p1'],
                        'p2_info': ret['p2']
                    }

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
                if state_tag == 'results':
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
                            score_results = results_parser.parse(frame_rgb)
                            pprint(score_results)
                            push_song_results(score_results, screenshot_path=screenshot_file)
                            print('screenshot_file: ', screenshot_file)
                            results_substep = ResultsSubstep.DONE

                if state_tag != 'results':
                    results_substep = ResultsSubstep.READY

                # print(publish_info)
                publisher.send_message(publish_info)

                # Display the frame (optional)
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
        cv2.destroyAllWindows()


if __name__ == "__main__":
    # 1. Set up frame source
    # 2. Set up score publisher
    # 3. Set up state determination
    # 4. Set up score extractor
    config = {
        "ingest": {
            "rtsp": {
                "rtsp_url": r"rtsp://localhost:8554/mystream",
                "queue_size": 1,
                "reconnect_delay": 5,
                "hw_accel": False
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
                'results',
                'song_playing',
                'song_select',
                'song_splash'
            ]
        },
        "jacket_database": {
            "prebuilt_database": r'C:\code\ddr_ex_parser\ddrcv\jacket_database\output\db_effnetb0.pkl',
            "cache_dir": r'C:\code\ddr_ex_parser\ddrcv\jacket_database\cache'
        },
        "results": {
            "screenshot_directory": r'C:\code\ddr_ex_parser\screenshots',
            "timestamp_format": "%Y%m%d_%H%M",
            "processing_delay": 5,
            "only_duo": False,
            "discord": True
        },
        "driver_debug": {
            "render_frame": True
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
