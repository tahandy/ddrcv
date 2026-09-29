"""Fresh-process template splash benchmark at the existing 5 Hz name cadence."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import time

for _key in ('OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','OMP_NUM_THREADS'):
    os.environ[_key] = '1'

import cv2

from ddrcv.state.player_names import PlayerNameReader, validate_config, NAME_BOXES
from .benchmark import metrics, memory_bytes
from .catalog import read_json, dump_json
from .corpus import read_image, crop
from .difficulty import DifficultyTemplates
from .execution import run_with_qos
from .lookup import Lookup
from .names import PerPlayerNameReader
from .threaded import ThreadedSplashLookup


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--name-method', choices=('batch','per-player'), required=True)
    p.add_argument('--qos', choices=('system','high'), required=True)
    p.add_argument('--name-threads', type=int, choices=(1,2), default=2)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args(); cv2.setNumThreads(1)
    high = a.qos == 'high'
    root = Path('experiments/jacket_lookup/artifacts')
    frames = [read_image(root/'corpus'/r['image']) for r in read_json(root/'corpus/manifest.json')['samples'] if r['kind']=='clean']
    crops = [{i:crop(frame, box) for i,box in enumerate(NAME_BOXES)} for frame in frames]
    frozen = read_json(root/'benchmark/frozen.json'); selected = frozen['selected']['event']
    initial = memory_bytes(); start = time.perf_counter()
    lookup = Lookup(root/'index'/selected, thresholds=frozen['configurations'][selected]['thresholds'])
    cfg = validate_config(dict(ocr=dict(allow_download=False, num_threads=a.name_threads)))
    names = PerPlayerNameReader(cfg, high_qos=high) if a.name_method == 'per-player' else PlayerNameReader(cfg)
    processor = ThreadedSplashLookup(lookup, difficulty_reader=DifficultyTemplates(root/'difficulty-template'), high_qos=high)
    try:
        with ThreadPoolExecutor(1, thread_name_prefix='paced-names') as pool:
            pool.submit(run_with_qos, high, names.warmup).result()
            init_ms = (time.perf_counter()-start)*1000
            def analyze(i):
                start = time.perf_counter()
                def read_names():
                    values = run_with_qos(high, names.read, crops[i])
                    return values, (time.perf_counter()-start)*1000
                future = pool.submit(read_names)
                chart = processor.analyze(frames[i])
                chart_ms = (time.perf_counter()-start)*1000
                values, names_ms = future.result()
                return dict(all_ready_ms=(time.perf_counter()-start)*1000,
                            chart_ready_ms=chart_ms,names_ready_ms=names_ms,names=values)
            for i in range(len(frames)): analyze(i)
            warm = memory_bytes()
            # Include the idle part of each 200 ms period in the CPU accounting,
            # so native thread-pool spinning cannot hide outside measured calls.
            time.sleep(.25)
            cpu = time.process_time(); wall = time.perf_counter(); samples = []
            for repeat in range(2):
                for i in range(len(frames)):
                    tick = time.perf_counter(); samples.append(analyze(i))
                    time.sleep(max(0, .2-(time.perf_counter()-tick)))
            cpu_ms = (time.process_time()-cpu)*1000
            wall_ms = (time.perf_counter()-wall)*1000
            dump_json(a.out,dict(name_method=a.name_method,worker_qos=a.qos,name_threads=a.name_threads,
                initial_rss=initial,warm_rss=warm,init_ms=init_ms,
                cpu_ms_per_sample=cpu_ms/len(samples),mean_cpu_cores=cpu_ms/wall_ms,
                summary={k:metrics([s[k] for s in samples]) for k in ('all_ready_ms','chart_ready_ms','names_ready_ms')},samples=samples))
    finally:
        processor.close()
        if isinstance(names, PerPlayerNameReader): names.close()


if __name__ == '__main__': main()
