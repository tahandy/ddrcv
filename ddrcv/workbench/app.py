"""Small local Flask surface; plain forms/JSON and JPEG previews."""
import threading
import time

from flask import Flask, Response, jsonify, render_template, request, send_file

from ddrcv.workbench.controller import Workbench, redact


def create_app(workbench=None):
    app = Flask(__name__)
    wb = workbench or Workbench()
    app.config['WORKBENCH'] = wb
    integration_lock = threading.RLock()

    @app.errorhandler(Exception)
    def error(error):
        from werkzeug.exceptions import HTTPException
        return jsonify(error=str(error)), error.code if isinstance(error, HTTPException) else 400

    @app.before_request
    def local_controls():
        if request.method == 'POST' and request.headers.get('X-Rehearsal') != '1':
            return jsonify(error='Use the local rehearsal panel for control requests'), 403

    @app.get('/')
    def index():
        return render_template('index.html')

    @app.get('/api/panel')
    def panel():
        lifetime = app.config.get('PANEL_LIFETIME')
        if lifetime is None:
            return Response(status=204)

        def events():
            if not lifetime.connect():
                return
            try:
                while not wb.closed.is_set():
                    # A server heartbeat detects closed/crashed browser tabs even
                    # when background-page JavaScript timers are throttled.
                    yield ': panel connected\n\n'
                    if wb.closed.wait(1):
                        break
            finally:
                lifetime.disconnect()

        return Response(events(), mimetype='text/event-stream', headers={'Cache-Control': 'no-store'})

    @app.get('/api/status')
    def status():
        return jsonify(wb.status())

    @app.post('/api/action')
    def action():
        args = dict(request.get_json())
        action = args.pop('action')
        if action == 'song_info':
            return jsonify(wb.catalog_preparation.describe(args['config']))
        if action in ('song_prepare', 'song_refresh', 'song_check'):
            return jsonify(wb.catalog_preparation.start(args['config'],
                           prepare=action != 'song_check', refresh=action == 'song_refresh'))
        if action == 'song_lookup':
            return jsonify(wb.configure_song_lookup(args['config']))
        return jsonify(wb.submit(action, **args))

    @app.get('/api/results/<event_id>/screenshot')
    def results_screenshot(event_id):
        # Resolve only recorded IDs, never a user-provided filesystem path.
        with wb.results.outbox.lock:
            record = wb.results.outbox.records.get(event_id)
            if record is None:
                return jsonify(error='Unknown result event'), 404
            path = wb.results.outbox.directory / event_id / 'screenshot.png'
        return send_file(path, mimetype='image/png')

    @app.get('/api/cameras')
    def cameras():
        import cv2
        from cv2_enumerate_cameras import enumerate_cameras
        return jsonify([dict(index=camera.index, name=camera.name) for camera in enumerate_cameras(cv2.CAP_DSHOW)])

    @app.get('/api/logs')
    def logs():
        lines = list(wb.logs.lines)
        renderer_log = wb.data_dir / 'renderer.log'
        if renderer_log.exists():
            lines += ['--- Renderer ---'] + renderer_log.read_text(encoding='utf-8', errors='replace').splitlines()[-80:]
        secret = wb.settings['obs'].get('password', '')
        if secret:
            lines = [line.replace(secret, '[redacted]') for line in lines]
        return jsonify(redact(lines))

    @app.post('/api/browse')
    def browse():
        args = request.get_json()
        return jsonify(path=wb.browse_path(args.get('directory', False), args.get('catalog', False)))

    @app.get('/frame.jpg')
    def frame():
        image, sequence = wb.image(request.args.get('view', 'annotated'))
        if image is None:
            return Response(status=204)
        return Response(image, mimetype='image/jpeg', headers={'Cache-Control': 'no-store', 'X-Frame-Sequence': str(sequence)})

    @app.get('/stream.mjpg')
    def stream():
        view = request.args.get('view', 'clean')
        if view not in ('clean', 'monitored'):
            raise ValueError('Stream view must be clean or monitored')
        def generate():
            import cv2
            import numpy as np
            blank = cv2.imencode('.jpg', np.zeros((720, 1280, 3), dtype=np.uint8))[1].tobytes()
            sequence, deadline, last_sent = -1, 0, 0
            while not wb.closed.is_set():
                changed = wb.wait_for_frame(sequence, timeout=.5)
                if wb.closed.is_set():
                    break
                if not changed and time.perf_counter() - last_sent < 2:
                    continue
                delay = deadline - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
                began = time.perf_counter()
                image, sequence = wb.image(view)
                image = image if image is not None else blank
                yield (b'--frame\r\nContent-Type: image/jpeg\r\nX-Frame-Sequence: ' + str(sequence).encode()
                       + b'\r\nContent-Length: ' + str(len(image)).encode() + b'\r\n\r\n' + image + b'\r\n')
                # New frames wake viewers immediately. A small paused heartbeat
                # detects disconnected browser tabs without re-sending at 30 Hz.
                deadline = began + 1 / 30
                last_sent = time.perf_counter()
        return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame', headers={'Cache-Control': 'no-store'})

    @app.get('/video')
    def video():
        return '<!doctype html><html><head><title>DDRCV clean video</title><style>html,body{margin:0;background:black;overflow:hidden;width:100%;height:100%}img{width:100%;height:100%;object-fit:contain}</style></head><body><img src="/stream.mjpg" alt=""></body></html>'

    @app.post('/api/snapshot')
    def snapshot():
        return jsonify(wb.submit('snapshot'))

    @app.post('/api/checks')
    def checks():
        return jsonify(wb.checks())

    @app.post('/api/renderer')
    def renderer():
        values = request.get_json()
        with integration_lock:
            if values['action'] == 'start':
                return jsonify(wb.start_renderer(values.get('path')))
            wb.stop_renderer()
        return jsonify(ok=True)

    @app.route('/api/obs', methods=['GET', 'POST'])
    def obs():
        if request.method == 'GET':
            return jsonify(wb.obs.status)
        values = dict(request.get_json())
        action = values.pop('action')
        if action == 'connect':
            return jsonify(wb.configure_obs(values))
        if action == 'automation':
            wb.obs.automate(bool(values['enabled']))
        elif action == 'scene':
            wb.obs.manual_scene(values['name'])
        elif action == 'disconnect':
            wb.obs.disconnect()
        elif action == 'check':
            return jsonify(wb.obs.validate())
        else:
            raise ValueError('Unknown OBS control')
        return jsonify(wb.obs.status)

    @app.post('/api/shutdown')
    def shutdown():
        callback = app.config.get('SHUTDOWN')
        if callback:
            threading.Thread(target=callback, daemon=True).start()
        return jsonify(ok=True)

    return app
