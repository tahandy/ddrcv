"""One-frame experiment combining independent name and chart recognition."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import time

for _key in ('OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'OMP_NUM_THREADS'):
    os.environ[_key] = '1'

import cv2

from .catalog import read_json, dump_json
from .configuration import WORKING_CONFIG
from .corpus import read_image, crop
from .difficulty import DifficultyTemplates
from .execution import run_with_qos
from .lookup import Lookup
from .names import PerPlayerNameReader
from .threaded import ThreadedSplashLookup


def build_parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image', type=Path, required=True)
    p.add_argument('--root', type=Path, default=Path('experiments/jacket_lookup/artifacts'))
    p.add_argument('--catalog', choices=('event', 'full'), default=WORKING_CONFIG.catalog)
    p.add_argument('--style', choices=('single', 'double'), default=WORKING_CONFIG.style)
    p.add_argument('--difficulty-method', choices=('template', 'ocr'), default=WORKING_CONFIG.difficulty_method)
    p.add_argument('--name-method', choices=('batch', 'per-player', 'none'), default=WORKING_CONFIG.name_method)
    p.add_argument('--name-threads', type=int, choices=(1, 2), default=WORKING_CONFIG.name_threads)
    p.add_argument('--worker-qos', choices=('system', 'high'), default='high' if WORKING_CONFIG.high_qos else 'system')
    p.add_argument('--output', type=Path)
    return p


def main(argv=None):
    p = build_parser()
    a = p.parse_args(argv); cv2.setNumThreads(1)
    initialized = time.perf_counter()
    frozen = read_json(a.root/'benchmark/frozen.json')
    selected = frozen['selected'][a.catalog]
    lookup = Lookup(a.root/'index'/selected, thresholds=frozen['configurations'][selected]['thresholds'])
    frame = read_image(a.image)
    if frame.shape != (720, 1280, 3): p.error('Expected a 1280x720 BGR splash')
    high = a.worker_qos == 'high'
    names = None
    difficulty = DifficultyTemplates(a.root/'difficulty-template') if a.difficulty_method == 'template' else None
    ocr = None
    if difficulty is None:
        from ddrcv.ocr.rapid import RapidOCRRecognizer
        ocr = RapidOCRRecognizer(allow_download=False, num_threads=1); ocr.warmup()
    try:
        if a.name_method != 'none':
            from ddrcv.state.player_names import PlayerNameReader, validate_config, NAME_BOXES
            cfg = validate_config(dict(ocr=dict(allow_download=False, num_threads=a.name_threads)))
            names = (PerPlayerNameReader(cfg, high_qos=high) if a.name_method == 'per-player'
                     else PlayerNameReader(cfg))
            names.warmup()
        init_ms = (time.perf_counter()-initialized)*1000
        # No names are read for an absent player or a non-splash frame.
        matched, presence = lookup._get_splash_detector().match(frame[..., ::-1])
        crops = {i:crop(frame, box) for i, box in enumerate(NAME_BOXES)
                 if presence[f'p{i+1}_present']} if names is not None and matched else {}
        def read():
            values = run_with_qos(high, names.read, crops) if crops else {}
            return values, (time.perf_counter()-start)*1000
        with ThreadedSplashLookup(lookup, recognizer=ocr, difficulty_reader=difficulty, high_qos=high) as charts:
            with ThreadPoolExecutor(1, thread_name_prefix='demo-names') as pool:
                start = time.perf_counter()
                future = pool.submit(read)
                chart = charts.analyze(frame, style=a.style)
                chart_ready = (time.perf_counter()-start)*1000
                values, names_ready = future.result()
                result = dict(chart=chart, names={f'p{k+1}':v for k,v in values.items()},
                    name_method=a.name_method, worker_qos=a.worker_qos,
                    timings_ms=dict(initialization=init_ms, chart_ready=chart_ready,
                        names_ready=names_ready, all_ready=(time.perf_counter()-start)*1000),
                    note='Single-frame observations; first inference may be cold; name confirmation remains separate.')
        if a.output: dump_json(a.output, result)
        import json
        print(json.dumps(result, indent=2))
    finally:
        if isinstance(names, PerPlayerNameReader): names.close()


if __name__ == '__main__': main()
