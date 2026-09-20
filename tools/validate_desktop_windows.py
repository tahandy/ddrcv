"""Optional Windows acceptance/footprint probe (requires psutil).

Runs the actual tray host and window module with a test-only window driver that
calls pywebview's own lifecycle methods. No hardware/OBS/network services used.
Artifacts and all config state stay in --out; no probe API ships in the app.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import threading
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Optional probe dependencies stay separate from the application environment.
sys.path.insert(0, str(ROOT / '.desktop-validation/test-deps'))


def write(path, value):
    from ddrcv.apps.driver_config import write_json
    write_json(path, value)


def wait_for(fn, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(.1)
    raise RuntimeError('Probe condition timed out')


def read(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def probe_window(out):
    import webview
    original = webview.start

    def start(func=None, *args, **kwargs):
        def drive():
            if func:
                func()
            window = webview.windows[0]
            wait_for(lambda: window.evaluate_js('document.getElementById("phase")?.textContent !== "Connecting" && !!window.pywebview'), 30)
            write(out / 'window-state.json', dict(pid=os.getpid(), ready=True, at=time.time()))
            last = None
            while not window.events.closed.is_set():
                command = read(out / 'window-command.json')
                if command.get('id') != last:
                    last = command.get('id')
                    action = command.get('action')
                    if action == 'minimize':
                        window.minimize()
                    elif action == 'restore':
                        window.restore()
                    elif action == 'close':
                        window.destroy()  # Exercises the real closing/draft-flush handler.
                    elif action == 'crash':
                        os._exit(23)
                    write(out / 'window-ack.json', dict(id=last, action=action))
                time.sleep(.05)
        return original(drive, *args, **kwargs)

    webview.start = start
    from ddrcv.desktop.window import main
    main()


def probe_host(out):
    from ddrcv.desktop import host
    original = subprocess.Popen
    def launch(command, *args, **kwargs):
        if 'ddrcv.desktop.window' in command:
            command = [command[0], '-B', str(Path(__file__).resolve()), '--window', '--out', str(out)]
        return original(command, *args, **kwargs)
    class ProbePanel(host.Panel):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.launcher = launch
    host.Panel = ProbePanel
    host.run(out / 'host', out / 'profile.json')


def probe_cli(out):
    from ddrcv.apps.driver_config import load_config
    from ddrcv.apps.driver_ddr import create_runtime
    import logging
    runtime = create_runtime(load_config(out / 'profile.json'), logging.getLogger('probe-cli'), out / 'cli')
    def monitor():
        while not runtime.finished.wait(.25):
            write(out / 'cli-state.json', runtime.status())
            if (out / 'cli-stop').exists():
                runtime.stop_requested.set()
    threading.Thread(target=monitor, daemon=True).start()
    runtime.run()


def measure(pid, status, seconds):
    import psutil
    root = psutil.Process(pid)
    known, cpu, rss = {}, [], []
    initial = status()
    began = time.perf_counter()
    def sample():
        values = []
        for process in [root] + root.children(recursive=True):
            try:
                if process.pid not in known:
                    known[process.pid] = process
                    process.cpu_percent(None)
                values.append((known[process.pid].cpu_percent(None), process.memory_info().rss))
            except psutil.Error:
                pass
        return sum(v[0] for v in values), sum(v[1] for v in values) / 1048576
    sample()
    while time.perf_counter() - began < seconds:
        time.sleep(.5)
        c, r = sample()
        cpu.append(c)
        rss.append(r)
    final = status()
    return dict(cpu_one_core_percent=round(statistics.mean(cpu), 2),
                working_set_mb=round(statistics.mean(rss), 1),
                frames_per_second=round((final['sequence']-initial['sequence'])/(time.perf_counter()-began), 2),
                recognition_ms=final['processing_ms'], published=final['published'],
                process_count=len(root.children(recursive=True))+1)


def acceptance(out, seconds):
    import psutil
    import cv2
    from ddrcv.apps.driver_config import normalize_config
    out.mkdir(parents=True, exist_ok=True)
    # A fixed real gameplay frame makes processing identical in every condition.
    image = cv2.imread(str(ROOT / 'state_images/mar2025/gameplay_2.png'))
    if image is None:
        raise RuntimeError('Missing gameplay fixture')
    clip = out / 'fixed-gameplay.avi'
    if not clip.exists():
        writer = cv2.VideoWriter(str(clip), cv2.VideoWriter_fourcc(*'MJPG'), 30, (1280, 720))
        if not writer.isOpened():
            raise RuntimeError('MJPG encoder unavailable')
        for _ in range(2700):
            writer.write(image)
        writer.release()
    import socket
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    cfg = normalize_config({'ingest': {'video': {'path': str(clip)}},
                            'publish': {'websocket': {'host': '127.0.0.1', 'port': port}},
                            'score_filter': {'max_per_frame': None}})
    write(out / 'profile.json', cfg)
    script = str(Path(__file__).resolve())
    python = sys.executable
    report = dict(memory_metric='Sum of process working sets; shared pages may be counted more than once', conditions='Fixed real gameplay frame encoded as 30 fps MJPG, same clip for all cases; no OBS or renderer', samples={})
    for stale in ('cli-stop', 'cli-state.json', 'window-command.json', 'window-ack.json', 'window-state.json'):
        (out / stale).unlink(missing_ok=True)
    with (out / 'cli.log').open('w') as log:
        cli = subprocess.Popen([python, '-B', script, '--cli', '--out', str(out)], stdout=log, stderr=log)
    try:
        wait_for(lambda: read(out / 'cli-state.json').get('sequence', 0) > 60)
        report['samples']['cli'] = measure(cli.pid, lambda: read(out / 'cli-state.json'), seconds)
    finally:
        (out / 'cli-stop').touch()
        cli.wait(timeout=25)
    with (out / 'host.log').open('w') as log:
        backend = subprocess.Popen([python, '-B', script, '--host', '--out', str(out)], stdout=log, stderr=log)
    def api(path, value=None):
        meta=read(out / 'host/instance.json')
        req=urllib.request.Request(meta['url']+'/api/'+path,
            data=None if value is None else json.dumps(value).encode(),
            headers={'X-Desk-Token':meta['token'],'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=25) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(error.read().decode()) from error
    def command(action):
        ident=time.time_ns()
        write(out / 'window-command.json', dict(id=ident, action=action))
        wait_for(lambda: read(out / 'window-ack.json').get('id') == ident)
    try:
        wait_for(lambda: read(out / 'host/instance.json'))
        wait_for(lambda: read(out / 'window-state.json').get('ready'), 40)
        assert api('status')['phase']=='Stopped'
        first_window = read(out / 'window-state.json')['pid']
        api('action', {'action':'start'})
        wait_for(lambda: api('status')['sequence'] > 60)
        report['samples']['panel_open'] = measure(backend.pid, lambda: api('status'), seconds)
        # Second host launch must reuse the same backend and existing panel.
        duplicate=subprocess.run([python,'-B','-m','ddrcv.desktop','--data-dir',str(out/'host')],cwd=ROOT,timeout=15)
        assert duplicate.returncode==0
        assert read(out / 'window-state.json')['pid']==first_window
        report['duplicate_launch_reused_instance']=True
        command('minimize')
        time.sleep(1)
        report['samples']['panel_minimized'] = measure(backend.pid, lambda: api('status'), seconds)
        command('restore')
        # Capture child identities before closure to detect leaked WebView2 processes.
        ui = psutil.Process(first_window)
        descendants=ui.children(recursive=True)
        before=api('status')
        command('close')
        wait_for(lambda: not psutil.pid_exists(first_window))
        wait_for(lambda: all(not p.is_running() for p in descendants), 15)
        assert api('status')['sequence'] > before['sequence']
        report['samples']['panel_closed'] = measure(backend.pid, lambda: api('status'), seconds)
        report['normal_close_released_ui_processes']=True
        reopens=[]
        for index in range(3):
            (out/'window-state.json').unlink(missing_ok=True)
            # Clear previous close command before launching a fresh window.
            write(out/'window-command.json',dict(id=time.time_ns(),action='restore'))
            began=time.perf_counter()
            api('action', {'action':'open'})
            window=wait_for(lambda: read(out/'window-state.json').get('pid'), 30)
            reopens.append(round(time.perf_counter()-began, 3))
            children=psutil.Process(window).children(recursive=True)
            command('close')
            wait_for(lambda: not psutil.pid_exists(window))
            wait_for(lambda: all(not p.is_running() for p in children),15)
        report['reopen_seconds']=reopens
        report['samples']['after_three_reopens']=measure(backend.pid,lambda:api('status'),seconds)
        # Abrupt GUI loss must preserve the backend, followed by successful reopening.
        (out/'window-state.json').unlink(missing_ok=True)
        write(out/'window-command.json',dict(id=time.time_ns(),action='restore'))
        api('action',{'action':'open'})
        crash_window=wait_for(lambda:read(out/'window-state.json').get('pid'),30)
        ui=psutil.Process(crash_window);children=ui.children(recursive=True)
        old_sequence=api('status')['sequence']
        write(out/'window-command.json',dict(id=time.time_ns(),action='crash'))
        wait_for(lambda:not psutil.pid_exists(crash_window))
        wait_for(lambda:api('status')['sequence']>old_sequence+5)
        wait_for(lambda:all(not p.is_running() for p in children),15)
        report['ui_crash_preserved_capture']=True
    finally:
        try:
            api('action',{'action':'exit','confirmed':True})
            backend.wait(timeout=30)
        except Exception:
            backend.terminate()
            backend.wait(timeout=10)
    report['clean_shutdown']=backend.returncode==0
    write(out/'report.json',report)
    print(json.dumps(report,indent=2))


def gameplay_trial(args, out):
    """Measure the real runtime; all instrumentation and state are probe-local."""
    from collections import defaultdict
    from contextlib import ExitStack
    from copy import deepcopy
    import logging
    import secrets
    import socket
    from unittest.mock import patch
    import cv2
    import numpy as np
    import psutil
    from werkzeug.serving import make_server
    from ddrcv.apps.driver_config import validate_config
    from ddrcv.apps import driver_ddr as driver
    from ddrcv.desktop.controller import Desk
    from ddrcv.desktop.app import create_app
    from ddrcv.desktop.host import Panel

    if (out / 'report.json').exists() or list((out / 'results').glob('*/result.json')):
        raise ValueError('Choose a fresh output directory; prior results would affect replay deduplication')
    out.mkdir(parents=True, exist_ok=True)
    engine_source = (ROOT / 'ddrcv/apps/recognition_engine.py').read_bytes()
    engine_class = driver.RecognitionEngine
    if args.reference_revision:
        engine_source = subprocess.check_output(['git', 'show',
            f'{args.reference_revision}:ddrcv/apps/recognition_engine.py'], cwd=ROOT)
        reference = {'__name__': 'probe_reference_engine'}
        exec(compile(engine_source, 'probe_reference_engine.py', 'exec'), reference)
        engine_class = reference['RecognitionEngine']
    saved = read(args.config) if args.config else {}
    saved = saved.get('applied', saved)
    cfg = {key: deepcopy(saved[key]) for key in ('debounce', 'score_filter', 'score_mode',
           'state', 'score_extractor', 'player_names', 'results') if key in saved}
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    cfg.update(ingest={'video': {'path': str(args.video.resolve())}},
               obs={'enabled': False}, renderer={'enabled': args.condition == 'renderer',
                                                'path': str(args.renderer_path.resolve())},
               publish={'websocket': {'host': '127.0.0.1', 'port': port}},
               driver_debug={'render_frame': False})
    cfg.setdefault('results', {}).update(enabled=True, discord=False, webhook=None,
        outbox_directory=str(out / 'results'), output_directory=str(out / 'screenshots'))
    cfg.setdefault('player_names', {})['enabled'] = True
    for key in ('player_names', 'results'):
        cfg[key].setdefault('ocr', {})['allow_download'] = False
    cfg = validate_config(cfg)
    rows, stages, trace = [], defaultdict(float), []
    current = dict(started=None, thread=None, timestamp=None, index=None)
    runtime = None
    main_thread = None
    children_cpu = {}
    cpu_stop = threading.Event()

    def cpu_monitor():
        root = psutil.Process()
        while not cpu_stop.wait(.25):
            for process in [root] + root.children(recursive=True):
                try:
                    t = process.cpu_times()
                    total = t.user + t.system
                    key = str(process.pid)
                    previous = children_cpu.setdefault(key, dict(name=process.name(), first=total, last=total))
                    previous['last'] = total
                except psutil.Error:
                    pass

    def timed(original, name):
        def call(*a, **kw):
            if threading.get_ident() != main_thread or current['started'] is None:
                return original(*a, **kw)
            began = time.perf_counter()
            try:
                return original(*a, **kw)
            finally:
                stages[name] += (time.perf_counter() - began) * 1000
        return call

    class TimedLock:
        def __init__(self, lock): self.lock = lock
        def __enter__(self):
            began = time.perf_counter()
            self.lock.acquire()
            if threading.get_ident() == main_thread and current['started'] is not None:
                stages['lock_wait'] += (time.perf_counter() - began) * 1000
            return self
        def __exit__(self, *exc): self.lock.release()

    def factory(config):
        nonlocal runtime
        with patch.object(driver, 'RecognitionEngine', engine_class):
            runtime = driver.create_runtime(config, logging.getLogger('gameplay-probe'), out, desktop=True)
        source = runtime.fetcher
        source.seek(max(0, args.start - 5))
        original_get = source.get_frame

        def next_frame():
            nonlocal main_thread
            main_thread = threading.get_ident()
            wall = time.perf_counter()
            if current['started'] is not None:
                row = dict(timestamp=current['timestamp'], index=current['index'],
                    active_ms=runtime.processing_ms,
                    thread_ms=(time.thread_time() - current['thread']) * 1000,
                    completion=runtime.frame_wall, stages=dict(stages),
                    names_ready=runtime.player_names.ready, state=runtime.result['confirmed_state'])
                rows.append(row)
                # Exclude event IDs/wall clocks, which intentionally differ between runs.
                trace.append({key: deepcopy(runtime.result[key]) for key in
                              ('timestamp', 'raw_state', 'confirmed_state', 'raw_scores', 'decisions', 'published')})
            current['started'] = None
            if source.index / source.fps >= args.end:
                source.ended = True
                return None
            frame = original_get()
            if frame is not None:
                stages.clear()
                current.update(started=time.perf_counter(), thread=time.thread_time(),
                               timestamp=source.source_time, index=source.index - 1)
                stages['decode_and_pacing'] = (current['started'] - wall) * 1000
            return frame
        source.get_frame = next_frame
        return runtime

    desk = Desk(out / 'desk', runtime_factory=factory)
    desk.draft = deepcopy(cfg)
    token = secrets.token_urlsafe(24)
    server = make_server('127.0.0.1', 0, create_app(desk, token), threaded=True)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    panel = Panel(f'http://127.0.0.1:{server.server_port}', token, out, {})
    original_launch = subprocess.Popen
    def launch(command, *a, **kw):
        return original_launch([sys.executable, '-B', str(Path(__file__).resolve()),
                                '--window', '--out', str(out)], *a, **kw)
    panel.launcher = launch
    try:
        if args.condition != 'recognition':
            panel.open()
            wait_for(lambda: read(out / 'window-state.json').get('ready'), 40)
        # Prepare without starting so wrappers are installed before the first frame.
        desk.apply()
        with ExitStack() as stack:
            if args.profile_stages:
                from ddrcv.score import glyph_detector, score_extractor
                for owner, attr, name in (
                    (runtime.engine, 'process', 'recognition_total'),
                    (runtime.engine.matcher, 'match', 'state_recognition'),
                    (runtime.engine.extractor, 'extract', 'scores_total'),
                    (cv2, 'cvtColor', 'color_conversion'),
                    (glyph_detector, 'preprocess_image', 'score_preprocessing'),
                    (glyph_detector.GlyphDetector, '_match_glyph', 'template_matching'),
                    (glyph_detector.GlyphDetector, 'non_maximum_suppression', 'suppression'),
                    (score_extractor, 'detections_to_num', 'number_assembly'),
                    (runtime, '_publish', 'publication'),
                ):
                    stack.enter_context(patch.object(owner, attr, timed(getattr(owner, attr), name)))
                from ddrcv.state.player_names import PlayerNameService
                from ddrcv.results.service import ResultsService
                for cls, name in ((PlayerNameService, 'name_submission'), (ResultsService, 'results_submission')):
                    stack.enter_context(patch.object(cls, 'submit', timed(cls.submit, name)))
                for obj, attr in ((runtime, 'feed_lock'), (runtime, 'lock'),
                                  (runtime.publisher, '_lock'), (runtime.integrations, 'lock')):
                    stack.enter_context(patch.object(obj, attr, TimedLock(getattr(obj, attr))))
            monitor = threading.Thread(target=cpu_monitor, daemon=True)
            monitor.start()
            began, cpu_began = time.perf_counter(), time.process_time()
            runtime.run()
            elapsed, cpu_seconds = time.perf_counter() - began, time.process_time() - cpu_began
            cpu_stop.set(); monitor.join(2)
        if runtime.error:
            raise RuntimeError(runtime.error)
        if args.condition == 'renderer' and runtime.integrations.renderer is None:
            raise RuntimeError('Renderer did not start')
        measured = [r for r in rows if args.start <= r['timestamp'] < args.end]
        gameplay = [r for r in measured if r['state'] == 'song_playing']
        def summary(samples):
            if not samples: return None
            values = np.array([r['active_ms'] for r in samples])
            return dict(frames=len(samples), mean_ms=float(values.mean()),
                p95_ms=float(np.percentile(values, 95)), p99_ms=float(np.percentile(values, 99)),
                capacity_fps=float(1000 / values.mean()),
                throughput_fps=(len(samples)-1)/(samples[-1]['completion']-samples[0]['completion']) if len(samples)>1 else 0,
                mean_thread_ms=statistics.mean(r['thread_ms'] for r in samples),
                names_ready_frames=sum(r['names_ready'] for r in samples),
                stages_mean_ms={key:statistics.mean(r['stages'].get(key, 0) for r in samples)
                                for key in sorted({k for r in samples for k in r['stages']})})
        report = dict(condition=args.condition, interval=[args.start, args.end], profiled=args.profile_stages,
            revision=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            reference_revision=args.reference_revision,
            engine_sha256=hashlib.sha256(engine_source).hexdigest(),
            video=str(args.video.resolve()),
            python=sys.version, opencv=cv2.__version__, opencv_threads=cv2.getNumThreads(),
            score_mode=cfg['score_mode'], source_fps=runtime.fetcher.fps,
            warmup=summary([r for r in rows if r['timestamp'] < args.start]),
            measured=summary(measured), gameplay=summary(gameplay),
            process_cpu_seconds=cpu_seconds, process_cpu_cores=cpu_seconds/elapsed,
            process_tree_cpu=children_cpu, elapsed_seconds=elapsed,
            results=runtime.results.status()['records'] if runtime.results else [])
        write(out / 'report.json', report)
        write(out / 'frames.json', rows)
        write(out / 'trace.json', trace)
        print(json.dumps({k:report[k] for k in ('condition','interval','profiled','gameplay')}, indent=2))
    finally:
        cpu_stop.set()
        panel.close()
        desk.close()
        server.shutdown(); server.server_close()


def gameplay_matrix(args, out):
    out.mkdir(parents=True, exist_ok=True)
    if args.config:
        saved = read(args.config)
        saved = saved.get('applied', saved)
        selected = {key: saved[key] for key in ('debounce', 'score_filter', 'score_mode',
                    'state', 'score_extractor', 'player_names', 'results') if key in saved}
        selected.get('results', {})['webhook'] = None
        write(out / 'input-config.json', selected)
        args.config = out / 'input-config.json'
    reports = []
    for repeat in range(args.repeats):
        for start, end in ((150, 170), (248, 265)):
            for condition in ('recognition', 'panel', 'renderer'):
                variants = ['reference', 'current'] if args.compare_revision else ['current']
                if repeat % 2: variants.reverse()
                traces = {}
                for variant in variants:
                    target = out / f'{repeat+1}-{start}-{condition}-{variant}'
                    target.mkdir(parents=True, exist_ok=True)
                    command = [sys.executable, '-B', str(Path(__file__).resolve()), '--probe-gameplay',
                        '--video', str(args.video.resolve()), '--renderer-path', str(args.renderer_path.resolve()),
                        '--out', str(target), '--start', str(start), '--end', str(end), '--condition', condition]
                    if args.profile_stages: command.append('--profile-stages')
                    if args.config: command.extend(('--config', str(args.config.resolve())))
                    if variant == 'reference': command.extend(('--reference-revision', args.compare_revision))
                    print(f'Running {target.name}', flush=True)
                    with (target / 'probe.log').open('w') as log:
                        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=150)
                    report = read(target / 'report.json')
                    report.update(repeat=repeat+1, variant=variant)
                    reports.append(report)
                    write(out / 'report.json', reports)
                    traces[variant] = read(target / 'trace.json')
                    g = report['gameplay']
                    print(f"  gameplay {g['mean_ms']:.2f} ms mean / {g['p95_ms']:.2f} ms p95", flush=True)
                if len(traces) == 2 and traces['reference'] != traces['current']:
                    raise AssertionError(f'Recognition trace changed: {repeat+1}-{start}-{condition}')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'.desktop-validation/windows')
    parser.add_argument('--seconds',type=float,default=8)
    parser.add_argument('--window',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--host',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--cli',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--gameplay',action='store_true',help='Run the recorded gameplay performance matrix')
    parser.add_argument('--probe-gameplay',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--video',type=Path)
    parser.add_argument('--config',type=Path,help='Optional profile or desktop state; external integrations are isolated')
    parser.add_argument('--renderer-path',type=Path,default=ROOT.parent/'ddr_score_render')
    parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--profile-stages',action='store_true')
    parser.add_argument('--compare-revision',help='Pair each run with the recognition engine from this Git revision')
    parser.add_argument('--reference-revision',help=argparse.SUPPRESS)
    parser.add_argument('--start',type=float,default=150)
    parser.add_argument('--end',type=float,default=170)
    parser.add_argument('--condition',choices=('recognition','panel','renderer'),default='recognition')
    args=parser.parse_args();out=args.out.resolve()
    if (args.gameplay or args.probe_gameplay) and args.video is None: parser.error('--video is required')
    if args.gameplay:gameplay_matrix(args,out)
    elif args.probe_gameplay:gameplay_trial(args,out)
    elif args.window:probe_window(out)
    elif args.host:probe_host(out)
    elif args.cli:probe_cli(out)
    else:acceptance(out,args.seconds)
