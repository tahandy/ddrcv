"""Compare portable catalogs with folder bundles and transfer one file offline.

Run from the checkout after the original integration artifacts are available:
    python -m experiments.jacket_lookup.catalog_container_validation
"""
import os
for variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[variable] = '1'

from collections import Counter
import gc
from pathlib import Path
import shutil
import tempfile
import time
from unittest.mock import patch

from ddrcv.jacket_lookup import assets, catalog
from ddrcv.jacket_lookup.config import validate_config
from ddrcv.jacket_lookup.images import read_image
from .benchmark import queries, metrics, memory_bytes

ROOT = Path('experiments/jacket_lookup/artifacts')
OUT = ROOT/'integration'
LEGACY = OUT/'assets'


def stable(value):
    if isinstance(value, dict):
        return {k: stable(v) for k, v in value.items() if k not in ('timings_ms', 'elapsed_ms')}
    if isinstance(value, list):
        return [stable(v) for v in value]
    return value


def main():
    report = dict(catalogs={}, differences=[])
    truth = catalog.read_json('experiments/jacket_lookup/ground_truth.json')
    for mode, name in (('event', 'dia_del_ritmo_26'), ('full', 'full-world')):
        path = OUT/(name+'.ddrcatalog')
        cfg = validate_config(dict(mode=mode, assets_dir=str(LEGACY)))
        packed_cfg = {**cfg, 'catalog_file': str(path)}
        result = assets.pack(packed_cfg)
        assert result['ok'], result
        load_ms = dict(folder=[], container=[])
        memories = dict(folder=[], container=[])
        for iteration in range(3):
            for format in (('folder', 'container') if iteration % 2 == 0 else ('container', 'folder')):
                gc.collect(); start_memory = memory_bytes(); began = time.perf_counter()
                lookup = assets.load(cfg if format == 'folder' else packed_cfg)
                load_ms[format].append((time.perf_counter()-began)*1000)
                memories[format].append(memory_bytes()-start_memory)
                del lookup
        before, after = assets.load(cfg), assets.load(packed_cfg)
        before_worker, after_worker = assets.processor(cfg, lookup=before), assets.processor(packed_cfg, lookup=after)
        kinds, rows, splash = Counter(), [], 0
        warm = dict(folder=[], container=[])
        try:
            for index, query in enumerate(queries(ROOT/'corpus', truth, before.catalog)):
                arguments = dict(exclude_song_ids=query['exclude'])
                values = {}
                for label in (('folder', 'container') if index % 2 == 0 else ('container', 'folder')):
                    lookup = before if label == 'folder' else after
                    values[label] = lookup.lookup(query['image'], **arguments)
                kinds[query['kind']] += 1
                if stable(values['folder']) != stable(values['container']):
                    report['differences'].append([mode, query['id'], 'jacket'])
                rows.append(dict(id=query['id'], kind=query['kind'], result=stable(values['container'])))
                if query['kind'] in ('clean', 'transition', 'negative'):
                    a, b = before_worker.analyze(query['frame']), after_worker.analyze(query['frame'])
                    splash += 1
                    if stable(a) != stable(b):
                        report['differences'].append([mode, query['id'], 'splash'])
                if query['kind'] == 'clean':
                    # Both loaded objects have now seen this frame; pair warm complete parsing.
                    for repeat in range(5):
                        for label in (('folder', 'container') if repeat % 2 == 0 else ('container', 'folder')):
                            worker = before_worker if label == 'folder' else after_worker
                            began = time.perf_counter(); worker.analyze(query['frame'])
                            warm[label].append((time.perf_counter()-began)*1000)
        finally:
            before_worker.close(); after_worker.close()
        report['catalogs'][mode] = dict(file=str(path), bytes=path.stat().st_size,
            gallery_images=len(after.entries), jacket_queries=dict(kinds), splash_comparisons=splash,
            load_ms={k: metrics(v) for k, v in load_ms.items()},
            loaded_memory_delta_bytes={k: metrics(v) for k, v in memories.items()},
            warm_template_splash_ms={k: metrics(v) for k, v in warm.items()})
        catalog.dump_json(OUT/('container-'+mode+'-queries.json'), rows)
        del before, after, before_worker, after_worker
    # Copy only the event file. Deny source access and all network connections.
    frame = read_image(ROOT/'corpus/frames/2025-03-27_15-50-18_00.png')
    with tempfile.TemporaryDirectory(prefix='ddrcv catalog receiver ') as tmp:
        copied = Path(tmp)/'shared catalog.ddrcatalog'
        shutil.copyfile(OUT/'dia_del_ritmo_26.ddrcatalog', copied)
        real_open = Path.open
        def guard(path, *args, **kwargs):
            if path.resolve().is_relative_to(OUT.resolve()):
                raise AssertionError('Accessed original catalog')
            return real_open(path, *args, **kwargs)
        with patch.object(Path, 'open', guard), patch('socket.socket.connect', side_effect=AssertionError('Network')):
            cfg = dict(catalog_file=str(copied), assets_dir=str(Path(tmp)/'absent cache'))
            loaded = assets.load(cfg)
            worker = assets.processor(cfg, lookup=loaded)
            try:
                result = worker.analyze(frame)
            finally:
                worker.close()
            assert result['accepted'] and result['players']['p2']['max_ex'] == 1881, result
            assert list(Path(tmp).iterdir()) == [copied]
        report['transfer'] = dict(ok=True, files_copied=1, extracted=False, source_access=False,
                                  network_access=False, max_ex=result['players']['p2']['max_ex'])
    report['ok'] = not report['differences']
    catalog.dump_json(OUT/'catalog-container.json', report)
    print(report, flush=True)
    assert report['ok'], report['differences']


if __name__ == '__main__':
    main()
