from flask import Blueprint, render_template, request, jsonify
from ddrcv.publish.websocket_publisher import WebSocketPublisher
import logging

bp = Blueprint('main', __name__)

# Global instance of WebSocketPublisher
publisher = None
logger = logging.getLogger("WebSocketPublisher")


@bp.route('/')
def index():
    """Renders the HTML page."""
    return render_template('index.html')


@bp.route('/start', methods=['POST'])
def start():
    """Starts the WebSocketPublisher with the given port."""
    global publisher

    port = request.json.get('port')
    if not port:
        return jsonify({'status': 'error', 'message': 'Port is required'}), 400

    # Stop any existing publisher
    if publisher:
        publisher.stop()

    # Start a new publisher on the specified port
    publisher = WebSocketPublisher(host='0.0.0.0', port=int(port), delay=0.1, logger=logger, only_send_new=False)
    publisher.start()

    return jsonify({'status': 'success', 'message': f'WebSocketPublisher started on port {port}'})


@bp.route('/stop', methods=['POST'])
def stop():
    """Stops the WebSocketPublisher."""
    global publisher

    if publisher:
        publisher.stop()
        publisher = None
        return jsonify({'status': 'success', 'message': 'WebSocketPublisher stopped'})

    return jsonify({'status': 'error', 'message': 'WebSocketPublisher is not running'})


@bp.route('/set_state', methods=['POST'])
def set_state():
    """Sets the current state to be sent via WebSocketPublisher."""
    global publisher

    if not publisher:
        return jsonify({'status': 'error', 'message': 'WebSocketPublisher is not running'}), 400

    state = request.json.get('state')
    if not state:
        return jsonify({'status': 'error', 'message': 'State is required'}), 400

    message = {'state': state}
    publisher.send_message(message)
    return jsonify({'status': 'success', 'current_state': state})


@bp.route('/status', methods=['GET'])
def status():
    """Returns the WebSocketPublisher status."""
    global publisher

    return jsonify({'is_running': publisher is not None})
