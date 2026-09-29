"""Qualify deterministic CPU builds without changing frozen acceptance thresholds.

    python -m experiments.jacket_lookup.portable_gallery_validation --build-all

Requires the original pinned source cache, corpus and integration containers.
Large outputs are written under ignored artifacts/integration/review-fixes.
"""
import os
for name in ('OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'OMP_NUM_THREADS'):
    os.environ[name] = '1'
os.environ.setdefault('OPENBLAS_CORETYPE', 'Haswell')

import argparse
from collections import Counter
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

import cv2
import numpy as np

from ddrcv.jacket_lookup import assets, catalog
from ddrcv.jacket_lookup.features import PortableEncoder, build_index
from ddrcv.jacket_lookup.fingerprint import gallery_fingerprint
from ddrcv.jacket_lookup.lookup import Lookup
from .benchmark import queries, metrics

ROOT = Path('experiments/jacket_lookup/artifacts')
OUT = ROOT/'integration/review-fixes'
VARIANTS = {'haswell': ('Haswell', True), 'sandybridge': ('Sandybridge', True),
            'scalar': ('Sandybridge', False), 'numpy_baseline': ('Sandybridge', False)}


def build(variant):
    core, optimized = VARIANTS[variant]
    assert os.environ['OPENBLAS_CORETYPE'] == core
    cv2.setUseOptimized(optimized)
    path = OUT/variant
    build_index(ROOT/'catalog/full.json', path, encoder_factory=PortableEncoder)
    lookup = Lookup(path, thresholds=assets.profile())
    result = dict(variant=variant, core=core, opencv_optimized=optimized, images=len(lookup.images),
                  fingerprint=gallery_fingerprint(lookup.meta, lookup.vectors, lookup.images),
                  numpy_disabled_features=os.environ.get('NPY_DISABLE_CPU_FEATURES', ''),
                  build_seconds=lookup.meta['build_seconds'])
    catalog.dump_json(OUT/(variant+'.json'), result)
    print(result, flush=True)


def compare(a, b, path, deltas, differences):
    if isinstance(a, dict) and isinstance(b, dict):
        ignored = {'timings_ms', 'elapsed_ms'}
        if path.endswith('/thresholds'):
            # Only gallery identity/provenance changes; compare score and margin.
            assert a == assets.legacy_profile() and b == assets.profile()
            ignored |= {'gallery_fingerprint', 'source_index_sha256', 'equivalent_to'}
        keys = set(a)-ignored
        if keys != set(b)-ignored:
            differences.append(path+': keys')
            return
        for key in sorted(keys):
            compare(a[key], b[key], path+'/'+key, deltas, differences)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x,y) in enumerate(zip(a,b)):
            compare(x,y,path+'/'+str(i),deltas,differences)
    elif isinstance(a,float) and isinstance(b,float):
        delta = abs(a-b)
        deltas[path.rsplit('/',1)[-1]] = max(deltas.get(path.rsplit('/',1)[-1],0), delta)
        if delta > 1e-6:
            differences.append(dict(path=path, before=a, after=b))
    elif a != b:
        differences.append(dict(path=path, before=a, after=b))


def main(build_all):
    OUT.mkdir(parents=True, exist_ok=True)
    if build_all:
        for variant, (core, _) in VARIANTS.items():
            with (OUT/(variant+'.log')).open('w') as log:
                subprocess.run([sys.executable, '-B', '-m', __spec__.name, '--build', variant],
                    env={**os.environ, 'OPENBLAS_CORETYPE': core, 'NPY_DISABLE_CPU_FEATURES':
                         'AVX,AVX2,FMA3,F16C' if variant == 'numpy_baseline' else ''}, stdout=log, stderr=subprocess.STDOUT,
                    check=True)
            print('Qualified build:', variant, flush=True)
    builds = [catalog.read_json(OUT/(v+'.json')) for v in VARIANTS]
    assert len({b['fingerprint'] for b in builds}) == 1
    report = dict(builds=builds, thresholds={k: assets.profile()[k] for k in ('score','margin')},
                  old_profile=assets.legacy_profile(), new_profile=assets.profile(),
                  differences=[], max_score_deltas={}, catalogs={}, cpu_threads=1,
                  numpy=np.__version__, opencv=cv2.__version__)
    directory = OUT/'haswell'
    metadata, arrays = (directory/'index.json').read_bytes(), (directory/'vectors.npz').read_bytes()
    truth = catalog.read_json('experiments/jacket_lookup/ground_truth.json')
    for mode, name in (('event','dia_del_ritmo_26'),('full','full-world')):
        before = assets.load(dict(mode=mode, catalog_file=str(ROOT/'integration'/(name+'.ddrcatalog'))))
        selected = deepcopy(before.selection)
        selected['gallery_fingerprint'] = assets.profile()['gallery_fingerprint']
        cfg = dict(mode=mode, catalog_file=str(OUT/(name+'.ddrcatalog')))
        assets._publish(Path(cfg['catalog_file']), metadata, arrays, selected, assets.validate_config(cfg))
        after = assets.load(cfg)
        assert np.array_equal(before.images, after.images)
        report['max_reference_vector_delta'] = float(np.max(np.abs(before.vectors-after.vectors)))
        processors = {'legacy': assets.processor(lookup=before), 'portable': assets.processor(lookup=after)}
        lookups = {'legacy': before, 'portable': after}
        kinds, splash, rows = Counter(), 0, []
        warm = {label: [] for label in processors}
        encode = {label: [] for label in processors}
        try:
            for index, q in enumerate(queries(ROOT/'corpus', truth, before.catalog)):
                values = {label: lookup.lookup(q['image'],exclude_song_ids=q['exclude'])
                          for label,lookup in lookups.items()}
                compare(values['legacy'],values['portable'],mode+'/'+q['id']+'/jacket',
                        report['max_score_deltas'],report['differences'])
                kinds[q['kind']] += 1
                row = dict(id=q['id'],kind=q['kind'],before=values['legacy'],after=values['portable'])
                if q['kind'] in ('clean','transition','negative'):
                    results = {label: p.analyze(q['frame']) for label,p in processors.items()}
                    compare(results['legacy'],results['portable'],mode+'/'+q['id']+'/splash',
                            report['max_score_deltas'],report['differences'])
                    row['splash'] = results
                    splash += 1
                rows.append(row)
                if q['kind'] == 'clean':
                    for iteration in range(10):
                        for label in (('legacy','portable') if iteration % 2 else ('portable','legacy')):
                            began = time.perf_counter()
                            result = processors[label].analyze(q['frame'])
                            warm[label].append((time.perf_counter()-began)*1000)
                            encode[label].append(result['timings_ms']['encode'])
        finally:
            for p in processors.values():
                p.close()
        report['catalogs'][mode] = dict(jacket_queries=dict(kinds),splash_comparisons=splash,
            warm_template_splash_ms={k:metrics(v) for k,v in warm.items()},
            warm_encode_ms={k:metrics(v) for k,v in encode.items()})
        catalog.dump_json(OUT/(mode+'-queries.json'),rows)
        print(mode, report['catalogs'][mode], flush=True)
    # Exercise the actual provisioning path under the formerly failing BLAS
    # dispatch, from an empty build cache, using only pinned source bytes.
    with (OUT/'fresh-prepare.log').open('w') as log:
        subprocess.run([sys.executable, '-B', '-m', __spec__.name, '--prepare-fresh'],
                       env={**os.environ, 'OPENBLAS_CORETYPE': 'Sandybridge'},
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    report['fresh_offline_prepare'] = catalog.read_json(OUT/'fresh-prepare.json')
    report['ok'] = not report['differences']
    catalog.dump_json(OUT/'summary.json',report)
    print('Differences:',report['differences'],flush=True)
    assert report['ok'], report['differences']


def prepare_fresh():
    from uuid import uuid4
    cfg = dict(assets_dir=str(OUT/'fresh-sandybridge'/uuid4().hex))
    assert not Path(cfg['assets_dir']).exists()
    with patch('socket.socket.connect',side_effect=AssertionError('Network')):
        prepared = assets.prepare(cfg, ref=assets.profile()['source_commit'], source_root=ROOT/'catalog')
        assert prepared['ok'], prepared
    catalog.dump_json(OUT/'fresh-prepare.json', dict(result=prepared, empty_build_cache=True,
        core=os.environ['OPENBLAS_CORETYPE'], network_access=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build',choices=VARIANTS)
    parser.add_argument('--build-all',action='store_true')
    parser.add_argument('--prepare-fresh',action='store_true')
    args = parser.parse_args()
    if args.build:
        build(args.build)
    elif args.prepare_fresh:
        prepare_fresh()
    else:
        main(args.build_all)
