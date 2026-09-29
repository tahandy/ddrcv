"""Interleaved offline profiling of name workers, difficulty and CPU scheduling."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import itertools
import os
from pathlib import Path
import platform
import time

for _key in ('OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'OMP_NUM_THREADS'):
    os.environ[_key] = '1'

import cv2

from ddrcv.ocr.rapid import RapidOCRRecognizer, prepare_ddr_crop, MODEL_SHA256
from ddrcv.state.player_names import PlayerNameReader, validate_config, NAME_BOXES
from .benchmark import metrics, memory_bytes
from .catalog import read_json, dump_json, sha256
from .corpus import read_image, crop
from .difficulty import DifficultyTemplates
from .execution import run_with_qos
from .lookup import Lookup, lookup_splash
from .names import PerPlayerNameReader
from .performance import Parity
from .threaded import ThreadedSplashLookup


class _TimedCall:
    """Local instrumentation only; delegates the exact installed implementation."""
    def __init__(self, target):
        self.target, self.elapsed = target, 0

    def __getattr__(self, key):
        return getattr(self.target, key)

    def __call__(self, *args, **kwargs):
        start = time.perf_counter()
        try:
            return self.target(*args, **kwargs)
        finally:
            self.elapsed += (time.perf_counter()-start)*1000


class ProfiledNameReader(PlayerNameReader):
    def warmup(self):
        super().warmup()
        if hasattr(self, 'probes'):
            return
        self.probes = {}
        for key in ('session', 'resize_norm_img', 'postprocess_op'):
            probe = _TimedCall(getattr(self.ocr._engine, key))
            setattr(self.ocr._engine, key, probe)
            self.probes[key] = probe

    def read(self, crops):
        # Same operations and validation as PlayerNameReader.read; parity is
        # checked against that uninstrumented implementation before timing.
        for probe in self.probes.values():
            probe.elapsed = 0
        start = time.perf_counter()
        prepared = [prepare_ddr_crop(image) for image in crops.values()]
        preparation = (time.perf_counter()-start)*1000
        readings = self.ocr.recognize_many(prepared)
        values = {key:self._name(r) for key, r in zip(crops, readings)}
        self.last = dict(prepare_ms=preparation,
                        inference_ms=self.probes['session'].elapsed,
                        normalize_ms=self.probes['resize_norm_img'].elapsed,
                        decode_ms=self.probes['postprocess_op'].elapsed,
                        total_ms=(time.perf_counter()-start)*1000,
                        raw={str(k):dict(text=r.text, confidence=r.confidence)
                             for k, r in zip(crops, readings)})
        return values


def config(threads):
    return validate_config(dict(ocr=dict(allow_download=False, num_threads=threads)))


def name_parts(reader):
    return [r.last for r in reader.readers] if isinstance(reader, PerPlayerNameReader) else [reader.last]


def read_names(reader, crops, high_qos, started):
    values = run_with_qos(high_qos, reader.read, crops)
    return dict(values={str(k):v for k, v in values.items()},
                ready_ms=(time.perf_counter()-started)*1000,
                parts=name_parts(reader))


def summarize(samples):
    keys = ('all_ready_ms', 'names_ready_ms', 'chart_ready_ms', 'cpu_ms',
            'name_prepare_ms', 'name_inference_ms', 'name_normalize_ms',
            'name_decode_ms', 'difficulty_ms', 'jacket_ms')
    return {key:metrics([row[key] for row in samples]) for key in keys}


def run(root, out, rounds, repeats):
    out.mkdir(parents=True, exist_ok=True)
    frozen = read_json(root/'benchmark/frozen.json')
    frames = [(row, read_image(root/'corpus'/row['image']))
              for row in read_json(root/'corpus/manifest.json')['samples']]
    clean = [(row, im) for row, im in frames if row['kind'] == 'clean']
    templates = DifficultyTemplates(root/'difficulty-template')
    readers = {f'batch{n}':ProfiledNameReader(config(n)) for n in (1, 2)}
    readers.update({f'per_player{n}':PerPlayerNameReader(config(n), reader_factory=ProfiledNameReader, high_qos=False)
                    for n in (1, 2)})
    processors = []
    ocr = RapidOCRRecognizer(allow_download=False, num_threads=1)
    ocr.warmup()
    baseline_names = PlayerNameReader(config(1)); baseline_names.warmup()
    parity, reference, samples, chart_reference = Parity(), {}, [], {}
    configurations = list(itertools.product(readers, (False, True), ('template', 'ocr')))
    try:
        for reader in readers.values(): reader.warmup()
        # Include degraded crops and negatives in behavior checks, independently
        # of whether the splash detector would send them to the live name reader.
        for row, frame in frames:
            crops = {i:crop(frame, box) for i, box in enumerate(NAME_BOXES)}
            expected = {str(k):v for k, v in baseline_names.read(crops).items()}
            reference[row['id']] = expected
            for mode, reader in readers.items():
                actual = {str(k):v for k, v in reader.read(crops).items()}
                parity.check('names_'+mode, row['id'], expected, actual)
        print('Name parity complete on 54 real frames', flush=True)
        with ThreadPoolExecutor(1, thread_name_prefix='profile-name-dispatch') as pool:
            for catalog in ('event', 'full'):
                selected = frozen['selected'][catalog]
                lookup = Lookup(root/'index'/selected,
                                thresholds=frozen['configurations'][selected]['thresholds'])
                processor = ThreadedSplashLookup(lookup, recognizer=ocr, high_qos=False)
                processors.append(processor)
                for row, frame in frames:
                    for difficulty in ('template', 'ocr'):
                        processor.difficulty_reader = templates if difficulty == 'template' else None
                        expected = lookup_splash(lookup, frame, recognizer=ocr,
                                                 difficulty_reader=processor.difficulty_reader)
                        chart_reference[catalog, row['id'], difficulty] = expected
                        for qos in (False, True):
                            processor.high_qos = qos
                            actual = processor.analyze(frame)
                            parity.check(f'chart_{catalog}_{difficulty}_{qos}', row['id'], expected, actual)
                for batch in range(rounds):
                    for repeat in range(repeats):
                        ordered_frames = clean if (batch+repeat)%2 else clean[::-1]
                        for number, (row, frame) in enumerate(ordered_frames):
                            crops = {i:crop(frame, box) for i, box in enumerate(NAME_BOXES)}
                            offset = (batch*repeats*len(clean)+repeat*len(clean)+number)%len(configurations)
                            order = configurations[offset:]+configurations[:offset]
                            if (batch+repeat+number)%2: order = order[::-1]
                            for name_mode, high_qos, difficulty in order:
                                reader = readers[name_mode]
                                if isinstance(reader, PerPlayerNameReader): reader.high_qos = high_qos
                                processor.high_qos = high_qos
                                processor.difficulty_reader = templates if difficulty == 'template' else None
                                cpu = time.process_time()
                                start = time.perf_counter()
                                future = pool.submit(read_names, reader, crops, high_qos, start)
                                try:
                                    chart = processor.analyze(frame)
                                    chart_ready = (time.perf_counter()-start)*1000
                                finally:
                                    names = future.result()
                                all_ready = (time.perf_counter()-start)*1000
                                cpu = (time.process_time()-cpu)*1000
                                parity.check('timed_names', row['id'], reference[row['id']], names['values'], record=False)
                                parity.check('timed_chart', row['id'], chart_reference[catalog, row['id'], difficulty], chart, record=False)
                                # Per-player wall stages overlap; report the sum
                                # of each stage's worker durations explicitly.
                                stages = chart['timings_ms']
                                samples.append(dict(catalog=catalog, name_mode=name_mode,
                                    high_qos=high_qos, difficulty=difficulty, round=batch,
                                    repeat=repeat, id=row['id'], all_ready_ms=all_ready,
                                    chart_ready_ms=chart_ready, names_ready_ms=names['ready_ms'], cpu_ms=cpu,
                                    name_prepare_ms=sum(p['prepare_ms'] for p in names['parts']),
                                    name_inference_ms=sum(p['inference_ms'] for p in names['parts']),
                                    name_normalize_ms=sum(p['normalize_ms'] for p in names['parts']),
                                    name_decode_ms=sum(p['decode_ms'] for p in names['parts']),
                                    difficulty_ms=stages['difficulty'], jacket_ms=stages['total'],
                                    names=names, chart_stages=stages))
                    print(f'{catalog}: interleaved round {batch+1}/{rounds}', flush=True)
                processor.close()
    finally:
        for processor in processors: processor.close()
        for reader in readers.values():
            if isinstance(reader, PerPlayerNameReader): reader.close()
    summaries = {}
    for catalog in ('event', 'full'):
        summaries[catalog] = {}
        for name_mode, qos, difficulty in configurations:
            selected = [r for r in samples if (r['catalog'],r['name_mode'],r['high_qos'],r['difficulty']) == (catalog,name_mode,qos,difficulty)]
            key = f'{name_mode}_{"high" if qos else "system"}_{difficulty}'
            summaries[catalog][key] = dict(summary=summarize(selected),
                rounds=[summarize([r for r in selected if r['round'] == i]) for i in range(rounds)])
    result = dict(schema=1, rounds=rounds, repeats=repeats, platform=platform.platform(),
                  protocol='CPU only; OpenCV/BLAS=1; difficulty ORT=1; name ORT=1 or 2; all configurations interleaved on each frame; warmed models; QoS applied to all branch callers and restored; no affinity/priority changes',
                  configurations=configurations, summaries=summaries,
                  parity=dict(counts=parity.counts,max_float_difference=parity.max_float_difference),
                  samples=samples, model_sha256=MODEL_SHA256,
                  hashes={str(p):sha256(p.read_bytes()) for p in (
                      root/'benchmark/frozen.json',root/'difficulty-template/bank.json',
                      Path(__file__),Path(__file__).with_name('names.py'),
                      Path(__file__).with_name('threaded.py'),Path(__file__).with_name('execution.py'))})
    dump_json(out/'results.json',result)
    dump_json(out/'summary.json',{k:v for k,v in result.items() if k!='samples'})
    dump_json(out/'parity.json',parity.records)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path('experiments/jacket_lookup/artifacts'))
    p.add_argument('--out',type=Path,default=Path('experiments/jacket_lookup/artifacts/name-profiling'))
    p.add_argument('--rounds',type=int,default=3)
    p.add_argument('--repeats',type=int,default=3)
    args = p.parse_args()
    if args.rounds < 1 or args.repeats < 1: p.error('rounds/repeats must be positive')
    cv2.setNumThreads(1)
    run(args.root,args.out,args.rounds,args.repeats)


if __name__ == '__main__': main()
