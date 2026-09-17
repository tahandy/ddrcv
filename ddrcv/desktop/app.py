"""Authenticated loopback control surface; no streaming endpoint."""
import hmac
import json

from flask import Flask, Response, jsonify, render_template, request
from werkzeug.exceptions import HTTPException


def create_app(desk, token, open_panel=None, shutdown=None):
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024

    @app.before_request
    def authenticate():
        if request.host.split(':')[0] not in ('127.0.0.1', 'localhost'):
            return jsonify(error='Loopback host required'), 403
        if request.path.startswith('/api/'):
            if not hmac.compare_digest(request.headers.get('X-Desk-Token', ''), token):
                return jsonify(error='Invalid desk session'), 403
            origin = request.headers.get('Origin')
            if origin and origin != request.host_url.rstrip('/'):
                return jsonify(error='Invalid request origin'), 403

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        # pywebview's generated bridge/evaluate_js uses Function/eval. No remote scripts.
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self' 'unsafe-eval'; connect-src 'self'; frame-ancestors 'none'"
        return response

    @app.errorhandler(Exception)
    def error(error):
        if isinstance(error, HTTPException):
            return jsonify(error=error.description), error.code
        return jsonify(error=desk.logs.scrub(str(error))), 400

    @app.get('/')
    def index():
        return render_template('index.html')

    @app.get('/api/status')
    def status():
        return jsonify(desk.status())

    @app.route('/api/config', methods=['GET', 'PUT'])
    def config():
        return jsonify(desk.edit(request.get_json()) if request.method == 'PUT' else desk.config())

    @app.post('/api/config/file')
    def config_file():
        args = request.get_json()
        if args['action'] == 'load':
            return jsonify(desk.load(args['path']))
        if args['action'] == 'save':
            return jsonify(desk.save(args.get('path')))
        raise ValueError('Unknown file action')

    @app.post('/api/action')
    def action():
        args = request.get_json()
        name = args['action']
        if name == 'start':
            return jsonify(desk.start())
        if name == 'stop':
            return jsonify(desk.stop())
        if name == 'switch_source':
            return jsonify(desk.switch_source())
        if name == 'apply':
            return jsonify(desk.apply())
        if name == 'apply_results':
            return jsonify(desk.apply_results())
        if name == 'open':
            if open_panel:
                open_panel()
            return jsonify(ok=True)
        if name == 'exit':
            if args.get('confirmed') is not True:
                raise ValueError('Confirm Exit application first')
            if shutdown:
                shutdown()
            return jsonify(ok=True)
        raise ValueError('Unknown action')

    @app.get('/api/cameras')
    def cameras():
        from cv2_enumerate_cameras import enumerate_cameras
        import cv2
        return jsonify([dict(index=c.index, name=c.name) for c in enumerate_cameras(cv2.CAP_DSHOW)])

    @app.post('/api/integration')
    def integration():
        args = dict(request.get_json())
        return jsonify(desk.integration(args.pop('action'), **args))

    @app.get('/api/logs')
    def logs():
        return jsonify(list(desk.logs.lines))

    @app.get('/api/frame')
    def frame():
        image, metadata = desk.snapshot()
        if image is None:
            return Response(status=204)
        return Response(image, mimetype='image/jpeg', headers={'X-Frame-Metadata': json.dumps(metadata)})

    @app.post('/api/preferences')
    def preferences():
        args = request.get_json()
        with desk.lock:
            for key in ('width', 'height'):
                if key in args:
                    desk.preferences[key] = max(640 if key == 'width' else 480, min(3840, int(args[key])))
            desk._persist()
        return jsonify(ok=True)

    return app
