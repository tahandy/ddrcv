"""Compare against a pre-change glyph_detector.py snapshot on a real recording."""
import argparse
from collections import Counter
from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import statistics
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    import cv2
    import numpy as np
    from ddrcv.apps.recognition_engine import RecognitionEngine
    from ddrcv.apps.driver_config import default_config
    from ddrcv.score import score_extractor

    cv2.setNumThreads(1)
    spec = importlib.util.spec_from_file_location('baseline_glyph_detector', args.baseline)
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)

    def extractor(reference=False):
        with redirect_stdout(io.StringIO()):
            if reference:
                with patch.object(score_extractor, 'GlyphDetector', baseline.GlyphDetector):
                    return score_extractor.ScoreExtractor()
            return score_extractor.ScoreExtractor()

    cap = cv2.VideoCapture(str(args.video.resolve()))
    if not cap.isOpened():
        raise ValueError('Cannot open recording')
    fps = cap.get(cv2.CAP_PROP_FPS)
    crops = []
    for start, end in ((20, 40), (110, 127)):
        cap.set(cv2.CAP_PROP_POS_FRAMES, round(start * fps))
        for _ in range(round((end - start) * fps)):
            ok, frame = cap.read()
            if not ok:
                raise ValueError('Recording ended before benchmark interval')
            crops.append([frame[y:y+h, x:x+w, ::-1].copy() for y, x, h, w in
                          (score_extractor.ScoreExtractor.p1_roi, score_extractor.ScoreExtractor.p2_roi)])
    trials, reference_detections = [], None
    for repeat in range(3):
        order = (True, False) if repeat % 2 == 0 else (False, True)
        for reference in order:
            scores = extractor(reference)
            detectors = [scores.p1_extractor.detector, scores.p2_extractor.detector]
            for pair in crops[:10]:
                for detector, crop in zip(detectors, pair):
                    detector.detect_glyphs(crop)
            output = []
            began = time.perf_counter()
            for pair in crops:
                output.append([detector.detect_glyphs(crop) for detector, crop in zip(detectors, pair)])
            duration = time.perf_counter() - began
            if reference_detections is None:
                reference_detections = deepcopy(output)
            if output != reference_detections:
                raise AssertionError('Complete detection dictionaries changed')
            row = dict(repeat=repeat+1, variant='baseline' if reference else 'optimized',
                       ms_per_player_crop=duration * 1000 / (2 * len(crops)))
            trials.append(row)
            print(json.dumps(row), flush=True)

    # Full sequence includes splash, gameplay, full-combo animation, results and departure.
    config = default_config()
    engines = [RecognitionEngine(config, extractor=extractor(reference)) for reference in (True, False)]
    cap.set(cv2.CAP_PROP_POS_FRAMES, round(10 * fps))
    states, parity_frames, absent_checks = Counter(), 0, 0
    for index in range(round(10 * fps), round(155 * fps)):
        ok, frame = cap.read()
        if not ok:
            raise ValueError('Recording ended before parity interval')
        results = [engine.process(frame, index / fps, frame_index=index, diagnostics=True) for engine in engines]
        if results[0] != results[1]:
            raise AssertionError(f'Recognition trace changed at frame {index}')
        states[results[0]['confirmed_state']] += 1
        parity_frames += 1
        if index % 90 == 0 and results[0]['confirmed_state'] == 'song_playing':
            for presence in ((False, True), (True, False), (False, False)):
                for engine in engines:
                    engine.extractor.set_presence(*presence)
                a, b = [engine.extractor.extract(frame[..., ::-1], debug=True) for engine in engines]
                if a != b:
                    raise AssertionError('Player presence changed recognition')
                absent_checks += 1
        if index % 900 == 0:
            print(f'Exact trace parity through {index / fps:.0f} seconds', flush=True)
    cap.release()
    medians = {name: statistics.median(t['ms_per_player_crop'] for t in trials if t['variant'] == name)
               for name in ('baseline', 'optimized')}
    improvement = 100 * (1 - medians['optimized'] / medians['baseline'])
    report = dict(video=str(args.video.resolve()),
                  baseline_sha256=hashlib.sha256(args.baseline.read_bytes()).hexdigest(),
                  optimized_sha256=hashlib.sha256((ROOT/'ddrcv/score/glyph_detector.py').read_bytes()).hexdigest(),
                  trials=trials, median_ms_per_crop=medians, improvement_percent=improvement,
                  exact_detection_comparisons=len(crops)*2*len(trials), exact_trace_frames=parity_frames,
                  states=dict(states), absent_player_checks=absent_checks,
                  gate_passed=improvement >= 15)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2), flush=True)
    if not report['gate_passed']:
        raise SystemExit('Crop-extraction improvement below 15% gate')


if __name__ == '__main__':
    main()
