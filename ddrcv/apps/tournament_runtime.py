"""One maintained recognition loop, usable synchronously by CLI or by the desk."""
from collections import deque
from concurrent.futures import Future
from copy import deepcopy
from pathlib import Path
from queue import Queue, Empty, Full
import threading
import time

import cv2

from ddrcv.ingest.file_source import FileSource, normalize_frame
from ddrcv.apps.tournament_integrations import Integrations


class TournamentRuntime:
    def __init__(self, config, engine, fetcher, publisher, logger, *, data_dir=None,
                 clock=time, desktop=False, screenshot_factory=None, discord_callback=None):
        self.config = deepcopy(config)
        self.engine, self.fetcher, self.publisher = engine, fetcher, publisher
        self.log, self.clock, self.desktop = logger, clock, desktop
        self.stop_requested = threading.Event()
        self.finished = threading.Event()
        self.lock = threading.RLock()
        self.phase, self.error = 'Ready', None
        self.result, self.frame = None, None
        self.frame_wall = self.frame_utc = None
        self.accepted_wall = [None, None]
        self.sequence = 0
        self.frame_times = deque(maxlen=120)
        self.processing_ms = 0
        self.thread = None
        self.capture_thread = None
        self.source_switch = None
        self.source_error = None
        self.source_revision = 0
        self.retired_captures = []
        self.integrations = Integrations(config, data_dir or Path.cwd() / '.tournament', logger)
        self.screenshot = None
        result_config = config.get('results', {})
        if result_config.get('enabled', False):
            if result_config.get('discord', False) and not result_config.get('webhook'):
                raise ValueError('Set results.webhook explicitly before enabling Discord publication')
            self.screenshot = screenshot_factory(result_config['screenshot_directory'],
                                                 timestamp_fmt=result_config['timestamp_format'])
        self.discord_callback = discord_callback
        self.result_jobs = Queue(maxsize=4)
        self.result_stop = threading.Event()
        self.result_thread = None

    def start(self):
        if self.thread:
            raise ValueError('Runtime has already started')
        self.thread = threading.Thread(target=self._background, name='tournament-recognition', daemon=True)
        self.thread.start()

    def _background(self):
        try:
            self.run()
        except Exception:
            self.log.exception('Driver stopped')

    def run(self):
        previous_state = 'unknown'
        try:
            self.phase = 'Starting'
            # Claim the publisher before opening hardware; conflicts never touch another driver.
            self.publisher.start()
            self.fetcher.start()
            candidate_thread = getattr(self.fetcher, 'thread', None)
            self.capture_thread = candidate_thread if isinstance(candidate_thread, threading.Thread) else None
            self.integrations.start()
            if self.screenshot:
                self.result_thread = threading.Thread(target=self._results_loop, name='tournament-results', daemon=True)
                self.result_thread.start()
            self.phase = 'Running'
            while not self.stop_requested.is_set():
                changed, frame = self._poll_source_switch()
                if changed:
                    previous_state = 'unknown'
                else:
                    frame = self.fetcher.get_frame()
                if frame is None:
                    if isinstance(self.fetcher, FileSource) and self.fetcher.ended:
                        self.phase = 'Ended'
                        break
                    self.stop_requested.wait(.01)
                    continue
                began = time.perf_counter()
                now = self.fetcher.source_time if isinstance(self.fetcher, FileSource) else self.clock.monotonic()
                still = isinstance(self.fetcher, FileSource) and self.fetcher.kind == 'image'
                result = self.engine.process(frame, now, diagnostics=still, stateless=still)
                info = result['published']
                if still:
                    self.log.info('Image diagnostics: %s', result)
                if info['state'] != previous_state:
                    self.log.info('Confirmed state: %s -> %s', previous_state, info['state'])
                    previous_state = info['state']
                self.publisher.send_message(info)
                # Still images cannot drive OBS automation.
                if not still:
                    self.integrations.update(info)
                wall = time.perf_counter()
                with self.lock:
                    self.sequence += 1
                    self.frame, self.result = frame, result
                    self.frame_wall, self.frame_utc = wall, time.time()
                    self.frame_times.append(wall)
                    self.processing_ms = (wall - began) * 1000
                    for index, key in enumerate(('p1_score', 'p2_score')):
                        if result['decisions'].get(key) == 'accepted':
                            self.accepted_wall[index] = wall
                        elif self.engine.session.trackers[index].value is None or not info['players'][index]:
                            self.accepted_wall[index] = None
                cfg = self.config.get('results', {})
                if (self.screenshot and self.engine.session.screenshot_due(now, cfg['processing_delay'])
                        and (not cfg.get('only_duo', False) or all(info['players']))):
                    try:
                        self.result_jobs.put_nowait(frame[..., ::-1].copy())
                        self.engine.session.results_saved = True
                    except Full:
                        self.log.warning('Results queue full; retrying on next frame')
                if not self.desktop and self.config.get('driver_debug', {}).get('render_frame', False):
                    cv2.imshow('DDR Capture', frame)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break
        except KeyboardInterrupt:
            pass
        except Exception as error:
            self.phase, self.error = 'Error', str(error)
            raise
        finally:
            self._cleanup()

    def _cleanup(self):
        self.stop_requested.set()
        self._finish_source_switch(RuntimeError('Driver stopped before the camera switch completed'))
        for fetcher, _ in self.retired_captures:
            try:
                fetcher.stop()
            except Exception:
                self.log.exception('Capture cleanup error')
        for stop in (self.fetcher.stop, self.publisher.stop, self.integrations.stop):
            try:
                stop()
            except Exception as error:
                self.error, self.phase = str(error), 'Error'
                self.log.exception('Shutdown error')
        self.result_stop.set()
        if self.result_thread:
            self.result_thread.join(timeout=12)
            if self.result_thread.is_alive():
                self.log.warning('Results delivery still finishing in background')
        if not self.desktop and self.config.get('driver_debug', {}).get('render_frame', False):
            cv2.destroyAllWindows()
        if self.phase not in ('Error', 'Ended'):
            self.phase = 'Stopped'
        self.finished.set()

    def switch_source(self, ingest, timeout=10):
        """Stage a live source on the recognition worker; keep the old source until ready."""
        from ddrcv.apps.driver_config import validate_config
        candidate = deepcopy(self.config)
        candidate['ingest'] = deepcopy(ingest)
        ingest = validate_config(candidate)['ingest']
        kind = next(iter(ingest))
        if kind not in ('simple', 'rtsp'):
            raise ValueError('Live switching supports cameras and RTSP; apply and restart for files')
        with self.lock:
            if self.phase != 'Running' or self.stop_requested.is_set():
                raise ValueError('Start the driver before switching cameras')
            if self.source_switch:
                raise ValueError('A camera switch is already in progress')
            if ingest == self.config['ingest']:
                return
            current = self.config['ingest'].get(kind, {})
            key = 'uri' if kind == 'simple' else 'rtsp_url'
            if current.get(key) == ingest[kind].get(key):
                raise ValueError('Use Apply and Restart to change settings on the same camera')
            self.retired_captures = [(f, t) for f, t in self.retired_captures if t.is_alive()]
            if self.retired_captures:
                raise RuntimeError('Previous capture is still cleaning up; wait before switching again')
            future = Future()
            self.source_error = None
            self.source_switch = dict(ingest=ingest, future=future, fetcher=None,
                                      deadline=time.monotonic() + timeout)
        # The worker resolves every request, including failed/stopped sessions. A caller
        # timeout must never leave an unobserved switch that could commit later.
        future.result()

    def _create_fetcher(self, ingest):
        from ddrcv.apps.driver_ddr_tbd5 import create_frame_fetcher
        return create_frame_fetcher(ingest, self.log)

    def _release_capture(self, fetcher):
        worker = getattr(fetcher, 'thread', None)
        try:
            fetcher.stop()
        finally:
            if isinstance(worker, threading.Thread) and worker.is_alive():
                self.retired_captures.append((fetcher, worker))

    def _finish_source_switch(self, error=None):
        with self.lock:
            request = self.source_switch
        if request is None:
            return
        if error and request['fetcher'] is not None:
            try:
                self._release_capture(request['fetcher'])
            except Exception:
                self.log.exception('Candidate camera cleanup failed')
        with self.lock:
            self.source_error = str(error) if error else None
            self.source_switch = None
        if error:
            self.log.warning('Camera switch failed: %s', error)
            request['future'].set_exception(error)
        else:
            request['future'].set_result(None)

    def _poll_source_switch(self):
        request = self.source_switch
        if request is None:
            return False, None
        try:
            if request['fetcher'] is None:
                request['fetcher'] = self._create_fetcher(request['ingest'])
                request['fetcher'].start()
            if time.monotonic() >= request['deadline']:
                raise ValueError('New camera did not deliver a frame within the timeout; current source retained')
            frame = request['fetcher'].get_frame()
            if frame is None:
                return False, None
            normalize_frame(frame)  # Live cameras must deliver the fixed 1280 x 720 geometry.
        except Exception as error:
            self._finish_source_switch(error)
            return False, None
        if self.stop_requested.is_set():
            self._finish_source_switch(RuntimeError('Camera switch cancelled by Stop'))
            return False, None
        old = self.fetcher
        # Only this worker touches recognition history; no old-source frame can
        # enter the new session. Keep publisher, integrations and result delivery alive.
        with self.lock:
            info = self.engine.reset()
            self.fetcher = request['fetcher']
            request['fetcher'] = None  # Ownership transferred even if later publication fails.
            worker = getattr(self.fetcher, 'thread', None)
            self.capture_thread = worker if isinstance(worker, threading.Thread) else None
            self.config['ingest'] = deepcopy(request['ingest'])
            self.result = self.frame = None
            self.frame_wall = self.frame_utc = None
            self.accepted_wall = [None, None]
            self.frame_times.clear()
            self.source_revision += 1
        try:
            self._release_capture(old)
        except Exception:
            self.log.exception('Previous camera cleanup failed')
        self.publisher.send_message(info)
        self.integrations.update(info)
        self._finish_source_switch()
        return True, frame

    def _results_loop(self):
        while not self.result_stop.is_set() or not self.result_jobs.empty():
            try:
                rgb = self.result_jobs.get(timeout=.1)
            except Empty:
                continue
            try:
                screenshot_file = self.screenshot.save(rgb)
                self.log.info('Results screenshot: %s', screenshot_file)
                cfg = self.config['results']
                if cfg.get('discord', False):
                    self.discord_callback(title='Results', screenshot_path=screenshot_file, webhook_url=cfg['webhook'])
            except Exception:
                self.log.exception('Results save/delivery failed')

    def stop(self):
        self.stop_requested.set()
        if self.thread:
            self.thread.join(timeout=30)
            if self.thread.is_alive():
                raise RuntimeError('Driver shutdown is still pending; wait before restarting')
            for worker in (self.capture_thread, self.integrations.thread, self.result_thread,
                           *(worker for _, worker in self.retired_captures)):
                if worker and worker.is_alive():
                    raise RuntimeError('Background cleanup is still pending; wait before restarting')
        elif not self.finished.is_set():
            # A prepared runtime may be discarded before starting.
            self.fetcher.stop()
            self.finished.set()

    def status(self):
        wall = time.perf_counter()
        with self.lock:
            frame_age = None if self.frame_wall is None else wall - self.frame_wall
            times = list(self.frame_times)
            fps = (len(times) - 1) / (times[-1] - times[0]) if len(times) > 1 and times[-1] > times[0] else 0
            snapshot = dict(phase=self.phase, error=self.error, sequence=self.sequence,
                            source=deepcopy(self.config['ingest']), source_revision=self.source_revision,
                            source_switching=self.source_switch is not None, source_error=self.source_error,
                            published=deepcopy(self.result['published'] if self.result else self.engine.session.info),
                            raw_state=self.result['raw_state'] if self.result else 'unknown',
                            raw_scores=deepcopy(self.result['raw_scores']) if self.result else None,
                            decisions=deepcopy(self.result['decisions']) if self.result else {},
                            frame_age=frame_age, capture_stale=frame_age is None or frame_age > 1,
                            score_age=[None if t is None else wall - t for t in self.accepted_wall],
                            fps=round(fps, 1), processing_ms=round(self.processing_ms, 2),
                            publisher=self.publisher.status)
        snapshot.update(self.integrations.status())
        return snapshot

    def snapshot(self):
        with self.lock:
            if self.frame is None:
                return None, {}
            frame = self.frame.copy()
            metadata = dict(sequence=self.sequence, captured_at=self.frame_utc,
                            age_seconds=time.perf_counter() - self.frame_wall)
        ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
        if not ok:
            raise ValueError('Could not encode snapshot')
        return encoded.tobytes(), metadata
