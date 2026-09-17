"""Single-instance tray host. No webview is imported in this process."""
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
import urllib.request

from ddrcv.apps.driver_config import write_json

ROOT = Path(__file__).resolve().parents[2]


class Instance:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.file = None
        self.metadata = self.data_dir / 'instance.json'

    def acquire(self):
        self.file = (self.data_dir / 'instance.lock').open('a+b')
        self.file.seek(0, 2)
        if not self.file.tell():
            self.file.write(b'0')
            self.file.flush()
        self.file.seek(0)
        try:
            if sys.platform == 'win32':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (OSError, BlockingIOError):
            self.file.close()
            self.file = None
            return False

    def open_existing(self):
        for _ in range(30):
            try:
                info = json.loads(self.metadata.read_text(encoding='utf-8'))
                req = urllib.request.Request(info['url'] + '/api/action',
                    data=b'{"action":"open"}', headers={'Content-Type': 'application/json', 'X-Desk-Token': info['token']})
                with urllib.request.urlopen(req, timeout=2) as response:
                    return response.status == 200
            except (OSError, ValueError, KeyError):
                time.sleep(.2)
        raise RuntimeError('The tournament app is running but not responding. Check its tray icon and backend.log.')

    def close(self):
        if self.file:
            self.metadata.unlink(missing_ok=True)
            self.file.close()
            self.file = None


class Panel:
    def __init__(self, url, token, data_dir, preferences):
        self.context = dict(url=url, token=token, preferences=preferences)
        self.data_dir = Path(data_dir)
        self.process = None
        self.launcher = None  # Optional test dependency; production uses subprocess.Popen.
        self.lock = threading.Lock()
        self.closed = False

    def open(self):
        with self.lock:
            if self.closed:
                return
            if self.process and self.process.poll() is None:
                try:
                    self.process.stdin.write('{"action":"focus"}\n')
                    self.process.stdin.flush()
                    return
                except (OSError, ValueError):
                    self.process.wait(timeout=3)
            if self.process and self.process.stdin:
                self.process.stdin.close()
            python = Path(sys.executable)
            if sys.platform == 'win32':
                python = python.with_name('pythonw.exe')
            with (self.data_dir / 'panel.log').open('a', encoding='utf-8') as log:
                self.process = (self.launcher or subprocess.Popen)([str(python), '-B', '-m', 'ddrcv.desktop.window'],
                    cwd=ROOT, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT,
                    text=True, encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
            self.process.stdin.write(json.dumps(self.context) + '\n')
            self.process.stdin.flush()

    def close(self):
        with self.lock:
            self.closed = True
            if self.process and self.process.poll() is None:
                try:
                    self.process.stdin.write('{"action":"exit"}\n')
                    self.process.stdin.flush()
                    self.process.wait(timeout=5)
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    self.process.terminate()
                    self.process.wait(timeout=3)
            if self.process and self.process.stdin:
                self.process.stdin.close()


def confirm_exit():
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        message_box = user32.MessageBoxW
        message_box.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
        message_box.restype = ctypes.c_int
        # Yes/No, question icon, default No, and foreground activation. The
        # dialog owns a separate thread; it must not nest inside pystray's WndProc.
        result = message_box(None,
            'Stop capture, score publishing, and integrations owned by this app?',
            'Exit DDRCV Tournament?', 0x24 | 0x100 | 0x10000)
        if not result:
            raise ctypes.WinError(ctypes.get_last_error())
        return result == 6
    return False


class ExitConfirmation:
    """Return immediately to the tray message pump while one dialog is active."""
    def __init__(self, exiting, confirm=None):
        self.exiting = exiting
        self.confirm = confirm or confirm_exit
        self.pending = threading.Lock()
        self.thread = None

    def __call__(self, icon=None, item=None):
        if self.exiting.is_set() or not self.pending.acquire(blocking=False):
            return
        self.thread = threading.Thread(target=self._ask, name='desk-exit-confirmation', daemon=True)
        try:
            self.thread.start()
        except Exception:
            self.pending.release()
            raise

    def _ask(self):
        try:
            if not self.exiting.is_set() and self.confirm():
                self.exiting.set()
        except Exception:
            logging.getLogger(__name__).exception('Could not confirm application exit')
        finally:
            self.pending.release()


def run(data_dir, config_path=None, no_panel=False):
    instance = Instance(data_dir)
    if not instance.acquire():
        instance.open_existing()
        return
    desk = panel = server = icon = None
    exiting = threading.Event()
    try:
        from ddrcv.desktop.controller import Desk
        from ddrcv.desktop.app import create_app
        from werkzeug.serving import make_server
        import pystray
        from PIL import Image, ImageDraw
        desk = Desk(data_dir)
        logging.getLogger().setLevel(logging.INFO)
        logging.getLogger('werkzeug').setLevel(logging.WARNING)
        # pythonw has no console streams; libraries that print must still be safe.
        if sys.stdout is None:
            sys.stdout = open(os.devnull, 'w')
        if sys.stderr is None:
            sys.stderr = open(os.devnull, 'w')
        log = RotatingFileHandler(Path(data_dir) / 'backend.log', maxBytes=1024 * 1024, backupCount=2, encoding='utf-8')
        class RedactingFormatter(logging.Formatter):
            def format(self, record):
                return desk.logs.scrub(super().format(record))
        log.setFormatter(RedactingFormatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
        logging.getLogger().addHandler(log)
        if config_path:
            desk.load(config_path)
        token = secrets.token_urlsafe(32)
        app = create_app(desk, token, open_panel=lambda: panel.open(), shutdown=exiting.set)
        server = make_server('127.0.0.1', 0, app, threaded=True)
        url = f'http://127.0.0.1:{server.server_port}'
        panel = Panel(url, token, data_dir, desk.preferences)
        server_thread = threading.Thread(target=server.serve_forever, name='desk-api', daemon=True)
        server_thread.start()
        write_json(instance.metadata, dict(url=url, token=token, pid=os.getpid()))
        image = Image.new('RGB', (64, 64), '#111923')
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((10, 10, 54, 54), radius=10, fill='#67dfbe')
        draw.polygon([(23, 20), (45, 32), (23, 44)], fill='#111923')
        quit_app = ExitConfirmation(exiting)
        icon = pystray.Icon('ddrcv-tournament', image, 'DDRCV Tournament · Stopped', menu=pystray.Menu(
            pystray.MenuItem('Open panel', lambda icon, item: panel.open(), default=True),
            pystray.MenuItem(lambda item: 'Driver: ' + desk.status()['phase'], lambda: None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('Exit application…', quit_app)))
        def setup(tray):
            tray.visible = True
            if not no_panel:
                panel.open()
            while not exiting.wait(1):
                status = desk.status()
                title = 'DDRCV Tournament · ' + status['phase']
                if status.get('error') or (status['phase'] == 'Running' and status.get('capture_stale')):
                    title += ' · Check capture'
                tray.title = title
            # Stop API acceptance before releasing ownership.
            try:
                server.shutdown()
                panel.close()
                desk.close()
            finally:
                tray.stop()
        try:
            icon.run(setup=setup)
        except KeyboardInterrupt:
            exiting.set()
    finally:
        exiting.set()
        if panel:
            panel.close()
        if desk:
            desk.close()
        if server:
            server.server_close()
        if icon:
            icon.stop()
        instance.close()
