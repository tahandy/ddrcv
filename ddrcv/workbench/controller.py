"""One playback worker, one publisher, and optional local integrations."""
from collections import deque
from concurrent.futures import Future
from copy import deepcopy
from datetime import datetime
import importlib.util
import json
import logging
import re
from pathlib import Path
from queue import Queue, Empty
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import cv2

from ddrcv.apps.recognition_engine import RecognitionEngine
from ddrcv.results.service import ResultsService, load_config, source_identity
from ddrcv.results.delivery import redact_error
from ddrcv.ingest.file_source import FileSource, FramePacket, normalize_frame
from ddrcv.ingest.simple_frame_fetcher import SimpleFrameFetcher
from ddrcv.ingest.rtsp_frame_fetcher import RTSPFrameFetcher
from ddrcv.publish.websocket_publisher import WebSocketPublisher
from ddrcv.publish.obs_service import OBSService
from ddrcv.score.score_extractor import ScoreExtractor
from ddrcv.publish.obs_policy import DEFAULT_SCENE_MAP
from ddrcv.workbench.regions import draw_monitored_regions
from ddrcv.state.player_names import PlayerNameService

ROOT = Path(__file__).resolve().parents[2]
STATES = ['unknown', 'login', 'song_select', 'song_splash', 'song_playing', 'song_result', 'total_result']
DEFAULTS = dict(source=dict(kind='video', path='', resize_to_720p=False), score_mode='money',
                player_names=dict(enabled=False),
                port=9000, renderer_path=str(ROOT.parent / 'ddr_score_render'),
                obs=dict(host='localhost', port=4455, password='', scene_map=DEFAULT_SCENE_MAP))


def plain(value):
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if hasattr(value, 'item'):
        return value.item()
    return value


def redact(value):
    if isinstance(value, dict):
        return {key: '[redacted]' if any(word in key.lower() for word in ('password', 'webhook', 'secret', 'token')) else redact(item)
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str) and '://' in value:
        value = redact_error(value) if '/webhooks/' in value else value
        def scrub(match):
            try:
                parsed = urlsplit(match.group())
                return urlunsplit((parsed.scheme, parsed.netloc.split('@')[-1], parsed.path, '', ''))
            except ValueError:
                return '[redacted URL]'
        return re.sub(r'[a-zA-Z][a-zA-Z0-9+.-]*://[^\s]+', scrub, value)
    return value


class RecentLogs(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.lines = deque(maxlen=200)
        self.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))

    def emit(self, record):
        self.lines.append(self.format(record))


class Workbench:
    def __init__(self, data_dir=None, engine=None, start_publisher=True):
        self.data_dir = Path(data_dir or ROOT / '.workbench').resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings_file = self.data_dir / 'settings.json'
        self.settings = deepcopy(DEFAULTS)
        self.log = logging.getLogger('ddrcv.workbench')
        self.logs = RecentLogs()
        logging.getLogger().addHandler(self.logs)
        try:
            if self.settings_file.exists():
                saved = json.loads(self.settings_file.read_text(encoding='utf-8'))
                self.settings.update({key: value for key, value in saved.items() if key in DEFAULTS})
                self.settings['obs'] = {**DEFAULTS['obs'], **saved.get('obs', {})}
        except (ValueError, OSError):
            self.log.warning('Local settings could not be read; using defaults')
        self.engine = engine or RecognitionEngine({'score_filter': {'max_per_frame': None if self.settings['score_mode'] == 'money' else 12}})
        self.publisher = WebSocketPublisher(host='127.0.0.1', port=self.settings['port'])
        self.obs = OBSService()
        self.lock = threading.RLock()
        self.frame_ready = threading.Condition(self.lock)
        self.image_lock = threading.Lock()
        self.commands = Queue()
        self.closed = threading.Event()
        self.source = None
        self.kind = None
        self.meta = {}
        self.playing = False
        self.loop = False
        self.speed = 1.0
        self.phase = 'No source'
        self.error = None
        self.frame = None
        self.image_cache = {}
        self.packet = None
        self.result = None
        self.message = deepcopy(self.engine.session.info)
        self.sequence = 0
        self.epoch = 0
        self.deadline = 0
        self.last_frame_wall = None
        self.processing_ms = 0
        self.decode_ms = 0
        self.recognition_ms = 0
        self.frame_times = deque(maxlen=120)
        self.renderer = None
        self.pickers = set()
        self.renderer_stop = self.data_dir / 'renderer.stop'
        self.results_config_path = self.data_dir / 'results_config.json'
        self.results = ResultsService(self.data_dir / 'results', load_config(self.results_config_path))
        self.results.notify = self._results_changed
        self.results_source_id = ''
        self.results_recorded = False
        self.player_names = PlayerNameService(self.settings['player_names'])
        self.message['player_names'] = self.player_names.snapshot()
        self.publisher.send_message(self.message)
        if start_publisher:
            try:
                self.publisher.start()
            except RuntimeError as error:
                self.error = str(error)
        self.worker = threading.Thread(target=self._run, name='rehearsal-playback', daemon=True)
        self.worker.start()
        self.obs_worker = threading.Thread(target=self._obs_loop, name='rehearsal-obs', daemon=True)
        self.obs_worker.start()

    def _results_changed(self):
        with self.lock:
            self.message['results'] = self.results.feed_status()
            self.publisher.send_message(deepcopy(self.message))

    def configure_results(self, values):
        allowed = {'enabled', 'discord', 'webhook', 'rehearsal'}
        if set(values) - allowed:
            raise ValueError('Unknown results setting')
        values = dict(values)
        if values.get('webhook') == '[redacted]':
            values.pop('webhook')
        config = {**self.results.config, **values}
        self.results._validate(config)
        temporary = self.results_config_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(config, indent=2), encoding='utf-8')
        temporary.replace(self.results_config_path)
        self.results.configure(**values)
        return {'ok': True}

    def save_settings(self):
        with self.lock:
            temporary = self.settings_file.with_suffix('.tmp')
            temporary.write_text(json.dumps(self.settings, indent=2), encoding='utf-8')
            temporary.replace(self.settings_file)

    def submit(self, action, **args):
        if self.closed.is_set():
            raise ValueError('Workbench is shutting down')
        future = Future()
        self.commands.put((action, args, future))
        return future.result(timeout=20)

    def _run(self):
        while not self.closed.is_set():
            if self.player_names.changed.is_set():
                self.player_names.changed.clear()
                with self.lock:
                    self.message['player_names'] = self.player_names.snapshot()
                    if self.result is not None:
                        self.result['published']['player_names'] = dict(self.message['player_names'])
                    if self.kind != 'image':
                        self.publisher.send_message(self.message)
            try:
                # Timed queue waits use coarse Windows synchronization timers.
                # Python 3.12 sleep uses a high-resolution waitable timer. Short
                # sleeps keep controls responsive without busy-waiting or
                # changing the system-wide timer resolution.
                action, args, future = self.commands.get_nowait() if self.playing else self.commands.get(timeout=.05)
            except Empty:
                action = None
                if self.playing:
                    remaining = self.deadline - time.perf_counter()
                    if remaining > 0:
                        time.sleep(min(.01, remaining))
                        continue
            if action:
                try:
                    result = self._command(action, **args)
                    self.error = None
                    future.set_result(result)
                except Exception as error:
                    self.error = str(error)
                    future.set_exception(error)
            if self.playing and time.perf_counter() >= self.deadline:
                try:
                    self._next()
                except Exception as error:
                    self.error, self.phase, self.playing = str(error), 'Error', False
                    self.log.error('Playback stopped: %s', error)

    def _reset(self):
        message = self.engine.reset()
        self.results.reset(self.results_source_id, self.results_recorded, self.settings['score_mode'])
        with self.lock:
            self.epoch += 1
            self.player_names.reset(self.engine.session.song_generation)
            message['player_names'] = self.player_names.snapshot()
            self.result = None
            self.message = message
            self.frame_times.clear()
        self.publisher.send_message(message)

    def _stop_source(self):
        self.playing = False
        if self.source is not None:
            self.source.stop()
        self.source = None

    def _command(self, action, **args):
        if action == 'snapshot':
            return self.snapshot()
        if action == 'results_config':
            return self.configure_results(args)
        if action in ('results_retry', 'results_republish'):
            self.results.retry(args['event_id'], republish=action == 'results_republish')
            return {'ok': True}
        if action == 'open':
            kind = args.get('kind', 'video')
            resize = bool(args.get('resize_to_720p', False))
            path = str(args.get('path', ''))
            saved_source = self.settings['source']
            if kind == 'rtsp' and path == redact(saved_source.get('path', '')):
                path = saved_source.get('path', path)
            if kind in ('video', 'image'):
                source = FileSource(path, kind, resize)
                meta = source.metadata
            elif kind == 'camera':
                source = SimpleFrameFetcher(int(path), width=1280, height=720)
                meta = dict(kind=kind, path=path, fps=None, duration=0, resized=False)
            elif kind == 'rtsp':
                if not path.startswith(('rtsp://', 'rtsps://')):
                    raise ValueError('Enter an RTSP URL')
                source = RTSPFrameFetcher(path, hw_accel=False)
                meta = dict(kind=kind, path=path, fps=None, duration=0, resized=False)
            else:
                raise ValueError('Choose video, image, camera, or RTSP')
            self._stop_source()
            self.source, self.kind, self.meta = source, kind, meta
            self.results_source_id, self.results_recorded = source_identity(meta)
            self.settings['source'] = dict(kind=kind, path=path, resize_to_720p=resize)
            self.save_settings()
            self._reset()
            with self.lock:
                self.frame = self.packet = None
                self.error = None
                self.last_frame_wall = None
                self.sequence += 1
                self.frame_ready.notify_all()
            self.source.start()
            self.playing = kind in ('camera', 'rtsp')
            self.phase = 'Waiting for capture' if self.playing else 'Image' if kind == 'image' else 'Paused'
            self.deadline = time.perf_counter()
            if kind in ('image', 'video'):
                self._next()
            self.log.info('Opened %s source', kind)
        elif action == 'play':
            if self.kind not in ('video', 'camera', 'rtsp') or self.source is None:
                raise ValueError('Open a video or capture device first')
            if self.kind == 'video' and self.source.ended:
                self.source.seek(0)
                self._reset()
            self.frame_times.clear()
            self.playing, self.phase, self.deadline = True, 'Playing', time.perf_counter()
        elif action == 'pause':
            self.playing, self.phase = False, 'Paused'
        elif action in ('seek', 'restart'):
            if self.kind != 'video':
                raise ValueError('Seek and restart are available for video files')
            self.source.seek(0 if action == 'restart' else float(args['seconds']))
            self._reset()
            self.phase = 'Playing' if self.playing else 'Paused'
            self._next()
        elif action == 'step':
            if self.kind != 'video':
                raise ValueError('Frame stepping is available for video files')
            self.playing, self.phase = False, 'Paused'
            self._next()
        elif action == 'playback':
            speed = float(args.get('speed', self.speed))
            if speed not in (.25, .5, 1, 2):
                raise ValueError('Choose 0.25, 0.5, 1, or 2 times speed')
            self.speed, self.loop, self.deadline = speed, bool(args.get('loop', self.loop)), time.perf_counter()
            self.frame_times.clear()
        elif action == 'score_mode':
            mode = args['mode']
            if mode not in ('money', 'ex'):
                raise ValueError('Choose money or ex')
            self.settings['score_mode'] = mode
            self.engine.config['score_filter']['max_per_frame'] = None if mode == 'money' else 12
            self._reset()
            if self.packet is not None:
                self._process(self.packet)
            self.save_settings()
        elif action == 'simulate':
            state = args.get('state', 'unknown')
            if state not in STATES:
                raise ValueError('Unknown simulated state')
            players = [bool(args.get('p1_present', True)), bool(args.get('p2_present', True))]
            scores = [int(args.get('p1_score', 0)), int(args.get('p2_score', 0))]
            if any(value < -1 for value in scores):
                raise ValueError('Scores must be -1 (unread) or nonnegative integers')
            self._stop_source()
            self._reset()
            self.kind, self.phase, self.meta = 'simulation', 'Simulation', {'kind': 'simulation'}
            message = dict(state=state, players=players, song=None,
                           player_names=dict(p1=None, p2=None),
                           score={key: score if present else None for key, score, present in
                                  zip(('p1_score', 'p2_score'), scores, players)})
            with self.lock:
                self.frame = self.packet = self.result = None
                self.message = message
                self.sequence += 1
                self.frame_ready.notify_all()
            self.publisher.send_message(message)
        elif action == 'publisher':
            port = int(args.get('port', 9000))
            if not 1 <= port <= 65535:
                raise ValueError('Port must be between 1 and 65535')
            self.publisher.stop()
            self.publisher = WebSocketPublisher(host='127.0.0.1', port=port)
            self.publisher.send_message(self.message)
            self.publisher.start()
            self.settings['port'] = port
            self.save_settings()
            self.error = None
        elif action == 'stop':
            self.results.finish()
            self._stop_source()
            self.kind, self.phase, self.meta = None, 'Stopped', {}
            self._reset()
            with self.lock:
                self.frame = self.packet = None
                self.sequence += 1
                self.frame_ready.notify_all()
        else:
            raise ValueError(f'Unknown action: {action}')
        return {'ok': True}

    def _next(self):
        began = time.perf_counter()
        if self.kind in ('video', 'image'):
            packet = self.source.read()
            if packet is None:
                self.results.finish()
                if self.kind == 'video' and self.loop and self.playing:
                    self.source.seek(0)
                    self._reset()
                    packet = self.source.read()
                else:
                    self.playing, self.phase = False, 'Ended'
                    return
        else:
            frame = self.source.get_frame()
            if frame is None:
                self.results.tick(began)
                self.deadline = began + .005
                return
            height, width = frame.shape[:2]
            frame = normalize_frame(frame, self.settings['source']['resize_to_720p'])
            self.meta.update(width=width, height=height, resized=(width, height) != (1280, 720))
            packet = FramePacket(frame, began, 0 if self.packet is None else self.packet.index + 1)
        decoded = time.perf_counter()
        self._process(packet)
        finished = time.perf_counter()
        elapsed = finished - began
        self.decode_ms = (decoded - began) * 1000
        self.recognition_ms = (finished - decoded) * 1000
        self.processing_ms = elapsed * 1000
        # Sequential replay never skips frames to catch up. Processing time is
        # included in each frame's wall-time budget, while recognition uses PTS.
        interval = 1 / self.source.fps / self.speed if self.kind == 'video' else 0
        # Advance the existing schedule so an OS wakeup delay isn't added to
        # every subsequent frame. If parsing is slow, process the next frame
        # immediately; replay still never skips frames.
        self.deadline = max(self.deadline + interval, finished)
        if self.playing:
            self.phase = 'Playing'

    def _process(self, packet):
        result = self.engine.process(packet.image, packet.timestamp, packet.index,
                                     diagnostics=True, stateless=self.kind == 'image')
        if self.kind != 'image':
            self.results.submit(packet.image, packet.timestamp, result['raw_state'],
                                result['published']['state'], result['published']['players'], packet.index)
        with self.lock:
            previous_state = self.message['state']
            if self.kind != 'image':
                self.player_names.submit(packet.image, packet.timestamp, result['raw_state'],
                                         result['published']['state'], result['published']['players'],
                                         self.engine.session.song_generation)
            self.result = plain(result)
            self.message = deepcopy(result['published'])
            self.message['player_names'] = self.player_names.snapshot()
            self.result['published']['player_names'] = dict(self.message['player_names'])
            if self.results.config['enabled']:
                self.message['results'] = self.results.feed_status()
            self.image_cache.clear()
            self.frame = packet.image
            self.packet = packet
            self.sequence += 1
            self.last_frame_wall = time.perf_counter()
            self.frame_times.append(self.last_frame_wall)
            self.frame_ready.notify_all()
        if previous_state != self.message['state']:
            self.log.info('Frame %s at %.3fs: confirmed %s -> %s',
                          packet.index, packet.timestamp, previous_state, self.message['state'])
        if self.kind != 'image':
            self.publisher.send_message(self.message)

    def _obs_loop(self):
        while not self.closed.wait(.5):
            with self.lock:
                message = deepcopy(self.message)
            self.obs.update(message)

    def status(self):
        with self.lock:
            times = list(self.frame_times)
            actual_fps = (len(times) - 1) / (times[-1] - times[0]) if len(times) > 1 and times[-1] > times[0] else 0
            desired_fps = (self.meta.get('fps') or 0) * self.speed
            return plain(dict(phase=self.phase, playing=self.playing, speed=self.speed, loop=self.loop,
                              source=redact(deepcopy(self.meta)), sequence=self.sequence, epoch=self.epoch,
                              position=self.packet.timestamp if self.packet else 0,
                              diagnostics=deepcopy(self.result), published=deepcopy(self.message),
                              settings=redact(deepcopy(self.settings)), error=self.error,
                              processing_ms=round(self.processing_ms, 2), actual_fps=round(actual_fps, 1),
                              decode_ms=round(self.decode_ms, 2), recognition_ms=round(self.recognition_ms, 2),
                              lagging=bool(desired_fps and (self.processing_ms > 1000 / desired_fps
                                           or (self.playing and len(times) >= 8 and actual_fps < desired_fps * .9))),
                              frame_age=None if self.last_frame_wall is None else time.perf_counter() - self.last_frame_wall,
                              results=self.results.status(),
                              player_name_status=self.player_names.status(),
                              publisher=self.publisher.status,
                              renderer=dict(running=self.renderer is not None and self.renderer.poll() is None,
                                            exit_code=self.renderer.poll() if self.renderer else None)))

    def image(self, view='clean'):
        # Multiple panel/OBS viewers reuse one encoding of each view/frame.
        with self.image_lock:
            return self._image(view)

    def wait_for_frame(self, sequence, timeout=.5):
        with self.frame_ready:
            return self.frame_ready.wait_for(lambda: self.sequence != sequence or self.closed.is_set(), timeout)

    def _image(self, view):
        with self.lock:
            if self.frame is None:
                return None, self.sequence
            if (self.sequence, view) in self.image_cache:
                return self.image_cache[(self.sequence, view)], self.sequence
            # Published frames/results are replaced, never modified in place.
            # Copy pixels only for the overlays that draw on them.
            frame, result, sequence = self.frame, self.result, self.sequence
        if view in ('p1', 'p2'):
            top, left, height, width = ScoreExtractor.p1_roi if view == 'p1' else ScoreExtractor.p2_roi
            frame = frame[top:top + height, left:left + width].copy()
            glyphs = (result or {}).get('glyphs', {}).get(view + '_debug') or []
            for glyph in glyphs:
                x1, y1, x2, y2 = glyph['bounding_box']
                cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 1)
            frame = cv2.resize(frame, (720, 135), interpolation=cv2.INTER_NEAREST)
        elif view == 'monitored' and result:
            frame = frame.copy()
            draw_monitored_regions(frame, result.get('monitored_regions', []))
        elif view == 'annotated' and result:
            frame = frame.copy()
            for top, left, height, width in (ScoreExtractor.p1_roi, ScoreExtractor.p2_roi):
                cv2.rectangle(frame, (left, top), (left + width, top + height), (0, 255, 0), 2)
            label = f"Frame {result['frame_index']} | {result['timestamp']:.3f}s | {result['raw_state']} -> {result['confirmed_state']}"
            cv2.rectangle(frame, (0, 0), (1280, 35), (20, 20, 20), -1)
            cv2.putText(frame, label, (12, 25), cv2.FONT_HERSHEY_SIMPLEX, .65, (255, 255, 255), 1)
        ok, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        image = jpeg.tobytes() if ok else None
        with self.lock:
            if sequence == self.sequence:
                self.image_cache[(sequence, view)] = image
        return image, sequence

    def snapshot(self):
        with self.lock:
            if self.frame is None:
                raise ValueError('Open a frame before saving a diagnostic snapshot')
            frame = self.frame.copy()
            evidence = dict(sequence=self.sequence, epoch=self.epoch, source=redact(deepcopy(self.meta)),
                            diagnostics=deepcopy(self.result), settings=redact(deepcopy(self.settings)),
                            parser_config=redact(deepcopy(self.engine.config)), logs=list(self.logs.lines))
        # Remove configured credentials from exception/log text as well.
        secret = self.settings['obs'].get('password', '')
        if secret:
            evidence['logs'] = [line.replace(secret, '[redacted]') for line in evidence['logs']]
        evidence['logs'] = [redact(line) if '://' in line else line for line in evidence['logs']]
        folder = self.data_dir / 'snapshots' / (datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid4().hex[:8])
        folder.mkdir(parents=True)
        cv2.imwrite(str(folder / 'frame.png'), frame)
        cv2.imwrite(str(folder / 'monitored.png'), draw_monitored_regions(
            frame.copy(), (evidence['diagnostics'] or {}).get('monitored_regions', [])))
        for name, roi in (('p1', ScoreExtractor.p1_roi), ('p2', ScoreExtractor.p2_roi)):
            top, left, height, width = roi
            cv2.imwrite(str(folder / f'{name}_crop.png'), frame[top:top + height, left:left + width])
        (folder / 'diagnostics.json').write_text(json.dumps(plain(evidence), indent=2), encoding='utf-8')
        return dict(path=str(folder))

    def start_renderer(self, path=None):
        root = Path(path or self.settings['renderer_path']).expanduser().resolve()
        if not (root / 'apps' / 'tbd5.py').is_file():
            raise ValueError('Select the ddr_score_render repository folder containing apps/tbd5.py')
        if importlib.util.find_spec('pygame') is None:
            raise ValueError('Pygame is missing. Run setup_workbench.bat again.')
        self.stop_renderer()
        self.renderer_stop.unlink(missing_ok=True)
        with (self.data_dir / 'renderer.log').open('w', encoding='utf-8') as stream:
            self.renderer = subprocess.Popen([sys.executable, '-B', '-m', 'apps.tbd5', '--uri',
                                               f'ws://127.0.0.1:{self.publisher.port}', '--stop-file', str(self.renderer_stop)],
                                              cwd=root, stdout=stream, stderr=subprocess.STDOUT)
        self.settings['renderer_path'] = str(root)
        self.save_settings()
        return {'ok': True}

    def browse_path(self, directory=False):
        args = [sys.executable, '-B', '-m', 'ddrcv.workbench.picker']
        if directory:
            args.append('--directory')
        with self.lock:
            if self.closed.is_set():
                raise ValueError('Workbench is shutting down')
            process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.pickers.add(process)
        try:
            try:
                output, _ = process.communicate(timeout=120)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                raise ValueError('File picker timed out. Paste the local path instead.')
            if process.returncode:
                raise ValueError('Native file picker could not open. Paste the local path instead.')
            return json.loads(output)
        finally:
            with self.lock:
                self.pickers.discard(process)

    def stop_renderer(self):
        if self.renderer and self.renderer.poll() is None:
            self.renderer_stop.touch()
            try:
                self.renderer.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.renderer.terminate()
                self.renderer.wait(timeout=3)

    def configure_obs(self, values):
        settings = {**self.settings['obs'], **values}
        if settings.get('password') == '[redacted]':
            settings['password'] = self.settings['obs'].get('password', '')
        result = self.obs.connect(**settings)
        self.settings['obs'] = settings
        self.save_settings()
        return result

    def checks(self):
        checks = []
        from ddrcv.ocr.check import check_ocr
        checks.append(check_ocr())
        for module in ('cv2', 'numpy', 'PIL', 'imagehash', 'skimage', 'flask', 'websockets', 'obsws_python', 'pygame', 'tkinter'):
            checks.append(dict(name=module, ok=importlib.util.find_spec(module) is not None, detail='Python dependency'))
        glyphs = ROOT / 'ddrcv' / 'score' / 'fonts' / 'World2'
        checks.append(dict(name='Digit templates', ok=all((glyphs / f'{i}.png').is_file() for i in range(10)), detail=str(glyphs)))
        checks.append(dict(name='State templates', ok=(ROOT / 'ddrcv/state/world/gameplay_1.pkl').is_file(), detail='DDR World'))
        renderer_root = Path(self.settings['renderer_path'])
        checks.append(dict(name='Renderer assets', ok=(renderer_root / 'score_render/assets/fonts/ChangaOne-Regular.ttf').is_file(), detail=str(renderer_root)))
        if self.publisher.status['running']:
            checks.append(dict(name='Score feed', ok=True, detail=f"Port {self.publisher.port}; {self.publisher.status['clients']} connected clients"))
        else:
            try:
                with socket.socket() as probe:
                    probe.bind(('127.0.0.1', self.publisher.port))
                checks.append(dict(name='Score feed port', ok=True, detail=f'Port {self.publisher.port} is available'))
            except OSError:
                checks.append(dict(name='Score feed port', ok=False, detail=f'Port {self.publisher.port} is occupied. Stop the other driver or simulator.'))
        source = self.settings['source']
        if source.get('path') and source['kind'] in ('image', 'video'):
            try:
                probe = FileSource(source['path'], source['kind'], source.get('resize_to_720p', False))
                detail = f'{probe.width}x{probe.height}; {probe.fps:g} fps; readable'
                probe.stop()
                checks.append(dict(name='Source file', ok=True, detail=detail))
            except Exception as error:
                checks.append(dict(name='Source file', ok=False, detail=str(error)))
        else:
            checks.append(dict(name='Source', ok=self.source is not None, detail=self.phase))
        if self.obs.client is not None:
            try:
                status = self.obs.validate()
                checks.append(dict(name='OBS scenes', ok=not status['missing'], detail=status['error'] or 'Connected and scene names verified'))
            except Exception as error:
                checks.append(dict(name='OBS scenes', ok=False, detail=str(error)))
        else:
            checks.append(dict(name='OBS (optional)', ok=None, detail='Not connected; parser-only testing is available'))
        return checks

    def close(self):
        if self.closed.is_set():
            return
        try:
            self.submit('stop')
        finally:
            self.closed.set()
            try:
                with self.lock:
                    self.frame_ready.notify_all()
                    for picker in tuple(self.pickers):
                        if picker.poll() is None:
                            picker.terminate()
                            picker.wait(timeout=3)
                self.worker.join(timeout=3)
            finally:
                # Drain playback commands before releasing the feed, so a queued
                # port change cannot reopen it. Other cleanup must not delay or
                # prevent releasing the listening socket.
                self.publisher.stop()
            self.obs_worker.join(timeout=3)
            self.obs.disconnect()
            self.stop_renderer()
            self.player_names.close()
            self.results.close()
            logging.getLogger().removeHandler(self.logs)
