"""Compare a trusted source snapshot with the optimized experiment, offline."""
from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

for _name in ('OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'OMP_NUM_THREADS'):
    os.environ[_name] = '1'

import cv2
import numpy as np

from . import difficulty, lookup
from .benchmark import memory_bytes, metrics, queries
from .catalog import dump_json, read_json, sha256
from .corpus import crop, DIFFICULTY_ROIS, read_image
from .difficulty_benchmark import perturbations


def load_baseline(directory):
    """Execute only the explicitly selected, locally captured Python snapshot."""
    directory = Path(directory)
    snapshot = read_json(directory/'snapshot.json')
    for name, digest in snapshot['files'].items():
        if Path(name).name != name or sha256((directory/name).read_bytes()) != digest:
            raise ValueError('Baseline source checksum mismatch')
    package = 'experiments.jacket_lookup._performance_baseline'
    spec = importlib.util.spec_from_file_location(package, directory/'__init__.py',
                                                submodule_search_locations=[str(directory)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    spec.loader.exec_module(module)
    return {name:importlib.import_module(package+'.'+name) for name in ('lookup','difficulty','catalog')}


def snapshot(out):
    target = Path(out)/'baseline'
    if target.exists():
        raise FileExistsError('Baseline exists; select a new output directory')
    target.mkdir(parents=True)
    hashes = {}
    for source in Path(__file__).parent.glob('*.py'):
        data = source.read_bytes()
        (target/source.name).write_bytes(data)
        hashes[source.name] = sha256(data)
    dump_json(target/'snapshot.json', dict(schema=1, files=hashes,
        description='Source captured before the performance change under comparison'))


def stable(value):
    if isinstance(value, dict):
        return {k:stable(v) for k,v in value.items() if k not in ('timings_ms','elapsed_ms')}
    if isinstance(value, (tuple, list)):
        return [stable(v) for v in value]
    return value


class Parity:
    def __init__(self):
        self.counts = {}
        self.max_float_difference = 0.0
        self.records = []

    def _check(self, a, b, path=''):
        if isinstance(a, dict):
            if a.keys() != b.keys():
                raise AssertionError(f'{path}: different result keys')
            for key in a:
                self._check(a[key], b[key], path+'/'+key)
        elif isinstance(a, list):
            if len(a) != len(b):
                raise AssertionError(f'{path}: different list lengths')
            for i,(left,right) in enumerate(zip(a,b)):
                self._check(left, right, path+'/'+str(i))
        elif isinstance(a, float):
            delta = abs(a-b)
            self.max_float_difference = max(self.max_float_difference, delta)
            if not np.isfinite(delta) or delta > 1e-6:
                raise AssertionError(f'{path}: {a} != {b}')
        elif a != b:
            raise AssertionError(f'{path}: {a} != {b}')

    def check(self, kind, key, a, b, *, record=True):
        a,b = stable(a),stable(b)
        self._check(a,b,kind+'/'+key)
        self.counts[kind] = self.counts.get(kind,0)+1
        if record:
            self.records.append(dict(kind=kind, id=key, baseline=a, optimized=b))


def objects(root, frozen, mode, baseline):
    selected = frozen['selected'][mode]
    kwargs = dict(thresholds=frozen['configurations'][selected]['thresholds'])
    return dict(baseline=baseline['lookup'].Lookup(root/'index'/selected, **kwargs),
                optimized=lookup.Lookup(root/'index'/selected, **kwargs))


def check_parity(root, corpus, truth, frozen, baseline, ocr, readers):
    parity = Parity()
    rows = read_json(corpus/'manifest.json')['samples']
    for row in rows:
        frame = read_image(corpus/row['image'])
        for player, roi in enumerate(DIFFICULTY_ROIS, 1):
            original = crop(frame,roi)
            cases = [('real',original)] + (list(perturbations(original)) if row['kind']=='clean' else [])
            for variant, image in cases:
                key = f"{row['id']}_p{player}_{variant}"
                a = baseline['difficulty'].text_mask(image)
                b = difficulty.text_mask(image)
                if not np.array_equal(a,b):
                    raise AssertionError('Nonidentical mask: '+key)
                parity.counts['pixel_identical_masks'] = parity.counts.get('pixel_identical_masks',0)+1
                exclusions = [()]
                if row['kind']=='clean':
                    exclusions.append((truth['labels'][row['id']]['players'][f'p{player}']['difficulty'],))
                for exclude in exclusions:
                    parity.check('difficulty',key+str(exclude),readers['baseline'].recognize(image,exclude=exclude),
                                 readers['optimized'].recognize(image,exclude=exclude))
    for mode in ('full','event'):
        pair = objects(root,frozen,mode,baseline)
        for q in queries(corpus,truth,pair['baseline'].catalog):
            parity.check(mode+'_jacket_'+q['kind'], q['id'],
                pair['baseline'].lookup(q['image'],exclude_song_ids=q['exclude']),
                pair['optimized'].lookup(q['image'],exclude_song_ids=q['exclude']))
        # The slow reference scans only selected-dataset records here; other
        # versions are irrelevant by definition and separately exercised by tests.
        catalog = pair['baseline'].catalog
        selected = {**catalog, 'records':[r for r in catalog['records'] if r['dataset']==catalog['metadata_dataset']]}
        keys = {(r['song_id'],c['style'],c['difficulty'],level) for r in selected['records']
                for c in r['charts'] for level in (None,c['level'])}
        keys.add(('absent-song','single','expert',None))
        for key in keys:
            parity.check(mode+'_chart',str(key),baseline['catalog'].resolve_chart(selected,*key),
                         pair['optimized']._charts.resolve(*key),record=False)
        for row in rows:
            frame = read_image(corpus/row['image'])
            frames = [('real',frame)]
            if row['kind']=='clean':
                variants = [dict(perturbations(crop(frame,roi))) for roi in DIFFICULTY_ROIS]
                for variant in variants[0]:
                    changed = frame.copy()
                    for index,(x,y,w,h) in enumerate(DIFFICULTY_ROIS):
                        changed[y:y+h,x:x+w] = variants[index][variant]
                    frames.append((variant,changed))
            for variant, image in frames:
                for method in ('template','ocr'):
                    result = {}
                    for implementation, obj in pair.items():
                        kwargs = dict(difficulty_reader=readers[implementation]) if method=='template' else dict(recognizer=ocr)
                        fn = baseline['lookup'].lookup_splash if implementation=='baseline' else lookup.lookup_splash
                        result[implementation] = fn(obj,image,**kwargs)
                    parity.check(mode+'_splash_'+method,row['id']+'_'+variant,result['baseline'],result['optimized'])
        print(f'Parity complete: {mode}',flush=True)
    return parity


def warm_comparison(root, corpus, frozen, baseline, ocr, readers, repeats, rounds):
    frames = [read_image(corpus/r['image']) for r in read_json(corpus/'manifest.json')['samples'] if r['kind']=='clean']
    pairs = {mode:objects(root,frozen,mode,baseline) for mode in ('full','event')}
    conditions = [(mode,method) for mode in pairs for method in ('template','ocr')]
    def call(mode, method, implementation, frame):
        fn = baseline['lookup'].lookup_splash if implementation=='baseline' else lookup.lookup_splash
        kwargs = dict(difficulty_reader=readers[implementation]) if method=='template' else dict(recognizer=ocr)
        return fn(pairs[mode][implementation],frame,**kwargs)['timings_ms']
    for mode,method in conditions:
        for frame in frames:
            for implementation in ('baseline','optimized'):
                call(mode,method,implementation,frame)
    raw = {mode:{method:{name:[] for name in ('baseline','optimized')} for method in ('template','ocr')} for mode in pairs}
    batches = []
    for batch in range(rounds):
        batch_samples = {mode:{method:{name:[] for name in ('baseline','optimized')} for method in ('template','ocr')} for mode in pairs}
        for repeat in range(repeats):
            for index,frame in enumerate(frames if (batch+repeat)%2 else frames[::-1]):
                order = conditions if (repeat+index)%2 else conditions[::-1]
                for mode,method in order:
                    for implementation in (('baseline','optimized') if (batch+repeat+index)%2 else ('optimized','baseline')):
                        timing = call(mode,method,implementation,frame)
                        raw[mode][method][implementation].append(timing)
                        batch_samples[mode][method][implementation].append(timing)
        batches.append({mode:{method:{name:metrics([s['splash_total'] for s in samples])
            for name,samples in methods.items()} for method,methods in modes.items()} for mode,modes in batch_samples.items()})
        print(f'Paired timing round {batch+1}/{rounds} complete',flush=True)
    summary = {}
    for mode,modes in raw.items():
        summary[mode] = {}
        for method,methods in modes.items():
            values = {name:{stage:metrics([s[stage] for s in samples]) for stage in samples[0]} for name,samples in methods.items()}
            before,after = values['baseline']['splash_total'],values['optimized']['splash_total']
            summary[mode][method] = dict(**values, median_reduction_percent=100*(1-after['median']/before['median']),
                                       p95_reduction_percent=100*(1-after['p95']/before['p95']))
    return dict(summary=summary, rounds=batches, samples=raw)


def worker(root, corpus, out, mode, implementation):
    baseline = load_baseline(out/'baseline') if implementation=='baseline' else None
    module = baseline['lookup'] if baseline else lookup
    frozen = read_json(root/'benchmark/frozen.json')
    selected = frozen['selected'][mode]
    start_rss = memory_bytes()
    began = time.perf_counter()
    obj = module.Lookup(root/'index'/selected,thresholds=frozen['configurations'][selected]['thresholds'])
    init_seconds = time.perf_counter()-began
    loaded_rss = memory_bytes()
    reader_module = baseline['difficulty'] if baseline else difficulty
    reader = reader_module.DifficultyTemplates(root/'difficulty-template')
    for row in read_json(corpus/'manifest.json')['samples']:
        if row['kind']=='clean':
            module.lookup_splash(obj,read_image(corpus/row['image']),difficulty_reader=reader)
    grays = getattr(obj,'_reference_grays',[])
    return dict(index_init_seconds=init_seconds, initial_rss=start_rss, loaded_rss=loaded_rss,
        warm_rss=memory_bytes(), cached_gray_count=sum(im is not None for im in grays),
        cached_gray_bytes=sum(im.nbytes for im in grays if im is not None),
        maximum_gray_bytes=int(obj.images.shape[0]*obj.images.shape[1]*obj.images.shape[2]) if grays else 0,
        indexed_chart_keys=len(obj._charts._resolved) if hasattr(obj,'_charts') else 0)


def compare(root, corpus, labels, out, repeats, rounds):
    from ddrcv.ocr.rapid import RapidOCRRecognizer
    baseline = load_baseline(out/'baseline')
    frozen = read_json(root/'benchmark/frozen.json')
    readers = dict(baseline=baseline['difficulty'].DifficultyTemplates(root/'difficulty-template'),
                   optimized=difficulty.DifficultyTemplates(root/'difficulty-template'))
    ocr = RapidOCRRecognizer(allow_download=False,num_threads=1)
    ocr.warmup()
    parity = check_parity(root,corpus,read_json(labels),frozen,baseline,ocr,readers)
    dump_json(out/'parity.json',dict(counts=parity.counts,max_float_difference=parity.max_float_difference,records=parity.records))
    timing = warm_comparison(root,corpus,frozen,baseline,ocr,readers,repeats,rounds)
    dump_json(out/'timings.json',timing)
    processes = {}
    for mode in ('full','event'):
        processes[mode] = {}
        for implementation in ('baseline','optimized'):
            values = []
            for _ in range(3):
                raw = subprocess.check_output([sys.executable,'-B','-m','experiments.jacket_lookup.performance',
                    '--phase','worker','--root',str(root),'--corpus',str(corpus),'--out',str(out),
                    '--mode',mode,'--implementation',implementation],text=True)
                values.append(json.loads(raw))
            processes[mode][implementation] = values
    result = dict(schema=1, protocol='Windows CPU; one OpenCV/BLAS/ORT thread; alternating paired implementations and method/catalog order; loaded OCR shared by both baselines',
        repeats=repeats, rounds=rounds, input_hashes={str(p):sha256(p.read_bytes()) for p in (
            Path(labels),corpus/'manifest.json',root/'benchmark/frozen.json',root/'difficulty-template/bank.json')},
        baseline_sources=read_json(out/'baseline/snapshot.json'),
        optimized_sources={p.name:sha256(p.read_bytes()) for p in Path(__file__).parent.glob('*.py')},
        parity=dict(counts=parity.counts,max_float_difference=parity.max_float_difference),
        timings=timing['summary'], timing_rounds=timing['rounds'], fresh_processes=processes)
    dump_json(out/'summary.json',result)
    print(json.dumps(dict(parity=result['parity'],timings=result['timings']),indent=2))
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--phase',choices=('snapshot','compare','worker'),default='compare')
    p.add_argument('--root',type=Path,default=Path('experiments/jacket_lookup/artifacts'))
    p.add_argument('--corpus',type=Path,default=Path('experiments/jacket_lookup/artifacts/corpus'))
    p.add_argument('--labels',type=Path,default=Path('experiments/jacket_lookup/ground_truth.json'))
    p.add_argument('--out',type=Path,default=Path('experiments/jacket_lookup/artifacts/performance'))
    p.add_argument('--repeats',type=int,default=12)
    p.add_argument('--rounds',type=int,default=3)
    p.add_argument('--mode',choices=('full','event'))
    p.add_argument('--implementation',choices=('baseline','optimized'))
    a = p.parse_args()
    cv2.setNumThreads(1)
    if a.phase=='snapshot':
        snapshot(a.out)
    elif a.phase=='worker':
        print(json.dumps(worker(a.root,a.corpus,a.out,a.mode,a.implementation)))
    else:
        compare(a.root,a.corpus,a.labels,a.out,a.repeats,a.rounds)


if __name__=='__main__':
    main()
