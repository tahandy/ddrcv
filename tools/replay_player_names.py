"""Replay a real login or splash through the driver, with an OCR-off baseline.

Only reads local video and publishes to an in-memory recorder. No OBS/Discord.
"""
import argparse
from copy import deepcopy
import json
import logging
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2
from ddrcv.apps.driver_config import validate_config
from ddrcv.apps.recognition_engine import RecognitionEngine
from ddrcv.apps.tournament_runtime import TournamentRuntime
from ddrcv.ingest.file_source import FileSource
from ddrcv.ocr.check import check_ocr
from ddrcv.state.tbd5_states import StateRotation


def first_screen(path, screen='song_splash'):
    source = FileSource(path)
    matcher = StateRotation()
    try:
        # Coarse discovery only; acceptance playback uses every video frame.
        for index in range(0, source.count, max(1, round(source.fps / 2))):
            source.seek(index / source.fps)
            packet = source.read()
            if packet is None:
                break
            state, _ = matcher.match(cv2.cvtColor(packet.image, cv2.COLOR_BGR2RGB))
            if state == screen:
                return max(0, packet.timestamp - 1)
        raise RuntimeError(f'No supported {screen} detected in this recording')
    finally:
        source.stop()


class WindowSource(FileSource):
    def __init__(self, path, start, end):
        super().__init__(path)
        self.seek(start)
        self.end_seconds = end

    def read(self):
        if self.index / self.fps >= self.end_seconds:
            self.ended = True
            return None
        return super().read()


class Recorder:
    def __init__(self):
        self.messages = []

    def start(self):
        pass

    def stop(self):
        pass

    def send_message(self, message):
        self.messages.append((time.perf_counter(), deepcopy(message)))


def run(path, start, end, enabled, screen='song_splash'):
    config = validate_config(dict(ingest=dict(video=dict(path=path)), results=dict(enabled=False),
                                 player_names=dict(enabled=enabled, ocr=dict(allow_download=False))))
    publisher = Recorder()
    engine = RecognitionEngine(config)
    runtime = TournamentRuntime(config, engine, WindowSource(path, start, end), publisher,
                                logging.getLogger('splash-replay'))
    durations, frames = [], []
    process = engine.process
    def timed(*args, **kwargs):
        began = time.perf_counter()
        result = process(*args, **kwargs)
        durations.append((time.perf_counter() - began) * 1000)
        frames.append((time.perf_counter(), result['timestamp'], result['raw_state']))
        return result
    engine.process = timed
    # Measure the complete synchronous name submit path separately from OCR.
    from ddrcv.state.player_names import PlayerNameService
    from unittest.mock import patch
    service = PlayerNameService(config['player_names'])
    submit = service.submit
    submits = []
    def timed_submit(*args, **kwargs):
        began = time.perf_counter()
        submit(*args, **kwargs)
        submits.append((time.perf_counter() - began) * 1000)
    service.submit = timed_submit
    began = time.perf_counter()
    with patch('ddrcv.apps.tournament_runtime.PlayerNameService', return_value=service):
        runtime.run()
    confirmed = [(stamp, msg) for stamp, msg in publisher.messages if any(msg['player_names'].values())]
    # Players confirm independently. Report the earliest snapshot with greatest
    # coverage, rather than mistaking the first partial update for the final names.
    best = max(confirmed, key=lambda item: sum(value is not None for value in item[1]['player_names'].values())) if confirmed else None
    first = next((stamp for stamp, _, raw in frames if raw == screen), None)
    def metrics(values):
        values = sorted(values)
        return dict(median_ms=round(statistics.median(values), 3),
                    p95_ms=round(values[min(len(values)-1, int(len(values)*.95))], 3),
                    max_ms=round(max(values), 3)) if values else None
    return dict(enabled=enabled, frames=len(frames), elapsed_seconds=round(time.perf_counter()-began, 3),
                names=best[1]['player_names'] if best else dict(p1=None, p2=None),
                first_name_seconds=None if not confirmed or first is None else round(confirmed[0][0]-first, 3),
                confirmation_seconds=None if best is None or first is None else round(best[0]-first, 3),
                recognition=metrics(durations), submit=metrics(submits), service=service.status(),
                distinct_names=[dict(p1=a, p2=b) for a,b in sorted({
                    (msg['player_names']['p1'] or '', msg['player_names']['p2'] or '')
                    for _,msg in confirmed})])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', required=True)
    parser.add_argument('--start', type=float)
    parser.add_argument('--seconds', type=float, default=9)
    parser.add_argument('--screen', choices=('login', 'song_splash'), default='song_splash')
    parser.add_argument('--expect', nargs=2, metavar=('P1', 'P2'), help='Expected names; use - for absent/unconfirmed')
    parser.add_argument('--output', default='.workbench/player-names-validation.json')
    args = parser.parse_args()
    ready = check_ocr()
    if not ready['ok']:
        raise SystemExit(ready['detail'])
    start = first_screen(args.video, args.screen) if args.start is None else args.start
    baseline = run(args.video, start, start + args.seconds, False, args.screen)
    enabled = run(args.video, start, start + args.seconds, True, args.screen)
    report = dict(video=str(Path(args.video).resolve()), screen=args.screen, window=[start, start+args.seconds],
                  baseline=baseline, enabled=enabled)
    output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    if enabled['service']['error']:
        raise SystemExit('Name worker failed')
    if args.expect:
        expected = dict(zip(('p1', 'p2'), [None if n == '-' else n for n in args.expect]))
        if (enabled['names'] != expected or any(value and value != expected[key]
                for names in enabled['distinct_names'] for key, value in names.items())):
            raise SystemExit('Names did not match the expected recording labels')


if __name__ == '__main__':
    main()
