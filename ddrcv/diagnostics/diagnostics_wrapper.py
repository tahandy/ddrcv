from gevent import monkey
monkey.patch_all()

import threading
import requests
from flask_socketio import SocketIO
from flask import request

# Use a global variable to track if handlers have been registered
_handlers_registered = False

class DiagnosticsWrapper:
    """ Context manager to wrap around a Flask app and manage the Flask-SocketIO diagnostics server. """
    def __init__(self, app, logger, host='127.0.0.1', port=5000):
        global _handlers_registered
        self.app = app
        self.logger = logger
        self.host = host
        self.port = port
        self.socketio = SocketIO(app)
        self.flask_thread = None

        # Attach the WebSocket handler to the logger
        self.logger.add_websocket_handler(self.socketio)

        # Register default events if not already done
        if not _handlers_registered:
            self._register_default_socketio_events()
            _handlers_registered = True

        # Add a custom shutdown route
        @app.route('/shutdown', methods=['POST'])
        def shutdown():
            """ Shutdown the Flask server. """
            if request.remote_addr == '127.0.0.1':  # Only allow shutdown from localhost
                func = request.environ.get('werkzeug.server.shutdown')
                if func:
                    func()  # Trigger the Werkzeug server shutdown
                return "Server shutting down..."
            else:
                return "Shutdown can only be requested from localhost.", 403

    def _register_default_socketio_events(self):
        """ Register default SocketIO events, such as 'connect'. """
        @self.socketio.on('connect')
        def handle_connect():
            """ Handle a new WebSocket connection. Send the last 10 logs to the client. """
            print(f"New client connected with SID {request.sid}. Sending buffered logs only to this client.")
            for log_message in self.logger.get_recent_logs():
                # Send the logs only to the newly connected client
                self.socketio.emit('log_message', {'message': log_message}, to=request.sid)

    def __enter__(self):
        """ Start the Flask server in a separate thread. """
        self.flask_thread = threading.Thread(target=lambda: self.socketio.run(self.app, host=self.host, port=self.port, debug=False, use_reloader=False, allow_unsafe_werkzeug=True))
        self.flask_thread.start()
        print(f"Diagnostics server started on http://{self.host}:{self.port}")
        return self.logger.get_logger()

    def __exit__(self, exc_type, exc_value, traceback):
        """ Gracefully shut down the Flask server when the context exits. """
        print("Shutting down diagnostics server...")

        # Use a POST request to trigger the shutdown endpoint
        try:
            response = requests.post(f'http://{self.host}:{self.port}/shutdown')
            if response.status_code == 200:
                print("Server shutdown initiated successfully via Werkzeug.")
            else:
                print(f"Failed to initiate server shutdown. Status Code: {response.status_code}")
        except Exception as e:
            print(f"Error during shutdown request: {e}")

        # Use socketio.stop() to stop the SocketIO server completely
        print("Calling socketio.stop() to stop SocketIO server...")
        self.socketio.stop()

        # Ensure the Flask server thread completes before exiting
        self.flask_thread.join()
        print("Diagnostics server shut down.")
