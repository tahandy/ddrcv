"""Song-disjoint calibration, frozen evaluation, and CPU timing evidence."""
from __future__ import annotations

import ctypes
import gc
import hashlib
import json
import os
from pathlib import Path
import platform
import time

import cv2
import numpy as np

from .catalog import dump_json, read_json, resolve_chart, sha256
from .corpus import crop, read_image, write_image
from .features import METHODS, build_index, resize
from .lookup import Lookup, lookup_splash


def metrics(values):
    if not values:
        return None
    return dict(n=len(values), median=float(np.median(values)), p95=float(np.percentile(values, 95)),
                p99=float(np.percentile(values, 99)), maximum=float(max(values)))


def memory_bytes():
    if os.name != 'nt':
        import resource
        return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)
    class Counters(ctypes.Structure):
        _fields_ = [('cb', ctypes.c_ulong), ('PageFaultCount', ctypes.c_ulong)] + [
            (name, ctypes.c_size_t) for name in ('PeakWorkingSetSize', 'WorkingSetSize',
            'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
            'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    fn = ctypes.windll.psapi.GetProcessMemoryInfo
    fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
    if not fn(ctypes.c_void_p(-1), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError()
    return int(counters.WorkingSetSize)


def split_labels(labels):
    songs = sorted({r['song_id'] for r in labels.values()}, key=lambda x: sha256(x.encode()))
    calibration = set(songs[:max(1, len(songs)//2)])
    return {sid: 'calibration' if sid in calibration else 'evaluation' for sid in songs}


def synthetic(image):
    for size in (128, 150):
        yield f'resample_{size}', resize(resize(image, size), image.shape[0])
    ok, encoded = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 35])
    yield 'jpeg35', cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    yield 'blur', cv2.GaussianBlur(image, (9, 9), 2)
    yield 'color', np.clip(image.astype(np.float32)*[.8, .95, 1.1]+8, 0, 255).astype(np.uint8)
    shift = np.float32([[1, 0, 9], [0, 1, -6]])
    yield 'offset', cv2.warpAffine(image, shift, image.shape[1::-1], borderMode=cv2.BORDER_REFLECT)
    border = image.copy()
    border[:12] = border[-12:] = (90, 200, 20)
    border[:, :12] = border[:, -12:] = (90, 200, 20)
    yield 'border', border


def queries(corpus, truth, catalog):
    corpus = Path(corpus)
    manifest = read_json(corpus / 'manifest.json')
    labels = truth['labels']
    split = split_labels(labels)
    present = {r['song_id'] for r in catalog['records']}
    # These exit frames retain a small but visually identifiable circle of artwork.
    partial = {'2025-03-19_16-29-40_00', '2025-03-19_16-47-45_03',
               '2025-03-27_15-43-31_00', '2025-03-27_15-52-48_00'}
    for row in manifest['samples']:
        frame = read_image(corpus / row['image'])
        image = crop(frame)
        label = labels.get(row.get('parent', row['id']))
        sid = label['song_id'] if label else None
        phase = split[sid] if sid else ('calibration' if int(sha256(row['video'].encode())[:8], 16)%2 else 'evaluation')
        visible = row['kind'] == 'clean' or (row['kind'] == 'transition' and
                    (row['id'].endswith('_entry') or row['parent'] in partial))
        expected = sid if visible and sid in present else None
        base = dict(id=row['id'], group=sid or row['video'], phase=phase, kind=row['kind'],
                    expected=expected, source_song=sid, image=image, frame=frame, exclude=())
        yield base
        if row['kind'] == 'clean':
            yield {**base, 'id':row['id']+'_withheld', 'kind':'withheld', 'expected':None,
                   'exclude':(sid,)}
            for variant, changed in synthetic(image):
                yield {**base, 'id':row['id']+'_'+variant, 'kind':'synthetic', 'variant':variant, 'image':changed}


def observe(lookup, query):
    result = lookup.lookup(query['image'], exclude_song_ids=query['exclude'])
    best = result['candidates'][0] if result['candidates'] else None
    return dict(**{k: query.get(k) for k in ('id', 'group', 'phase', 'kind', 'variant', 'expected', 'source_song')},
        predicted=best['song_id'] if best else None, name=best['name'] if best else None,
        score=best['score'] if best else -1, margin=result['margin'],
        eligible=bool(best and best['name'] and not best['shared_artwork']),
        top5=[c['song_id'] for c in result['candidates']],
        accepted=result['accepted'], reason=result['reason'], timings_ms=result['timings_ms'])


def fit_thresholds(rows):
    """Grid selection on calibration only: zero false accepts, then recall, then clearance."""
    best = None
    for score in np.arange(.4, 1.001, .01):
        for margin in np.arange(.02, .301, .01):
            correct, false, clearance = 0, 0, []
            for r in rows:
                ok = r['eligible'] and r['score'] >= score and r['margin'] >= margin
                truth = r['expected'] is not None and r['predicted'] == r['expected']
                if ok and not truth:
                    false += 1
                    break
                if ok and truth:
                    correct += 3 if r['kind'] == 'clean' else 1
                    clearance.append(min(r['score']-score, r['margin']-margin))
                elif not truth and r['eligible']:
                    clearance.append(max(score-r['score'], margin-r['margin']))
            if false:
                continue
            key = (correct, min(clearance, default=0), -float(score+margin))
            if best is None or key > best[0]:
                best = (key, dict(score=round(float(score), 4), margin=round(float(margin), 4)))
    return best[1] if best else dict(score=1.01, margin=1.01)


def accept_rows(rows, thresholds):
    for r in rows:
        r['accepted'] = bool(r['eligible'] and r['score'] >= thresholds['score'] and r['margin'] >= thresholds['margin'])


def summarize(rows):
    result = {}
    for kind in ('clean', 'negative', 'transition', 'withheld', 'synthetic'):
        group = [r for r in rows if r['kind'] == kind]
        known = [r for r in group if r['expected']]
        accepted = [r for r in group if r['accepted']]
        correct = [r for r in accepted if r['expected'] is not None and r['predicted'] == r['expected']]
        result[kind] = dict(queries=len(group), known=len(known), accepted=len(accepted), correct=len(correct),
            false_accepts=len(accepted)-len(correct),
            precision=len(correct)/len(accepted) if accepted else None,
            coverage=len(correct)/len(known) if known else None,
            top1=sum(r['predicted']==r['expected'] for r in known)/len(known) if known else None,
            top5=sum(r['expected'] in r['top5'] for r in known)/len(known) if known else None)
    return result


def timed(lookup, images, repeats=12):
    for image in images[:3]:
        lookup.lookup(image)
    stages = {name: [] for name in ('encode', 'search', 'verify', 'total')}
    for repeat in range(repeats):
        # Alternate order to avoid consistently favoring one cached image.
        for im in images if repeat % 2 else images[::-1]:
            result = lookup.lookup(im)
            for key, value in result['timings_ms'].items():
                stages[key].append(value)
    return {k: metrics(v) for k, v in stages.items()}


def run(root, corpus, labels_path, out, *, phase='all', repeats=12, methods=METHODS, sizes=(128, 150)):
    root, out = Path(root), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    truth = read_json(labels_path)
    frozen_file = out / 'frozen.json'
    if phase in ('all', 'calibrate') and frozen_file.exists():
        raise ValueError('This output already has frozen thresholds; use --phase evaluate or a new output directory')
    if phase in ('all', 'calibrate'):
        frozen = dict(schema=1, label_sha256=sha256(Path(labels_path).read_bytes()),
            manifest_sha256=sha256((Path(corpus)/'manifest.json').read_bytes()),
            split=split_labels(truth['labels']), configurations={}, selected={})
        for mode in ('full', 'event'):
            catalog_path = root / 'catalog' / ('full.json' if mode == 'full' else 'dia_del_ritmo_26.json')
            catalog = read_json(catalog_path)
            calibration = [q for q in queries(corpus, truth, catalog) if q['phase']=='calibration']
            options = []
            for method in methods:
                for size in sizes:
                    name = f'{mode}-{method}-{size}'
                    index_dir = root / 'index' / name
                    if not (index_dir/'index.json').exists():
                        build_index(catalog_path, index_dir, method=method, size=size)
                    lk = Lookup(index_dir)
                    rows = [observe(lk, q) for q in calibration]
                    thresholds = fit_thresholds(rows)
                    accept_rows(rows, thresholds)
                    lk.thresholds = thresholds
                    stats = summarize(rows)
                    timings = timed(lk, [q['image'] for q in calibration if q['kind']=='clean'], repeats)
                    eligible = (stats['clean']['coverage'] or 0) >= .95 and all(
                        s['false_accepts']==0 for s in stats.values()) and timings['total']['p95'] < 50
                    config = dict(thresholds=thresholds, calibration=stats, timings=timings,
                                  index_sha256=sha256((index_dir/'index.json').read_bytes()),
                                  qualifies_on_calibration=eligible)
                    frozen['configurations'][name] = config
                    dump_json(out / f'{name}-thresholds.json', {**thresholds, 'index_sha256': config['index_sha256']})
                    dump_json(out / f'{name}-calibration.json', rows)
                    if eligible:
                        options.append((0 if method in ('classical', 'sift') else 1 if method=='mobilenet' else 2,
                            -(stats['synthetic']['coverage'] or 0), timings['total']['p95'], name))
                    print(json.dumps(dict(phase='calibration', config=name, thresholds=thresholds,
                        clean=stats['clean'], p95_ms=timings['total']['p95'])), flush=True)
                    del lk
                    gc.collect()
            frozen['selected'][mode] = min(options)[-1] if options else None
        dump_json(frozen_file, frozen)
        if phase == 'calibrate':
            return frozen
    frozen = read_json(frozen_file)
    if frozen['label_sha256'] != sha256(Path(labels_path).read_bytes()) or frozen['manifest_sha256'] != sha256((Path(corpus)/'manifest.json').read_bytes()):
        raise ValueError('Ground truth or corpus changed after thresholds were frozen')
    report = dict(machine=dict(platform=platform.platform(), processor=platform.processor(),
        python=platform.python_version(), opencv=cv2.__version__, numpy=np.__version__,
        cpu_only=True, threads=1), frozen_sha256=sha256(frozen_file.read_bytes()),
        selected_before_evaluation=frozen['selected'], results={})
    for name, config in frozen['configurations'].items():
        index_dir = root / 'index' / name
        if config['index_sha256'] != sha256((index_dir/'index.json').read_bytes()):
            raise ValueError('Index changed after calibration')
        before = memory_bytes()
        lk = Lookup(index_dir, thresholds=config['thresholds'])
        after = memory_bytes()
        evaluation = [q for q in queries(corpus, truth, lk.catalog) if q['phase']=='evaluation']
        rows = [observe(lk, q) for q in evaluation]
        timings = timed(lk, [q['image'] for q in evaluation if q['kind']=='clean'], repeats)
        result = dict(summary=summarize(rows), timings_ms=timings, cold_seconds=lk.cold_seconds,
            loaded_rss_bytes=after, rss_increment_bytes=max(0, after-before),
            array_bytes=lk.vectors.nbytes+lk.images.nbytes,
            index_bytes=sum(p.stat().st_size for p in index_dir.iterdir()),
            index_build_seconds=lk.meta['build_seconds'], indexed_artworks=len(lk.entries),
            skipped_banners=len(lk.meta['skipped']))
        report['results'][name] = result
        dump_json(out / f'{name}-evaluation.json', rows)
        print(json.dumps(dict(phase='evaluation', config=name, clean=result['summary']['clean'],
            false_accepts=sum(s['false_accepts'] for s in result['summary'].values()),
            p95_ms=timings['total']['p95'])), flush=True)
        del lk
        gc.collect()
    dump_json(out / 'results.json', report)
    return report
