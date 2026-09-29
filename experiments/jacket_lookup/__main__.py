"""Source-checkout CLI; run with python -m experiments.jacket_lookup."""
import argparse
import json
import os
from pathlib import Path

from .configuration import WORKING_CONFIG


for _name in ('OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'OMP_NUM_THREADS'):
    os.environ[_name] = '1'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    c = sub.add_parser('catalog')
    c.add_argument('--root', default='experiments/jacket_lookup/artifacts/catalog')
    c.add_argument('--mode', choices=('event', 'full'), default='event')
    c.add_argument('--event', default=WORKING_CONFIG.event)
    c.add_argument('--ref', default='c62053faa82df55ebc926812a7af684f520ae704')
    c = sub.add_parser('extract')
    c.add_argument('--videos', required=True)
    c.add_argument('--out', default='experiments/jacket_lookup/artifacts/corpus')
    c = sub.add_parser('encode')
    c.add_argument('--catalog', required=True)
    c.add_argument('--out', required=True)
    c.add_argument('--method', choices=('classical', 'sift', 'mobilenet', 'efficientnet'), default='classical')
    c.add_argument('--size', type=int, choices=(128, 150), default=128)
    c.add_argument('--models', default=None)
    c = sub.add_parser('lookup')
    c.add_argument('--index', required=True)
    c.add_argument('--image', required=True)
    c.add_argument('--thresholds', required=True)
    c.add_argument('--splash', action='store_true')
    c.add_argument('--splash-execution', choices=('sequential', 'threaded'), default=WORKING_CONFIG.splash_execution)
    c.add_argument('--difficulty-method', choices=('ocr', 'template'), default=WORKING_CONFIG.difficulty_method)
    c.add_argument('--worker-qos', choices=('system', 'high'), default='high' if WORKING_CONFIG.high_qos else 'system')
    c.add_argument('--difficulty-templates', default='experiments/jacket_lookup/artifacts/difficulty-template')
    c.add_argument('--style', choices=('single', 'double'), default='single')
    c.add_argument('--models', default=None)
    c.add_argument('--output')
    c = sub.add_parser('benchmark')
    c.add_argument('--root', default='experiments/jacket_lookup/artifacts')
    c.add_argument('--corpus', default='experiments/jacket_lookup/artifacts/corpus')
    c.add_argument('--labels', default='experiments/jacket_lookup/ground_truth.json')
    c.add_argument('--out', default='experiments/jacket_lookup/artifacts/benchmark')
    c.add_argument('--phase', choices=('all', 'calibrate', 'evaluate'), default='all')
    c.add_argument('--repeats', type=int, default=12)
    c.add_argument('--methods', nargs='+', choices=('classical', 'sift', 'mobilenet', 'efficientnet'), default=('classical', 'sift', 'mobilenet', 'efficientnet'))
    c.add_argument('--sizes', nargs='+', type=int, choices=(128,150), default=(128,150))
    c = sub.add_parser('difficulty-benchmark')
    c.add_argument('--root', default='experiments/jacket_lookup/artifacts')
    c.add_argument('--corpus', default='experiments/jacket_lookup/artifacts/corpus')
    c.add_argument('--labels', default='experiments/jacket_lookup/ground_truth.json')
    c.add_argument('--out', default='experiments/jacket_lookup/artifacts/difficulty-template')
    c.add_argument('--phase', choices=('calibrate', 'evaluate', 'all'), default='all')
    c.add_argument('--repeats', type=int, default=12)
    c = sub.add_parser('check')
    c.add_argument('--provision', action='store_true')
    for command in ('evidence', 'profile-worker'):
        c = sub.add_parser(command)
        c.add_argument('--root', default='experiments/jacket_lookup/artifacts')
        c.add_argument('--corpus', default='experiments/jacket_lookup/artifacts/corpus')
        c.add_argument('--out', default='experiments/jacket_lookup/artifacts/benchmark')
        c.add_argument('--repeats', type=int, default=20)
        if command == 'profile-worker':
            c.add_argument('--name', required=True)
        else:
            c.add_argument('--labels', default='experiments/jacket_lookup/ground_truth.json')
    a = p.parse_args()
    if a.command == 'profile-worker':
        from .evidence import profile_worker
        print(json.dumps(profile_worker(a.root, a.corpus, a.out, a.name, a.repeats)))
    elif a.command == 'evidence':
        from .evidence import splash_evidence, profiles, render
        splash_evidence(a.root, a.corpus, a.labels, a.out)
        profiles(a.root, a.corpus, a.out, a.repeats)
        print(render(a.root, a.corpus, a.out))
    elif a.command == 'difficulty-benchmark':
        from .difficulty_benchmark import run
        run(a.root, a.corpus, a.labels, a.out, phase=a.phase, repeats=a.repeats)
    elif a.command == 'check':
        from .check import check
        result = check(provision=a.provision)
        print(json.dumps(result, indent=2))
        raise SystemExit(0 if result['ok'] else 1)
    elif a.command == 'catalog':
        from .catalog import prepare
        path, catalog = prepare(a.root, mode=a.mode, event=a.event, ref=a.ref)
        print(json.dumps(dict(path=str(path), records=len(catalog['records']), assets=len(catalog['assets']),
                              failures=catalog['failures']), indent=2))
    elif a.command == 'extract':
        from .corpus import extract
        extract(a.videos, a.out)
    elif a.command == 'encode':
        from .features import build_index
        meta = build_index(a.catalog, a.out, method=a.method, size=a.size, model_dir=a.models)
        print(json.dumps({k: meta[k] for k in ('method', 'size', 'build_seconds', 'model_init_seconds')}))
    elif a.command == 'benchmark':
        from .benchmark import run
        run(a.root, a.corpus, a.labels, a.out, phase=a.phase, repeats=a.repeats, methods=a.methods, sizes=a.sizes)
    elif a.command == 'lookup':
        from .catalog import read_json, dump_json
        from .corpus import read_image
        from .lookup import Lookup, lookup_splash
        profile = read_json(a.thresholds)
        if not profile.get('index_sha256'):
            raise ValueError('Use a benchmark-generated threshold profile bound to this index')
        lookup = Lookup(a.index, model_dir=a.models, thresholds=profile)
        image = read_image(a.image)
        reader = None
        if a.splash and a.difficulty_method == 'template':
            from .difficulty import DifficultyTemplates
            reader = DifficultyTemplates(a.difficulty_templates)
        if a.splash and a.splash_execution == 'threaded':
            from .threaded import ThreadedSplashLookup
            with ThreadedSplashLookup(lookup, difficulty_reader=reader, high_qos=a.worker_qos == 'high') as processor:
                result = processor.analyze(image, style=a.style)
        else:
            from .execution import run_with_qos
            result = run_with_qos(a.worker_qos == 'high', lookup_splash, lookup, image, style=a.style, difficulty_reader=reader) if a.splash else lookup.lookup(image)
        if a.output:
            dump_json(a.output, result)
        print(json.dumps(result, indent=2, ensure_ascii=True))


if __name__ == '__main__':
    main()
