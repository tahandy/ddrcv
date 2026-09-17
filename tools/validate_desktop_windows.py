"""Optional Windows acceptance/footprint probe (requires psutil).

Runs the actual tray host and window module with a test-only window driver that
calls pywebview's own lifecycle methods. No hardware/OBS/network services used.
Artifacts and all config state stay in --out; no probe API ships in the app.
"""
import argparse
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
    from ddrcv.apps.driver_ddr_tbd5 import create_runtime
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


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'.desktop-validation/windows')
    parser.add_argument('--seconds',type=float,default=8)
    parser.add_argument('--window',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--host',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--cli',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args();out=args.out.resolve()
    if args.window:probe_window(out)
    elif args.host:probe_host(out)
    elif args.cli:probe_cli(out)
    else:acceptance(out,args.seconds)
