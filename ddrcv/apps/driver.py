import os


os.environ['KMP_DUPLICATE_LIB_OK']='TRUE'

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

    publish_info = dict()
    publish_info['state'] = 'unknown'
    publish_info['players'] = (True, True)
    publish_info['song'] = None
    publish_info['score'] = None

    bb = [108, 424, 535-108, 855-424]

    try:
        while True:
            frame = fetcher.get_frame()
            if frame is not None:
                frame_rgb = frame[..., ::-1].copy()
                state_tag, state_data = state_determination.match(frame[..., ::-1])

                publish_info['state'] = state_tag

                if state_tag == 'song_select':
                    publish_info['players'] = None
                    publish_info['song'] = None
                    publish_info['score'] = None

                if state_tag == 'song_splash':
                    score_extractor.set_presence(state_data['p1_present'], state_data['p2_present'])
                    publish_info['players'] = (state_data['p1_present'], state_data['p2_present'])

                    dist, song_info = db.lookup(frame_rgb[bb[0]:bb[0]+bb[2], bb[1]:bb[1]+bb[3], ::-1].copy(), count=1)
                    publish_info['song'] = {
                        'similarity': float(dist[0]),
                        'info': str(song_info[0].song_data['Song'])
                    }

                if state_tag == 'song_playing':
                    score_ret = score_extractor.extract(frame_rgb, debug=False)
                    publish_info['score'] = score_ret['data']

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
                'stage_rank',
                'song_playing',
                'song_select',
                'song_splash'
            ]
        },
        "jacket_database": {
            "prebuilt_database": r'C:\code\ddr_ex_parser\ddrcv\jacket_database\output\db_mobilenetv3_small.pkl',
            "cache_dir": r'C:\code\ddr_ex_parser\ddrcv\jacket_database\cache'
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
