"""Paired sequential/threaded splash and name-OCR measurements, offline only."""
import argparse
import importlib.util
import os
from pathlib import Path
import sys
import time
from concurrent.futures import ThreadPoolExecutor

for _key in ('OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','OMP_NUM_THREADS'):
    os.environ[_key]='1'

import cv2

from .catalog import read_json,dump_json,sha256
from .corpus import read_image,crop
from .benchmark import metrics
from .lookup import Lookup,lookup_splash
from .difficulty import DifficultyTemplates
from .performance import Parity
from .threaded import ThreadedSplashLookup,LatestSplashService


def run(root, out, repeats, rounds):
    from ddrcv.ocr.rapid import RapidOCRRecognizer
    from ddrcv.state.player_names import PlayerNameReader,validate_config,NAME_BOXES
    out.mkdir(parents=True,exist_ok=True)
    frozen=read_json(root/'benchmark/frozen.json')
    manifest=read_json(root/'corpus/manifest.json')
    frames=[(r,read_image(root/'corpus'/r['image'])) for r in manifest['samples']]
    clean=[(r,im) for r,im in frames if r['kind']=='clean']
    reader=DifficultyTemplates(root/'difficulty-template')
    # Deliberately separate instances: sharing one recognizer would serialize
    # names and difficulty on RapidOCRRecognizer's inference lock.
    ocr=RapidOCRRecognizer(allow_download=False,num_threads=1);ocr.warmup()
    names=PlayerNameReader(validate_config(dict(ocr=dict(allow_download=False,num_threads=1))));names.warmup()
    before_file=out/'baseline/lookup.py'
    expected=read_json(out/'baseline/snapshot.json')['lookup.py']
    if sha256(before_file.read_bytes())!=expected:raise ValueError('Sequential baseline changed')
    spec=importlib.util.spec_from_file_location('experiments.jacket_lookup._before_threads',before_file)
    before=importlib.util.module_from_spec(spec);spec.loader.exec_module(before)
    parity=Parity();results={};submission={}
    with ThreadPoolExecutor(max_workers=1,thread_name_prefix='benchmark-name-ocr') as name_pool:
        for mode in ('full','event'):
            selected=frozen['selected'][mode];thresholds=frozen['configurations'][selected]['thresholds']
            old=before.Lookup(root/'index'/selected,thresholds=thresholds)
            seq=Lookup(root/'index'/selected,thresholds=thresholds)
            par=Lookup(root/'index'/selected,thresholds=thresholds)
            results[mode]={}
            for method in ('template','ocr'):
                kwargs=dict(difficulty_reader=reader) if method=='template' else dict(recognizer=ocr)
                with ThreadedSplashLookup(par,high_qos=False,**kwargs) as processor:
                    for row,image in frames:
                        original=before.lookup_splash(old,image,**kwargs)
                        sequential=lookup_splash(seq,image,**kwargs)
                        threaded=processor.analyze(image)
                        parity.check(mode+'_'+method+'_refactor',row['id'],original,sequential)
                        parity.check(mode+'_'+method+'_threaded',row['id'],sequential,threaded)
                    for _,image in clean:
                        names.read({i:crop(image,roi) for i,roi in enumerate(NAME_BOXES)})
                    measurements={implementation:[] for implementation in ('sequential','threaded')}
                    batch_results=[]
                    for batch in range(rounds):
                        batch_samples={key:[] for key in measurements}
                        for repeat in range(repeats):
                            for number,(row,image) in enumerate(clean if (batch+repeat)%2 else clean[::-1]):
                                name_crops={i:crop(image,roi) for i,roi in enumerate(NAME_BOXES)}
                                pair={}
                                for implementation in (('sequential','threaded') if (batch+repeat+number)%2 else ('threaded','sequential')):
                                    start=time.perf_counter()
                                    if implementation=='sequential':
                                        chart=lookup_splash(seq,image,**kwargs)
                                        chart_ready=(time.perf_counter()-start)*1000
                                        name_values=names.read(name_crops)
                                    else:
                                        future=name_pool.submit(names.read,name_crops)
                                        chart=processor.analyze(image)
                                        chart_ready=(time.perf_counter()-start)*1000
                                        name_values=future.result()
                                    sample=dict(all_ready_ms=(time.perf_counter()-start)*1000,
                                                chart_ready_ms=chart_ready,chart_stages=chart['timings_ms'])
                                    measurements[implementation].append(sample);batch_samples[implementation].append(sample)
                                    pair[implementation]=dict(chart=chart,names={str(k):v for k,v in name_values.items()})
                                parity.check(mode+'_'+method+'_names_pair',f'{batch}_{repeat}_{row["id"]}',pair['sequential'],pair['threaded'],record=False)
                        batch_results.append({key:{stage:metrics([s[stage] for s in samples]) for stage in ('all_ready_ms','chart_ready_ms')}
                            for key,samples in batch_samples.items()})
                        print(f'{mode} {method}: threaded timing round {batch+1}/{rounds}',flush=True)
                    results[mode][method]=dict(summary={key:{stage:metrics([s[stage] for s in samples]) for stage in ('all_ready_ms','chart_ready_ms')}
                        for key,samples in measurements.items()},rounds=batch_results,samples=measurements)
            # Producer overhead under load: full-frame copies and bounded queue,
            # with no waiting for the chart or difficulty computation to finish.
            with LatestSplashService(ThreadedSplashLookup(par,difficulty_reader=reader,high_qos=False)) as service:
                timings=[]
                for i in range(200):
                    image=clean[i%len(clean)][1]
                    start=time.perf_counter();service.submit(image,i/60,'submission-probe')
                    timings.append((time.perf_counter()-start)*1000)
                submission[mode]=dict(submit_ms=metrics(timings),status=service.status())
    result=dict(schema=1,protocol='CPU; native thread counts=1; independent warmed OCR instances for names and difficulty; paired alternating sequential/threaded calls',
        repeats=repeats,rounds=rounds,parity=dict(counts=parity.counts,max_float_difference=parity.max_float_difference),
        submission=submission,results=results,
        files={str(p):sha256(p.read_bytes()) for p in (root/'benchmark/frozen.json',root/'difficulty-template/bank.json',before_file)})
    dump_json(out/'results.json',result)
    dump_json(out/'parity.json',parity.records)
    concise={**result,'results':{mode:{method:{k:v for k,v in row.items() if k!='samples'} for method,row in methods.items()} for mode,methods in results.items()}}
    dump_json(out/'summary.json',concise)
    return concise


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path('experiments/jacket_lookup/artifacts'))
    p.add_argument('--out',type=Path,default=Path('experiments/jacket_lookup/artifacts/threading'))
    p.add_argument('--repeats',type=int,default=4)
    p.add_argument('--rounds',type=int,default=3)
    a=p.parse_args();cv2.setNumThreads(1)
    run(a.root,a.out,a.repeats,a.rounds)


if __name__=='__main__':main()
