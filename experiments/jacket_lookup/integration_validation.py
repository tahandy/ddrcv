"""Packaged-core parity, paced Windows CPU measurements, and whole-video replay."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib
import importlib.util
import os
from pathlib import Path
import sys
import time

for key in ('OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'OMP_NUM_THREADS'):
    os.environ[key] = '1'

import cv2
import numpy as np

from ddrcv.jacket_lookup import assets
from ddrcv.jacket_lookup.catalog import dump_json, read_json
from ddrcv.jacket_lookup.images import read_image, crop
from ddrcv.jacket_lookup.lookup import Lookup, lookup_splash
from ddrcv.jacket_lookup.difficulty import DifficultyTemplates
from ddrcv.jacket_lookup.names import PerPlayerNameReader
from ddrcv.jacket_lookup.service import SplashService
from ddrcv.state.player_names import NAME_BOXES, PlayerNameService
from .benchmark import queries, observe, summarize, metrics, memory_bytes

ROOT = Path('experiments/jacket_lookup/artifacts')
OUT = ROOT / 'integration'
CFG = dict(enabled=True, assets_dir=str(OUT/'assets'))


def wait(predicate, timeout=10):
    until = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= until:
            raise TimeoutError('Recognition did not finish')
        time.sleep(.001)


def parity():
    directory = OUT/'baseline'
    spec = importlib.util.spec_from_file_location('_jacket_before', directory/'__init__.py',
                                                submodule_search_locations=[str(directory)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    old = importlib.import_module('_jacket_before.lookup')
    old_difficulty = importlib.import_module('_jacket_before.difficulty')
    truth = read_json('experiments/jacket_lookup/ground_truth.json')
    result = dict(catalogs={}, differences=[], score_max_error=0.)
    def without_times(value):
        if isinstance(value, dict):
            return {k:without_times(v) for k,v in value.items() if k not in ('timings_ms','elapsed_ms')}
        if isinstance(value, list):
            return [without_times(v) for v in value]
        return value
    for mode in ('event','full'):
        name = mode+'-classical-128'
        thresholds = read_json(ROOT/'benchmark'/f'{name}-thresholds.json')
        before = old.Lookup(ROOT/'index'/name, thresholds=thresholds)
        after = Lookup(ROOT/'index'/name, thresholds=thresholds)
        old_bank = old_difficulty.DifficultyTemplates(ROOT/'difficulty-template')
        bank = DifficultyTemplates(assets.PACKAGE_ASSETS/'templates')
        rows = []
        count = splash_count = 0
        for query in queries(ROOT/'corpus',truth,after.catalog):
            a = before.lookup(query['image'],exclude_song_ids=query['exclude'])
            b = after.lookup(query['image'],exclude_song_ids=query['exclude'])
            count += 1
            result['score_max_error'] = max(result['score_max_error'],
                abs(a['margin']-b['margin']),
                max((abs(x['score']-y['score']) for x,y in zip(a['candidates'],b['candidates'])),default=0))
            if without_times(a) != without_times(b):
                result['differences'].append([mode,query['id'],'jacket'])
            if query['kind'] in ('clean','transition','negative'):
                a = old.lookup_splash(before,query['frame'],difficulty_reader=old_bank)
                b = lookup_splash(after,query['frame'],difficulty_reader=bank)
                splash_count += 1
                if without_times(a) != without_times(b):
                    result['differences'].append([mode,query['id'],'splash'])
            rows.append(observe(after,query))
        result['catalogs'][mode] = dict(jacket_comparisons=count,splash_comparisons=splash_count,
                                      evaluation=summarize([r for r in rows if r['phase']=='evaluation']))
    dump_json(OUT/'parity.json',result)
    print(result,flush=True)
    if result['differences']:
        raise AssertionError('Core behavior changed')


def paced(output):
    frames = [read_image(ROOT/'corpus'/r['image'])
              for r in read_json(ROOT/'corpus/manifest.json')['samples'] if r['kind']=='clean']
    initial = memory_bytes(); began = time.perf_counter()
    lookup = assets.load(CFG)
    processor = assets.processor(CFG, lookup=lookup)
    names = PerPlayerNameReader(dict(ocr=dict(allow_download=False,num_threads=1)))
    names.warmup()
    init_ms = (time.perf_counter()-began)*1000
    samples = []
    try:
        with ThreadPoolExecutor(1) as pool:
            def analyze(frame):
                began = time.perf_counter()
                future = pool.submit(names.read,{i:crop(frame,box) for i,box in enumerate(NAME_BOXES)})
                chart = processor.analyze(frame)
                chart_ms = (time.perf_counter()-began)*1000
                readings = future.result()
                return dict(total_ms=(time.perf_counter()-began)*1000,
                            chart_ms=chart_ms,stages=chart['timings_ms'],names=readings)
            for frame in frames: analyze(frame)
            warm = memory_bytes()
            time.sleep(.25)
            cpu = time.process_time(); start = time.perf_counter()
            for _ in range(3):
                for frame in frames:
                    tick = time.perf_counter()
                    samples.append(analyze(frame))
                    time.sleep(max(0,.2-(time.perf_counter()-tick)))
            cpu_seconds = time.process_time()-cpu; wall_seconds = time.perf_counter()-start
        # Measure the real service submission and temporal publication separately.
        ns = PlayerNameService(dict(enabled=True), reader=names)
        service = SplashService(CFG,names=ns,processor=processor)
        wait(lambda: ns.ready or ns.error)
        enqueue, episodes = [], []
        try:
            for i, frame in enumerate(frames):
                service.reset(str(i))
                start = time.perf_counter(); first_song=first_charts=first_names=None
                for step in range(4):
                    t = time.perf_counter()-start
                    began = time.perf_counter()
                    service.submit(frame,t,'song_splash','song_splash',(True,True),str(i))
                    enqueue.append((time.perf_counter()-began)*1000)
                    deadline = start+(step+1)*.21
                    while time.perf_counter() < deadline:
                        snapshot = service.snapshot()
                        elapsed = (time.perf_counter()-start)*1000
                        if snapshot['song'] and first_song is None: first_song=elapsed
                        if snapshot['song'] and all(snapshot['song']['charts'].values()) and first_charts is None:
                            first_charts=elapsed
                        if all(snapshot['player_names'].values()) and first_names is None: first_names=elapsed
                        time.sleep(.002)
                episodes.append(dict(song_ms=first_song,charts_ms=first_charts,names_ms=first_names,
                                     status=service.status(),names_status=ns.status(),snapshot=service.snapshot()))
        finally:
            service.close()
        result = dict(cpu_only=True,native_threads=1,high_qos=True,
            samples=samples,initial_rss=initial,warm_rss=warm,init_ms=init_ms,
            mean_cpu_cores=cpu_seconds/wall_seconds,
            summary={k:metrics([s[k] for s in samples]) for k in ('total_ms','chart_ms')},
            stages={k:metrics([s['stages'][k] for s in samples]) for k in samples[0]['stages']},
            enqueue_ms=metrics(enqueue),episodes=episodes,
            confirmation_ms={k:metrics([e[k] for e in episodes if e[k] is not None])
                             for k in ('song_ms','charts_ms','names_ms')})
        dump_json(output,result)
        print(dict(output=str(output),summary=result['summary'],enqueue=result['enqueue_ms'],
                   mean_cpu_cores=result['mean_cpu_cores']),flush=True)
    finally:
        processor.close(); names.close()


def replay(videos):
    from ddrcv.apps.recognition_engine import RecognitionEngine
    from ddrcv.apps.driver_config import normalize_config
    truth = read_json('experiments/jacket_lookup/ground_truth.json')['labels']
    manifest = read_json(ROOT/'corpus/manifest.json')
    results = []
    for video in manifest['videos']:
        print('Replaying '+video['file'],flush=True)
        engine = RecognitionEngine(normalize_config({}))
        services = {mode:SplashService({**CFG,'mode':mode},dict(enabled=mode=='event'))
                    for mode in ('event','full')}
        path = Path(videos)/video['file']
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened(): raise ValueError(str(path))
        fps = cap.get(cv2.CAP_PROP_FPS); index = 0
        observations = []; begins = {}; confirmed = {}
        start = time.perf_counter()
        try:
            while cap.grab():
                if index % 3 == 0:
                    ok,frame = cap.retrieve()
                    if not ok: break
                    t = index/fps
                    result = engine.process(frame,t)
                    state = result['published']
                    generation = engine.session.song_generation
                    if result['raw_state']=='song_splash':
                        begins.setdefault(generation,t)
                    for service in services.values():
                        service.submit(frame,t,result['raw_state'],state['state'],state['players'],generation)
                    # Offline accelerated replay drains jobs at sample boundaries;
                    # wall-clock performance is measured by paced(), not this scan.
                    if result['raw_state'] in ('song_splash','login'):
                        for service in services.values():
                            if service.worker:
                                wait(lambda: not service.worker.status()['busy'] and not service.worker.status()['pending'])
                            wait(lambda: not service.names.busy and service.names.pending is None)
                    for mode,service in services.items():
                        snapshot=service.snapshot()
                        song=snapshot['song']
                        if song:
                            key=(mode,generation)
                            confirmed.setdefault(key,dict(first_song=t,first_charts=None))
                            if all(song['charts'][f'p{p}'] is not None or not state['players'][p-1] for p in (1,2)):
                                confirmed[key]['first_charts'] = confirmed[key]['first_charts'] or t
                            if not observations or observations[-1].get('mode')!=mode or observations[-1].get('generation')!=generation:
                                pass
                            matches=[r for r in observations if r['mode']==mode and r['generation']==generation]
                            entry=dict(mode=mode,generation=generation,source_seconds=t,first_raw_splash=begins.get(generation),
                                       **confirmed[key],snapshot=snapshot)
                            if matches: observations[observations.index(matches[0])]=entry
                            else: observations.append(entry)
                index += 1
        finally:
            cap.release()
            for service in services.values(): service.close()
        expected=[r for r in manifest['samples'] if r['video']==video['file'] and r['kind']=='clean']
        for item in observations:
            timestamp=item['first_song']
            nearest=min(expected,key=lambda r:abs(r['seconds']-timestamp)) if expected else None
            label=truth[nearest['id']] if nearest else None
            item['expected_id']=nearest['id'] if nearest else None
            item['song_correct']=bool(label and item['snapshot']['song']['song_id']==label['song_id'])
            item['difficulty_correct']={p: bool(chart and label and chart['difficulty']==label['players'][p]['difficulty'])
                                         for p,chart in item['snapshot']['song']['charts'].items()}
        results.append(dict(video=video['file'],decoded_frames=index,processing_seconds=time.perf_counter()-start,
                            expected_splashes=len(expected),observations=observations,
                            worker_status={m:s.status() for m,s in services.items()}))
        dump_json(OUT/'replay.json',dict(protocol='All video frames decoded; recognition 10 Hz; drain async jobs during splash/login; source-time confirmation, not wall latency',
                                      videos=results))
        print(dict(video=video['file'],frames=index,observations=len(observations)),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase',choices=('parity','paced','replay'))
    p.add_argument('--output',type=Path,default=OUT/'paced.json')
    p.add_argument('--videos',default='D:/TBD5')
    args=p.parse_args(); cv2.setNumThreads(1)
    if args.phase=='parity': parity()
    elif args.phase=='paced': paced(args.output)
    else: replay(args.videos)

if __name__=='__main__': main()
