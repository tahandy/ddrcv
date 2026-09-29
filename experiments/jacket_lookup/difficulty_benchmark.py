"""Frozen template experiment, disjoint source songs, OCR comparison and timings."""
from __future__ import annotations

from pathlib import Path
import time

import cv2
import numpy as np

from .benchmark import fit_thresholds, metrics, split_labels
from .catalog import dump_json, read_json, resolve_chart, sha256
from .corpus import crop, DIFFICULTY_ROIS, read_image, write_image
from .difficulty import build_bank, DifficultyTemplates
from .lookup import Lookup, lookup_splash, parse_difficulty


def perturbations(image):
    encoded = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 35])[1]
    yield 'jpeg35', cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    yield 'blur', cv2.GaussianBlur(image, (3, 3), .8)
    yield 'color', np.clip(image.astype(float)*[.85, .95, 1.05]+5, 0, 255).astype(np.uint8)
    yield 'dim', np.clip(image.astype(float)*.7, 0, 255).astype(np.uint8)
    yield 'offset', cv2.warpAffine(image, np.float32([[1, 0, 2], [0, 1, -1]]), image.shape[1::-1])
    yield 'resample', cv2.resize(cv2.resize(image, None, fx=.75, fy=.75), image.shape[1::-1])


def queries(corpus, truth, phases):
    corpus = Path(corpus)
    for row in read_json(corpus/'manifest.json')['samples']:
        if row['kind'] not in ('clean', 'negative'):
            continue
        label = truth.get(row['id'])
        phase = phases[label['song_id']] if label else ('calibration' if int(sha256(row['video'].encode())[:8], 16)%2 else 'evaluation')
        frame = read_image(corpus/row['image'])
        for p, roi in enumerate(DIFFICULTY_ROIS, 1):
            expected = label['players'][f'p{p}']['difficulty'] if label else None
            base = dict(id=f"{row['id']}_p{p}", parent=row['id'], phase=phase,
                kind=row['kind'], expected=expected, group=label['song_id'] if label else row['video'],
                image=crop(frame, roi), exclude=())
            yield base
            if label and phase != 'template_source':
                yield {**base, 'id':base['id']+'_withheld', 'kind':'withheld', 'expected':None, 'exclude':(expected,)}
                for variant, image in perturbations(base['image']):
                    yield {**base, 'id':base['id']+'_'+variant, 'kind':'synthetic', 'variant':variant, 'image':image}


def observe(reader, q):
    result = reader.recognize(q['image'], exclude=q['exclude'])
    best = result['candidates'][0] if result['candidates'] else None
    return dict(**{k: q.get(k) for k in ('id', 'parent', 'phase', 'kind', 'variant', 'expected', 'group')},
        predicted=best['difficulty'] if best else None, score=best['score'] if best else -1,
        margin=result['margin'], eligible=result['reason'] not in ('no_text', 'no_candidates'),
        accepted=result['accepted'], reason=result['reason'], elapsed_ms=result['elapsed_ms'])


def summarize(rows):
    result = {}
    for kind in sorted({r['kind'] for r in rows}):
        group = [r for r in rows if r['kind'] == kind]
        positive = [r for r in group if r['expected']]
        accepted = [r for r in group if r['accepted']]
        correct = sum(r['expected'] is not None and r['predicted'] == r['expected'] for r in accepted)
        result[kind] = dict(queries=len(group), positive=len(positive), accepted=len(accepted), correct=correct,
            false_accepts=len(accepted)-correct, coverage=correct/len(positive) if positive else None,
            precision=correct/len(accepted) if accepted else None,
            top1=sum(r['predicted']==r['expected'] for r in positive)/len(positive) if positive else None)
    return result


def transition_evidence(reader, corpus, truth, phases):
    """Reviewed TBD5 entries fade the same label in; all reviewed exits lack text."""
    corpus = Path(corpus)
    evidence = []
    for row in read_json(corpus/'manifest.json')['samples']:
        if row['kind'] != 'transition':
            continue
        label = truth[row['parent']]
        frame = read_image(corpus/row['image'])
        for p, roi in enumerate(DIFFICULTY_ROIS, 1):
            q = dict(id=f"{row['id']}_p{p}", parent=row['parent'], phase=phases[label['song_id']],
                kind='fading_entry' if row['id'].endswith('_entry') else 'empty_exit',
                expected=label['players'][f'p{p}']['difficulty'] if row['id'].endswith('_entry') else None,
                group=label['song_id'], image=crop(frame, roi), exclude=())
            evidence.append(observe(reader, q))
    return dict(annotation='Visually reviewed all 44 ROIs. Entry labels fade in; exits have no readable label. Same-event stress cases, not independent songs.',
        evaluation=summarize([r for r in evidence if r['phase']=='evaluation']),
        all_phases=summarize(evidence), rows=evidence)


def calibrate(corpus, labels_path, out):
    out = Path(out)
    bank = build_bank(corpus, labels_path, out)
    truth = read_json(labels_path)['labels']
    phases = split_labels(truth)
    for entry in bank['entries']:
        phases[entry['song_id']] = 'template_source'
    reader = DifficultyTemplates(out)
    rows = [observe(reader, q) for q in queries(corpus, truth, phases) if q['phase'] == 'calibration']
    bank['thresholds'] = fit_thresholds(rows)
    bank['phases'] = phases
    bank['manifest_sha256'] = sha256((Path(corpus)/'manifest.json').read_bytes())
    # Bind every input image as well as its metadata, including evaluation images.
    bank['frame_hashes'] = {r['image']:sha256((Path(corpus)/r['image']).read_bytes())
        for r in read_json(Path(corpus)/'manifest.json')['samples']}
    dump_json(out/'bank.json', bank)
    dump_json(out/'frozen.json', dict(bank_sha256=sha256((out/'bank.json').read_bytes()),
        thresholds=bank['thresholds'], phases=phases))
    for row in rows:
        row['accepted'] = row['eligible'] and row['score'] >= bank['thresholds']['score'] and row['margin'] >= bank['thresholds']['margin']
    dump_json(out/'calibration.json', dict(summary=summarize(rows), rows=rows))
    print(f"Frozen difficulty templates: {bank['thresholds']}", flush=True)


def evaluate(root, corpus, labels_path, out, repeats):
    from ddrcv.ocr.rapid import RapidOCRRecognizer
    root, corpus, out = Path(root), Path(corpus), Path(out)
    frozen = read_json(out/'frozen.json')
    if sha256((out/'bank.json').read_bytes()) != frozen['bank_sha256']:
        raise ValueError('Frozen difficulty bank changed')
    reader = DifficultyTemplates(out)
    if reader.meta['labels_sha256'] != sha256(Path(labels_path).read_bytes()) or reader.meta['manifest_sha256'] != sha256((corpus/'manifest.json').read_bytes()):
        raise ValueError('Frozen evaluation inputs changed')
    for name, digest in reader.meta['frame_hashes'].items():
        if sha256((corpus/name).read_bytes()) != digest:
            raise ValueError('Frozen evaluation frame changed')
    truth = read_json(labels_path)['labels']
    all_queries = list(queries(corpus, truth, frozen['phases']))
    rows = [observe(reader, q) for q in all_queries if q['phase'] == 'evaluation']
    sources = [observe(reader, q) for q in all_queries if q['phase'] == 'template_source']
    cold = time.perf_counter()
    ocr = RapidOCRRecognizer(allow_download=False, num_threads=1)
    ocr.warmup()
    ocr_cold = time.perf_counter()-cold
    ocr_rows = []
    for q in all_queries:
        if q['phase'] != 'evaluation' or q['kind'] == 'withheld':
            continue
        reading = ocr.recognize_many([q['image']], color_order='bgr')[0]
        parsed = parse_difficulty(reading.text, reading.confidence)
        ocr_rows.append(dict(**{k:q.get(k) for k in ('id','kind','expected','variant')},
            accepted=parsed is not None, predicted=parsed['difficulty'] if parsed else None,
            text=reading.text, score=reading.confidence))
    report = dict(schema=1, method='WORLD difficulty label templates; no digit recognition',
        thresholds=frozen['thresholds'], bank_sha256=frozen['bank_sha256'], phases=frozen['phases'],
        template_cold_seconds=reader.cold_seconds, ocr_cold_seconds=ocr_cold,
        template_bytes=sum((out/e['image']).stat().st_size for e in reader.meta['entries']),
        timing_protocol='CPU, one OpenCV/BLAS/ORT thread, warm, interleaved methods, alternating order',
        independent_evaluation_songs=len({r['group'] for r in rows if r['kind']=='clean'}),
        template=summarize(rows), ocr=summarize(ocr_rows), rows=rows, ocr_rows=ocr_rows,
        template_source_checks=summarize(sources), modes={})
    report['transitions'] = transition_evidence(reader, corpus, truth, frozen['phases'])
    jacket_frozen = read_json(root/'benchmark/frozen.json')
    clean = [r for r in read_json(corpus/'manifest.json')['samples'] if r['kind']=='clean']
    for mode, selected in jacket_frozen['selected'].items():
        lookup = Lookup(root/'index'/selected, thresholds=jacket_frozen['configurations'][selected]['thresholds'])
        frames = [(row, read_image(corpus/row['image'])) for row in clean]
        mode_report = {}
        for method in ('template', 'ocr'):
            kwargs = dict(difficulty_reader=reader) if method == 'template' else dict(recognizer=ocr)
            evidence = []
            for row, frame in frames:
                result = lookup_splash(lookup, frame, **kwargs)
                checks = {}
                for player, label in truth[row['id']]['players'].items():
                    actual = result['players'].get(player, {})
                    chart = resolve_chart(lookup.catalog, truth[row['id']]['song_id'], 'single', label['difficulty'])
                    checks[player] = dict(expected_difficulty=label['difficulty'], expected_max_ex=chart['max_ex'],
                        difficulty_correct=actual.get('difficulty')==label['difficulty'],
                        complete_correct=actual.get('difficulty')==label['difficulty'] and actual.get('max_ex')==chart['max_ex'],
                        false_max_ex=actual.get('max_ex') is not None and actual.get('max_ex')!=chart['max_ex'])
                evidence.append(dict(id=row['id'], phase=frozen['phases'][truth[row['id']]['song_id']], checks=checks, result=result))
            checks = [c for row in evidence for c in row['checks'].values()]
            held = [c for row in evidence if row['phase']=='evaluation' for c in row['checks'].values()]
            mode_report[method] = dict(total_ms=None, difficulty_ms=None,
                all_player_checks=len(checks), all_difficulties_correct=sum(c['difficulty_correct'] for c in checks),
                all_complete_correct=sum(c['complete_correct'] for c in checks), false_max_ex=sum(c['false_max_ex'] for c in checks),
                evaluation_player_checks=len(held), evaluation_complete_correct=sum(c['complete_correct'] for c in held), evidence=evidence)
        # Interleave methods on identical frames, alternating order, to reduce
        # warmup, CPU-frequency and background-load bias between timed blocks.
        samples = {method:dict(total=[], difficulty=[]) for method in mode_report}
        for repeat in range(repeats):
            for row, frame in frames if repeat%2 else frames[::-1]:
                for method in (('template','ocr') if repeat%2 else ('ocr','template')):
                    kwargs = dict(difficulty_reader=reader) if method == 'template' else dict(recognizer=ocr)
                    result = lookup_splash(lookup, frame, **kwargs)
                    samples[method]['total'].append(result['timings_ms']['splash_total'])
                    samples[method]['difficulty'].append(result['timings_ms']['difficulty'])
        for method, sample in samples.items():
            mode_report[method]['total_ms'] = metrics(sample['total'])
            mode_report[method]['difficulty_ms'] = metrics(sample['difficulty'])
            print(f"{mode} {method}: splash p95={metrics(sample['total'])['p95']:.2f} ms; difficulty p95={metrics(sample['difficulty'])['p95']:.2f} ms", flush=True)
        report['modes'][mode] = mode_report
    dump_json(out/'results.json', report)
    examples = [q for q in all_queries if q['phase']=='evaluation' and q['kind'] in ('clean','negative')][:16]
    examples += [q for q in all_queries if q['phase']=='evaluation' and q.get('variant')=='dim'][:4]
    sheet = np.full((len(examples)*55, 900, 3), 30, np.uint8)
    for i, q in enumerate(examples):
        im = q['image']; h,w = im.shape[:2]
        sheet[i*55:i*55+h, :w] = im
        observed = observe(reader, q)
        text = f"{q['id']} => {observed['predicted']} / {observed['reason']} ({observed['score']:.2f})"
        cv2.putText(sheet, text, (230, i*55+22), cv2.FONT_HERSHEY_SIMPLEX, .37, (240,240,240), 1)
    write_image(out/'examples.jpg', sheet)
    concise = {k:v for k,v in report.items() if k not in ('rows','ocr_rows','modes')}
    concise['transitions'] = {k:v for k,v in report['transitions'].items() if k != 'rows'}
    concise['modes'] = {mode:{method:{k:v for k,v in result.items() if k!='evidence'} for method,result in methods.items()} for mode,methods in report['modes'].items()}
    dump_json(out/'summary.json', concise)
    return report


def run(root, corpus, labels_path, out, *, phase='all', repeats=12):
    cv2.setNumThreads(1)
    if phase in ('calibrate', 'all'):
        calibrate(corpus, labels_path, out)
    if phase in ('evaluate', 'all'):
        return evaluate(root, corpus, labels_path, out, repeats)
