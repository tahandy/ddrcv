import json

from flask import Flask, Blueprint, render_template, request, jsonify
from obsws_python import ReqClient
import threading
import asyncio
import websockets

# OBS WebSocket configuration
OBS_HOST = "localhost"
OBS_PORT = 4455
OBS_PASSWORD = "6s0sjd7n1M1ybhb1"

# External WebSocket server configuration
STATE_SERVER_URI = "ws://localhost:9000"

# Flask app initialization
app = Flask(__name__)

# Define the blueprint
obs_blueprint = Blueprint("obs", __name__)

# Persistent OBS client with thread lock
obs_client = None
client_lock = threading.Lock()

# Manual override state
manual_override = False
manual_override_lock = threading.Lock()

# WebSocket connection management
ws_connection_status = {"connected": False}
ws_thread = None
ws_previous_state = dict(state='unknown')
ws_current_state = dict(state='unknown')


def get_obs_client():
    """Get or initialize the persistent OBS WebSocket client."""
    global obs_client
    with client_lock:
        if obs_client is None:
            obs_client = ReqClient(host=OBS_HOST, port=OBS_PORT, password=OBS_PASSWORD)
        return obs_client


async def connect_to_state_server():
    """Connect to the external WebSocket server and process state updates."""
    global ws_connection_status, ws_previous_state, ws_current_state
    try:
        async with websockets.connect(STATE_SERVER_URI) as websocket:
            ws_connection_status["connected"] = True
            while ws_connection_status["connected"]:
                state = await websocket.recv()
                if state != 'null':
                    with manual_override_lock:
                        if not manual_override:
                            if isinstance(state, str):
                                state = json.loads(state)
                            ws_previous_state = ws_current_state
                            ws_current_state = state
                            handle_state_change(ws_previous_state, ws_current_state)
    except Exception as e:
        print(f"Error in WebSocket connection: {e}")
    finally:
        ws_connection_status["connected"] = False


def handle_state_change(prev, curr):
    """Handle logic to switch scenes based on the dynamic state."""
    prev_tag = prev['state']
    curr_tag = curr['state']

    target_scene = None
    if prev_tag == 'song_select' and curr_tag in ('unknown', 'song_splash'):
        target_scene = 'Gameplay'

    if prev_tag == 'results' and curr_tag in ('unknown', 'song_select'):
        target_scene = 'Commentator'

    if target_scene is not None:
        print(prev, curr)
        print('target scene: ', target_scene)


    if target_scene is not None:
        try:
            client = get_obs_client()
            client.set_current_program_scene(target_scene)
        except Exception as e:
            print(f"Error handling state change: {e}")


def start_ws_connection():
    """Start the WebSocket connection in a background thread."""
    global ws_thread
    if ws_thread and ws_thread.is_alive():
        return
    ws_thread = threading.Thread(target=asyncio.run, args=(connect_to_state_server(),), daemon=True)
    ws_thread.start()


def stop_ws_connection():
    """Stop the WebSocket connection."""
    global ws_connection_status
    ws_connection_status["connected"] = False


@obs_blueprint.route("/", methods=["GET"])
def index():
    """Render the main page with the scene list, active scene, and connection status."""
    global manual_override, ws_connection_status
    try:
        client = get_obs_client()
        scenes_response = client.get_scene_list()
        scenes = scenes_response.scenes
        active_scene_response = client.get_current_program_scene()
        active_scene = active_scene_response.current_program_scene_name
    except Exception as e:
        print("Error retrieving scenes or active scene:", e)
        scenes = []
        active_scene = "Unknown"
    return render_template(
        "index.html",
        scenes=scenes,
        active_scene=active_scene,
        manual_override=manual_override,
        ws_connected=ws_connection_status["connected"],
    )


@obs_blueprint.route("/toggle_override", methods=["POST"])
def toggle_override():
    """Toggle the manual override."""
    global manual_override
    with manual_override_lock:
        manual_override = not manual_override
    return jsonify(success=True, manual_override=manual_override)


@obs_blueprint.route("/ws_control", methods=["POST"])
def ws_control():
    """Start, stop, or restart the WebSocket connection."""
    action = request.json.get("action")
    if action == "start":
        start_ws_connection()
    elif action == "stop":
        stop_ws_connection()
    elif action == "restart":
        stop_ws_connection()
        start_ws_connection()
    return jsonify(success=True, connected=ws_connection_status["connected"])


@obs_blueprint.route("/switch_scene", methods=["POST"])
def switch_scene():
    """Switch to a selected scene."""
    scene_name = request.json.get("scene_name")
    if scene_name:
        try:
            client = get_obs_client()
            client.set_current_program_scene(scene_name)
            return jsonify(success=True)
        except Exception as e:
            print(f"Error switching scene: {e}")
            return jsonify(success=False, error=str(e)), 500
    return jsonify(success=False, error="No scene name provided"), 400


@obs_blueprint.route("/update_text", methods=["POST"])
def update_text():
    """Update text in a specified text element."""
    text_element = request.json.get("text_element")
    value = request.json.get("value")
    if text_element and value:
        try:
            client = get_obs_client()
            client.set_input_settings(input_name=text_element, input_settings={"text": value})
            return jsonify(success=True)
        except Exception as e:
            print(f"Error updating text: {e}")
            return jsonify(success=False, error=str(e)), 500
    return jsonify(success=False, error="Missing text element or value"), 400


@app.teardown_appcontext
def disconnect_obs_client(exception=None):
    """Disconnect the persistent OBS WebSocket client on app teardown."""
    global obs_client
    with client_lock:
        if obs_client is not None:
            obs_client.disconnect()
            obs_client = None