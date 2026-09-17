"""Optional OBS/renderer control, isolated from the recognition loop."""
from copy import deepcopy
from concurrent.futures import Future
import logging
from pathlib import Path
from queue import Queue, Empty
import subprocess
import sys
import threading
import time

from ddrcv.publish.obs_service import OBSService


class Integrations:
    def __init__(self, config, data_dir, logger=None):
        self.config = deepcopy(config)
        self.data_dir = Path(data_dir)
        self.log = logger or logging.getLogger(__name__)
        self.obs = OBSService()
        self.renderer = None
        self.stop_file = self.data_dir / 'renderer.stop'
        self.closed = threading.Event()
        self.commands = Queue(maxsize=16)
        self.lock = threading.Lock()
        self.message = None
        self.cached = dict(obs=self.obs.status, renderer=dict(running=False, exit_code=None, error=None))
        self.renderer_error = None
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._run, name='tournament-integrations', daemon=True)
        self.thread.start()

    def update(self, message):
        with self.lock:
            self.message = deepcopy(message)

    def status(self):
        with self.lock:
            return deepcopy(self.cached)

    def command(self, action, **args):
        if self.closed.is_set() or self.thread is None or not self.thread.is_alive():
            raise ValueError('Start the driver before controlling integrations')
        future = Future()
        self.commands.put_nowait((action, args, future))
        return future.result(timeout=12)

    def _connect_obs(self):
        cfg = self.config.get('obs', {})
        self.obs.connect(**{k: v for k, v in cfg.items() if k in ('host', 'port', 'password', 'scene_map')})
        if cfg.get('automation', False):
            self.obs.automate(True)

    def _start_renderer(self):
        root = Path(self.config['renderer']['path']).expanduser().resolve()
        if not (root / 'apps/tbd5.py').is_file():
            raise ValueError('Renderer folder must contain apps/tbd5.py')
        import importlib.util
        if importlib.util.find_spec('pygame') is None:
            raise ValueError('Pygame is missing; run setup_desktop.bat')
        if self.renderer and self.renderer.poll() is None:
            return
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.stop_file.unlink(missing_ok=True)
        pub = self.config['publish']['websocket']
        host = pub['host']
        if host in ('0.0.0.0', '::'):
            host = '127.0.0.1' if host == '0.0.0.0' else '::1'
        if ':' in host:
            host = f'[{host}]'
        python = str(Path(sys.executable).with_name('python.exe')) if sys.platform == 'win32' else sys.executable
        with (self.data_dir / 'renderer.log').open('w', encoding='utf-8') as log:
            self.renderer = subprocess.Popen([python, '-B', '-m', 'apps.tbd5', '--uri',
                                             f'ws://{host}:{pub["port"]}', '--stop-file', str(self.stop_file)],
                                            cwd=root, stdout=log, stderr=subprocess.STDOUT,
                                            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        self.renderer_error = None

    def _stop_renderer(self):
        if self.renderer and self.renderer.poll() is None:
            self.stop_file.touch()
            try:
                self.renderer.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.renderer.terminate()
                try:
                    self.renderer.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.renderer.kill()
                    self.renderer.wait(timeout=2)

    def _action(self, action, args):
        actions = {'obs_connect': self._connect_obs, 'obs_disconnect': self.obs.disconnect,
                   'obs_check': self.obs.validate, 'renderer_start': self._start_renderer,
                   'renderer_stop': self._stop_renderer}
        if action == 'obs_automation':
            if type(args.get('enabled')) is not bool:
                raise ValueError('Automation enabled must be true or false')
            self.obs.automate(args['enabled'])
        elif action == 'obs_scene':
            self.obs.manual_scene(args['name'])
        elif action in actions:
            actions[action]()
        else:
            raise ValueError('Unknown integration action')

    def _refresh(self):
        running = self.renderer is not None and self.renderer.poll() is None
        exit_code = self.renderer.poll() if self.renderer else None
        with self.lock:
            self.cached = dict(obs=self.obs.status, renderer=dict(running=running, exit_code=exit_code,
                               error=self.renderer_error or ('Renderer exited unexpectedly; inspect renderer.log' if exit_code not in (None, 0) else None)))

    def _run(self):
        try:
            for key, action in (('obs', self._connect_obs), ('renderer', self._start_renderer)):
                if self.closed.is_set():
                    break
                if self.config.get(key, {}).get('enabled', False):
                    try:
                        action()
                    except Exception as error:
                        if key == 'renderer':
                            self.renderer_error = str(error)
                        self.log.error('%s could not start: %s', key, error)
            self._refresh()
            next_obs = 0
            while not self.closed.is_set():
                try:
                    action, args, future = self.commands.get(timeout=.1)
                except Empty:
                    pass
                else:
                    try:
                        self._action(action, args)
                        self._refresh()
                        future.set_result(self.status())
                    except Exception as error:
                        if action.startswith('renderer'):
                            self.renderer_error = str(error)
                        future.set_exception(error)
                if time.monotonic() >= next_obs:
                    with self.lock:
                        message = deepcopy(self.message)
                    if message is not None:
                        self.obs.update(message)
                    self._refresh()
                    next_obs = time.monotonic() + .5
        finally:
            self.obs.disconnect()
            self._stop_renderer()
            self._refresh()
            while True:
                try:
                    _, _, future = self.commands.get_nowait()
                    future.set_exception(ValueError('Integrations stopped'))
                except Empty:
                    break

    def stop(self):
        self.closed.set()
        if self.thread:
            self.thread.join(timeout=12)
            if self.thread.is_alive():
                raise RuntimeError('Integration shutdown is still pending; wait before restarting')
