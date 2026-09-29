"""Fresh-process name model initialization and working-set measurement."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import time

for _key in ('OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'OMP_NUM_THREADS'):
    os.environ[_key] = '1'

import cv2

from ddrcv.state.player_names import PlayerNameReader, validate_config, NAME_BOXES
from .benchmark import memory_bytes
from .catalog import read_json, dump_json
from .corpus import read_image, crop
from .execution import run_with_qos
from .names import PerPlayerNameReader


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode', choices=('batch1','batch2','per_player1','per_player2'), required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args(); cv2.setNumThreads(1)
    root = Path('experiments/jacket_lookup/artifacts/corpus')
    frames = [read_image(root/r['image']) for r in read_json(root/'manifest.json')['samples'] if r['kind']=='clean']
    crops = [{i:crop(frame,box) for i,box in enumerate(NAME_BOXES)} for frame in frames]
    del frames
    initial = memory_bytes()
    start = time.perf_counter()
    cfg = validate_config(dict(ocr=dict(allow_download=False, num_threads=int(a.mode[-1]))))
    reader = PerPlayerNameReader(cfg, high_qos=True) if a.mode.startswith('per_player') else PlayerNameReader(cfg)
    try:
        with ThreadPoolExecutor(1) as worker:
            worker.submit(run_with_qos, True, reader.warmup).result()
            init_ms = (time.perf_counter()-start)*1000
            loaded = memory_bytes()
            for chips in crops: worker.submit(run_with_qos, True, reader.read, chips).result()
            warm = memory_bytes()
            dump_json(a.out, dict(mode=a.mode, initial_rss=initial, loaded_rss=loaded,
                warm_rss=warm, init_ms=init_ms, warm_added_bytes=warm-initial,
                model_count=2 if a.mode.startswith('per_player') else 1,
                note='Fresh process; HighQoS requested; initialization loads model but excludes first inference; warm RSS after eleven clean name pairs.'))
    finally:
        if isinstance(reader, PerPlayerNameReader): reader.close()


if __name__ == '__main__': main()
