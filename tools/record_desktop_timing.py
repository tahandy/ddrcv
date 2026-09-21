"""Read the running desktop's displayed timing without changing capture/settings."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import statistics
import time
import urllib.request


def timing_sample(status):
    # Explicit allowlist: never export session tokens, credentials, or result records.
    sample = {key: status.get(key) for key in (
        'phase', 'sequence', 'fps', 'source_fps', 'processing_ms',
        'processing_avg_ms', 'processing_fps', 'frame_age')}
    sample['state'] = status.get('published', {}).get('state')
    sample['obs_connected'] = status.get('obs', {}).get('connected', False)
    sample['renderer_running'] = status.get('renderer', {}).get('running', False)
    return sample


def summarize(samples):
    active = [s for s in samples if s['phase'] == 'Running' and s['state'] == 'song_playing'
              and s['processing_avg_ms'] is not None]
    if not active:
        return {'gameplay_status_samples': 0}
    values = [s['processing_avg_ms'] for s in active]
    return dict(gameplay_status_samples=len(active),
                displayed_processing_ms=dict(min=min(values), median=statistics.median(values), max=max(values)),
                displayed_throughput_fps_median=statistics.median(s['fps'] for s in active),
                samples_at_least_25_ms=sum(v >= 25 for v in values))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=60)
    parser.add_argument('--interval', type=float, default=.5)
    parser.add_argument('--data-dir', type=Path,
                        default=Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'DDRCV/tournament')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    if not 0 < args.seconds <= 3600 or not .1 <= args.interval <= 10:
        parser.error('Use 0 < seconds <= 3600 and 0.1 <= interval <= 10')
    output = args.out or (Path(__file__).resolve().parents[1] / '.desktop-validation' /
                         ('live-timing-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json'))
    samples, failures = [], []
    began = time.monotonic()
    print('Recording status only. Start/play gameplay in the desktop as usual.', flush=True)
    while time.monotonic() - began < args.seconds:
        tick = time.monotonic()
        try:
            metadata = json.loads((args.data_dir / 'instance.json').read_text(encoding='utf-8'))
            request = urllib.request.Request(metadata['url'] + '/api/status',
                                             headers={'X-Desk-Token': metadata['token']})
            with urllib.request.urlopen(request, timeout=3) as response:
                sample = timing_sample(json.load(response))
            sample['elapsed_seconds'] = round(time.monotonic() - began, 3)
            samples.append(sample)
        except (OSError, ValueError, KeyError) as error:
            failures.append(dict(elapsed_seconds=round(time.monotonic() - began, 3), kind=type(error).__name__))
        remaining = args.seconds - (time.monotonic() - began)
        time.sleep(max(0, min(remaining, args.interval - (time.monotonic() - tick))))
    report = dict(metric='Samples of the displayed two-second average; not individual-frame percentiles',
                  interval_seconds=args.interval, summary=summarize(samples), samples=samples, failures=failures)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report['summary'], indent=2))
    print(f'Saved {output}')


if __name__ == '__main__':
    main()
