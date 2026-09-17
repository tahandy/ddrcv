"""One maintained recognition loop, usable synchronously by CLI or by the desk."""
from collections import deque
from concurrent.futures import Future
from copy import deepcopy
from pathlib import Path
import threading
import time

import cv2

from ddrcv.ingest.file_source import FileSource, normalize_frame
from ddrcv.apps.tournament_integrations import Integrations
from ddrcv.state.player_names import PlayerNameService


class TournamentRuntime:
    def __init__(self, config, engine, fetcher, publisher, logger, *, data_dir=None,
                 clock=time, desktop=False, results_factory=None):
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
        self.processing_times = deque(maxlen=120)
        self.processing_ms = 0
        self.thread = None
        self.capture_thread = None
        self.source_switch = None
        self.source_error = None
        self.source_revision = 0
        self.retired_captures = []
        self.integrations = Integrations(config, data_dir or Path.cwd() / '.tournament', logger)
        self.results_factory = results_factory
        self.results = None
        self.results_error = None
        self.results_update = None
        self.control_update = None
        self.feed_lock = threading.RLock()
        self.feed_active = False
        self.feed_integrations = False
        self.latest_info = deepcopy(engine.session.info)
        self.latest_message = {**deepcopy(self.latest_info), 'player_names': dict(p1=None, p2=None)}
        self.player_names = None

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
            self.feed_active = True
            self.player_names = PlayerNameService(self.config.get('player_names'))
            self._start_results()
            self.fetcher.start()
            candidate_thread = getattr(self.fetcher, 'thread', None)
            self.capture_thread = candidate_thread if isinstance(candidate_thread, threading.Thread) else None
            self.integrations.start()
            self.phase = 'Running'
            while not self.stop_requested.is_set():
                if self.player_names.changed.is_set():
                    self.player_names.changed.clear()
                    self._publish()
                self._poll_results_update()
                self._poll_control_update()
                changed, frame = self._poll_source_switch()
                if changed:
                    previous_state = 'unknown'
                else:
                    frame = self.fetcher.get_frame()
                if frame is None:
                    if self.results is not None and not isinstance(self.fetcher, FileSource):
                        self.results.tick(self.clock.monotonic())
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
                if self.results is not None and not still:
                    self.results.submit(frame, now, result['raw_state'], info['state'], info['players'],
                                        self.fetcher.index - 1 if isinstance(self.fetcher, FileSource) else None)
                with self.feed_lock:
                    if not still:
                        self.player_names.submit(frame, now, result['raw_state'], info['state'],
                                                 info['players'], self.engine.session.song_generation)
                    self._publish(info, integrations=not still)
                wall = time.perf_counter()
                with self.lock:
                    self.sequence += 1
                    self.frame, self.result = frame, result
                    self.frame_wall, self.frame_utc = wall, time.time()
                    self.frame_times.append(wall)
                    self.processing_ms = (wall - began) * 1000
                    self.processing_times.append((wall, wall - began))
                    for index, key in enumerate(('p1_score', 'p2_score')):
                        if result['decisions'].get(key) == 'accepted':
                            self.accepted_wall[index] = wall
                        elif self.engine.session.trackers[index].value is None or not info['players'][index]:
                            self.accepted_wall[index] = None
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
        with self.lock:
            request, self.results_update = self.results_update, None
        if request:
            request['future'].set_exception(RuntimeError('Driver stopped before results settings were applied'))
        with self.lock:
            control, self.control_update = self.control_update, None
        if control:
            control['future'].set_exception(RuntimeError('Driver stopped before control was applied'))
        self._finish_source_switch(RuntimeError('Driver stopped before the camera switch completed'))
        for fetcher, _ in self.retired_captures:
            try:
                fetcher.stop()
            except Exception:
                self.log.exception('Capture cleanup error')
        for stop in (self.fetcher.stop, self._stop_names, self._stop_results, self.publisher.stop, self.integrations.stop):
            try:
                stop()
            except Exception as error:
                self.error, self.phase = str(error), 'Error'
                self.log.exception('Shutdown error')
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
            self.processing_times.clear()
            self.processing_ms = 0
            self.source_revision += 1
        try:
            self._release_capture(old)
        except Exception:
            self.log.exception('Previous camera cleanup failed')
        if self.results is not None:
            self.results.finish()
            self._reset_results_source()
        with self.feed_lock:
            if self.player_names is not None:
                self.player_names.reset(self.engine.session.song_generation)
            self._publish(info, integrations=True)
        self._finish_source_switch()
        return True, frame

    def control(self, action, value):
        if action not in ('names', 'reset_score'):
            raise ValueError('Unknown runtime control')
        if action == 'names' and type(value) is not bool:
            raise ValueError('Name setting must be boolean')
        if action == 'reset_score' and (type(value) is not int or value not in (0, 1)):
            raise ValueError('Select player 1 or 2')
        with self.lock:
            if self.phase != 'Running' or self.stop_requested.is_set():
                raise ValueError('Start capture before using this control')
            if self.control_update:
                raise ValueError('A runtime control is already pending')
            future = Future()
            self.control_update = dict(action=action, value=value, future=future)
        future.result()

    def _poll_control_update(self):
        with self.lock:
            request, self.control_update = self.control_update, None
        if request is None:
            return
        try:
            value = request['value']
            if request['action'] == 'names':
                self.player_names.configure_enabled(value)
                self.config['player_names']['enabled'] = value
            else:
                session = self.engine.session
                session.trackers[value].reset()
                key = f'p{value+1}_score'
                if session.info['score'] is not None:
                    session.info['score'][key] = -1 if session.info['players'][value] else None
                with self.lock:
                    self.accepted_wall[value] = None
                    if self.result:
                        self.result['published'] = deepcopy(session.info)
                        self.result['decisions'][key] = 'reset'
            self._publish(self.engine.session.info)
        except Exception as error:
            request['future'].set_exception(error)
        else:
            request['future'].set_result(None)

    def configure_results(self, settings):
        """Apply operator controls on the recognition worker without resetting gameplay."""
        from ddrcv.apps.driver_config import validate_config
        allowed = {'enabled', 'discord', 'webhook', 'parse_names', 'screenshots_only', 'output_directory', 'include_player_names'}
        if set(settings) - allowed:
            raise ValueError('Only Results tab settings can change during capture')
        with self.lock:
            if self.phase != 'Running' or self.stop_requested.is_set():
                raise ValueError('Wait for the driver to be running before applying results settings')
            if self.results_update:
                raise ValueError('Results settings are already being applied')
            candidate = deepcopy(self.config)
            candidate['results'].update(settings)
            validated = validate_config(candidate)['results']
            future = Future()
            self.results_update = dict(config=validated, future=future)
        future.result()

    def _poll_results_update(self):
        with self.lock:
            request, self.results_update = self.results_update, None
        if request is None:
            return
        previous = self.config['results']
        try:
            config = request['config']
            if self.results is not None:
                self.results.configure(**config)
            elif config['enabled']:
                from ddrcv.results.service import ResultsService
                factory = self.results_factory or ResultsService
                service = factory(config['outbox_directory'], config, notify=self._publish_results_status)
                try:
                    self._reset_results_source(service)
                except Exception:
                    service.close()
                    raise
                self.results = service
            self.config['results'] = deepcopy(config)
            self.results_error = None
            self._publish_results_status()
        except Exception as error:
            self.config['results'] = previous
            request['future'].set_exception(error)
        else:
            request['future'].set_result(None)

    def _reset_results_source(self, service=None):
        from ddrcv.results.service import source_identity
        kind, source = next(iter(self.config['ingest'].items()))
        identity, recorded = source_identity(dict(kind=kind, path=source.get('path', '')))
        service = self.results if service is None else service
        service.reset(identity, recorded, self.config.get('score_mode',
                           'money' if self.config.get('score_filter', {}).get('max_per_frame', 12) is None else 'ex'))

    def _start_results(self):
        if not self.config.get('results', {}).get('enabled', False):
            return
        from ddrcv.results.service import ResultsService
        try:
            factory = self.results_factory or ResultsService
            config = self.config['results']
            self.results = factory(config.get('outbox_directory', '.workbench/results'), config,
                                   notify=self._publish_results_status)
            self._reset_results_source()
        except Exception as error:
            from ddrcv.results.delivery import redact_error
            self.results_error = redact_error(error, self.config['results'].get('webhook'))
            self.log.exception('Results service could not start')
            if self.results is not None:
                self.results.close()
                self.results = None

    def _publish(self, info=None, integrations=None):
        with self.feed_lock:
            if not self.feed_active:
                return
            if info is not None:
                self.latest_info = deepcopy(info)
            if integrations is not None:
                self.feed_integrations = integrations
            message = deepcopy(self.latest_info)
            message['player_names'] = (self.player_names.snapshot() if self.player_names is not None
                                       else dict(p1=None, p2=None))
            if self.results is not None:
                message['results'] = self.results.feed_status()
            elif self.results_error:
                message['results'] = dict(phase='failed', error=self.results_error)
            self.latest_message = deepcopy(message)
            self.publisher.send_message(message)
            if self.feed_integrations:
                self.integrations.update(message)

    def _stop_names(self):
        if self.player_names is not None:
            self.player_names.close()

    def _publish_results_status(self):
        # Delivery can complete during capture loss; publish the latest confirmed
        # game state plus the updated durable results status without another frame.
        self._publish()

    def _stop_results(self):
        try:
            if self.results is not None:
                self.results.close()
        finally:
            with self.feed_lock:
                self.feed_active = False

    def _results_workers(self):
        if self.results is None:
            return ()
        return tuple(worker for worker in (self.results.worker, self.results.persistence_worker,
                     self.results.outbox.worker) if isinstance(worker, threading.Thread))

    def stop(self):
        self.stop_requested.set()
        if self.thread:
            self.thread.join(timeout=30)
            if self.thread.is_alive():
                raise RuntimeError('Driver shutdown is still pending; wait before restarting')
            for worker in (self.capture_thread, self.integrations.thread, *self._results_workers(),
                           self.player_names.worker if self.player_names is not None else None,
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
            # Recent completed frames: playback/capture waits affect throughput,
            # but only active frame work contributes to processing capacity.
            times = [t for t in self.frame_times if wall - t <= 2]
            fps = (len(times) - 1) / (wall - times[0]) if len(times) > 1 and wall > times[0] else 0
            durations = [duration for t, duration in self.processing_times if wall - t <= 2]
            mean_seconds = sum(durations) / len(durations) if durations else 0
            active = self.phase == 'Running' and frame_age is not None and frame_age <= 1
            source_fps = self.fetcher.fps if isinstance(self.fetcher, FileSource) and self.fetcher.kind == 'video' else None
            snapshot = dict(phase=self.phase, error=self.error, sequence=self.sequence,
                            source=deepcopy(self.config['ingest']), source_revision=self.source_revision,
                            source_switching=self.source_switch is not None, source_error=self.source_error,
                            published=deepcopy(self.result['published'] if self.result else self.engine.session.info),
                            raw_state=self.result['raw_state'] if self.result else 'unknown',
                            raw_scores=deepcopy(self.result['raw_scores']) if self.result else None,
                            decisions=deepcopy(self.result['decisions']) if self.result else {},
                            frame_age=frame_age, capture_stale=frame_age is None or frame_age > 1,
                            score_age=[None if t is None else wall - t for t in self.accepted_wall],
                            fps=round(fps, 1) if active else 0, processing_ms=round(self.processing_ms, 2),
                            processing_avg_ms=round(mean_seconds * 1000, 2) if active and mean_seconds > 0 else None,
                            processing_fps=round(1 / mean_seconds, 1) if active and mean_seconds > 0 else None,
                            source_fps=round(source_fps, 2) if source_fps else None,
                            publisher=self.publisher.status)
        if self.results is not None:
            snapshot['results'] = self.results.feed_status()
            snapshot['published']['results'] = deepcopy(snapshot['results'])
        elif self.results_error:
            snapshot['results'] = dict(phase='failed', error=self.results_error)
        snapshot.update(self.integrations.status())
        with self.feed_lock:
            snapshot['published'] = deepcopy(self.latest_message)
            if self.player_names is not None:
                snapshot['player_name_status'] = self.player_names.status()
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
