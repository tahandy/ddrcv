"""End-to-end chart checks, independent process profiles, and readable reports."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time

from .catalog import dump_json, read_json, resolve_chart, sha256


def splash_evidence(root, corpus, truth_path, out, repeats=6):
    from ddrcv.ocr.rapid import RapidOCRRecognizer
    from .benchmark import metrics, split_labels
    from .corpus import read_image
    from .lookup import Lookup, lookup_splash
    root, corpus, out = Path(root), Path(corpus), Path(out)
    frozen = read_json(out / 'frozen.json')
    truth = read_json(truth_path)['labels']
    split = split_labels(truth)
    rows = [r for r in read_json(corpus/'manifest.json')['samples'] if r['kind']=='clean']
    started = time.perf_counter()
    ocr = RapidOCRRecognizer(allow_download=False, num_threads=1)
    ocr.warmup()
    report = dict(ocr_cold_seconds=time.perf_counter()-started, modes={})
    for mode, selected in frozen['selected'].items():
        if not selected:
            continue
        lookup = Lookup(root/'index'/selected, thresholds=frozen['configurations'][selected]['thresholds'])
        evidence = []
        all_timings, ocr_timings = [], []
        for row in rows:
            frame = read_image(corpus/row['image'])
            expected = truth[row['id']]
            # Untimed first call warms the OCR batch shape and its buffers.
            result = lookup_splash(lookup, frame, recognizer=ocr)
            for _ in range(repeats):
                result = lookup_splash(lookup, frame, recognizer=ocr)
                all_timings.append(result['timings_ms']['splash_total'])
                ocr_timings.append(result['timings_ms']['ocr'])
            checks = {}
            for player, label in expected['players'].items():
                actual = result['players'].get(player, {})
                chart = resolve_chart(lookup.catalog, expected['song_id'], 'single', label['difficulty'], label['level'])
                checks[player] = dict(expected=label, expected_max_ex=chart['max_ex'],
                    expected_status=chart['status'],
                    chart_read_correct=all(actual.get(k)==v for k,v in label.items()),
                    emitted_wrong_max_ex=actual.get('max_ex') is not None and actual.get('max_ex') != chart['max_ex'],
                    complete_correct=(actual.get('max_ex')==chart['max_ex'] and all(actual.get(k)==v for k,v in label.items())))
            evidence.append(dict(id=row['id'], phase=split[expected['song_id']], expected=expected,
                                 checks=checks, result=result))
        checks = [c for e in evidence for c in e['checks'].values()]
        report['modes'][mode] = dict(selected=selected, timings_ms=metrics(all_timings),
            ocr_ms=metrics(ocr_timings), players=len(checks), chart_reads_correct=sum(c['chart_read_correct'] for c in checks),
            complete_correct=sum(c['complete_correct'] for c in checks),
            eligible_chart_observations=sum(c['expected_max_ex'] is not None for c in checks),
            wrong_emitted_max_ex=sum(c['emitted_wrong_max_ex'] for c in checks), evidence=evidence)
    dump_json(out/'splash-results.json', report)
    return report


def profile_worker(root, corpus, out, name, repeats):
    from .benchmark import memory_bytes, timed
    from .corpus import crop, read_image
    from .lookup import Lookup
    root, corpus, out = Path(root), Path(corpus), Path(out)
    frozen = read_json(out/'frozen.json')
    start = time.perf_counter()
    lookup = Lookup(root/'index'/name, thresholds=frozen['configurations'][name]['thresholds'])
    init = time.perf_counter()-start
    resident = memory_bytes()
    images = [crop(read_image(corpus/r['image'])) for r in read_json(corpus/'manifest.json')['samples'] if r['kind']=='clean']
    return dict(name=name, index_init_seconds=init, loaded_process_rss_bytes=resident,
                timings_ms=timed(lookup, images, repeats))


def profiles(root, corpus, out, repeats=20):
    out = Path(out)
    frozen = read_json(out/'frozen.json')
    results = {}
    for name in frozen['configurations']:
        began = time.perf_counter()
        raw = subprocess.check_output([sys.executable, '-B', '-m', 'experiments.jacket_lookup',
            'profile-worker', '--root', str(root), '--corpus', str(corpus), '--out', str(out),
            '--name', name, '--repeats', str(repeats)], text=True)
        results[name] = json.loads(raw)
        results[name]['subprocess_wall_seconds_including_queries'] = time.perf_counter()-began
        print(f"Profiled {name}: p95 {results[name]['timings_ms']['total']['p95']:.2f} ms", flush=True)
        dump_json(out/'fresh-process-profiles.json', results)
    return results


def render(root, corpus, out):
    from .corpus import read_image, crop, write_image
    import cv2
    import numpy as np
    root, corpus, out = Path(root), Path(corpus), Path(out)
    frozen = read_json(out/'frozen.json')
    result = read_json(out/'results.json')
    profiles = read_json(out/'fresh-process-profiles.json')
    splash = read_json(out/'splash-results.json')
    lines = ['# CPU jacket lookup benchmark', '',
        'CPU-only, one inference/OpenCV/BLAS thread. Configurations were chosen on five calibration songs before six held-out songs were evaluated.', '',
        '| Index / method / size | Held-out known accepted | False accepts: real / synthetic | Warm p50 / p95 / p99 ms | Fresh process RSS MiB |',
        '|---|---:|---:|---:|---:|']
    for name, res in result['results'].items():
        s = res['summary']; t = profiles[name]['timings_ms']['total']
        real_false = sum(s[k]['false_accepts'] for k in ('clean','negative','transition','withheld'))
        lines.append(f"| {name} | {s['clean']['correct']}/{s['clean']['known']} | {real_false} / {s['synthetic']['false_accepts']} | "
            f"{t['median']:.2f} / {t['p95']:.2f} / {t['p99']:.2f} | {profiles[name]['loaded_process_rss_bytes']/2**20:.1f} |")
    lines.extend(['', '## Complete splash lookup', ''])
    for mode, data in splash['modes'].items():
        lines.append(f"- {mode}: {data['chart_reads_correct']}/{data['players']} chart labels read correctly; "
            f"{data['wrong_emitted_max_ex']} incorrect max EX values emitted. "
            f"{data['eligible_chart_observations']} eligible player-chart observations. "
            f"Warm total p50/p95/p99: {data['timings_ms']['median']:.2f}/{data['timings_ms']['p95']:.2f}/{data['timings_ms']['p99']:.2f} ms.")
    lines.extend(['', '## Limits', '',
        '- Eleven distinct songs are a small, single-capture-domain sample; six are held out. No population-level precision claim is supported.',
        '- Only three recorded songs belong to the Dia Del Ritmo catalog, and only one recorded player chart is eligible. The held-out event split contains one known song and no eligible max-EX chart.',
        '- Synthetic degradation, repeated timing calls, entry/exit frames and withholding tests are correlated with their parent songs. They are not additional independent songs.',
        '- Thresholds are empirical similarity/margin cutoffs, not calibrated probabilities. Test results were not used to retune them.',
        '- Historical non-square banners are inventoried but excluded from the square-jacket index. Album art shared by multiple identities is rejected.',
        '- Max EX correctness means agreement with the pinned upstream chart metadata, not an independent note-count audit.',
        '- Fresh-process RSS includes Python and imported libraries. Index initialization excludes interpreter startup; subprocess wall time also includes all timed queries.',
        '', 'Raw results, per-query records, frozen thresholds, split IDs, and profiles are adjacent to this report.'])
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    # Small review sheet: each selected method on every observed clean splash.
    from PIL import Image, ImageDraw, ImageFont
    font_path = Path('C:/Windows/Fonts/msyh.ttc')
    font = ImageFont.truetype(str(font_path), 17) if font_path.exists() else ImageFont.load_default()
    rows = splash['modes']['event']['evidence']
    manifest = {r['id']:r for r in read_json(corpus/'manifest.json')['samples']}
    sheet = Image.new('RGB', (1000, len(rows)*145), '#18202a')
    draw = ImageDraw.Draw(sheet)
    for i, entry in enumerate(rows):
        frame = read_image(corpus/manifest[entry['id']]['image'])
        jacket = cv2.cvtColor(crop(frame), cv2.COLOR_BGR2RGB)
        sheet.paste(Image.fromarray(jacket).resize((128,128)), (8, i*145+8))
        text = entry['expected']['name']+'\nEvent: '+entry['result']['reason']
        for player, row in entry['result']['players'].items():
            text += f"\n{player}: {row.get('difficulty','?')} {row.get('level','?')} | max EX {row.get('max_ex')} | {row['status']}"
        draw.multiline_text((150, i*145+10), text, fill='white', font=font, spacing=4)
    sheet.save(out/'event-examples.jpg', quality=90)
    return out/'REPORT.md'
