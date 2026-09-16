import threading
import asyncio
import time
import websockets
import json
from flask import Blueprint, request, jsonify, render_template, Response, current_app
from obsws_python import ReqClient
from ddrcv.publish.obs_service import OBSService

try:
    from ..state_stream import consume_states
except ImportError:  # apps/obs is the import root for the command-line launcher.
    from state_stream import consume_states

obs_client = None
obs_service = None
STATE_SERVER_URI = None


# Shared State
manual_override = False
ws_connected = False
ws_thread = None
polling_thread = None
previous_state = {"state": "unknown"}
current_state = {"state": "unknown"}
active_scene = None
handle_state_change = lambda *x: print('Handler not implemented')
lock = threading.RLock()
obs_lock = threading.RLock()
ws_stop = threading.Event()
ws_enabled = False

# Define the blueprint
obs_blueprint = Blueprint("obs", __name__, template_folder="templates")

@obs_blueprint.record_once
def on_load(state):
    global STATE_SERVER_URI
    global obs_client, obs_service
    global handle_state_change
    app = state.app
    obs_client = ReqClient(host=app.config.get('OBS_HOST'),
                           port=app.config.get('OBS_PORT'),
                           password=app.config.get('OBS_PASSWORD'))
    STATE_SERVER_URI = app.config.get('STATE_SERVER_URI')
    handle_state_change = app.config.get('state_handler')
    obs_service = OBSService(client=obs_client, policy=handle_state_change)

def receive_state(message):
    global previous_state, current_state
    # Share the lock with manual controls, so an automatic switch cannot race
    # a desk operator's request to pause automation.
    with lock:
        previous_state, current_state = current_state, message
        with obs_lock:
            obs_service.update(current_state, enabled=not manual_override)


def set_connection_status(connected):
    global ws_connected
    with lock:
        ws_connected = connected


async def connect_to_websocket():
    await consume_states(websockets.connect, STATE_SERVER_URI, ws_stop,
                         receive_state, set_connection_status)


def run_state_feed():
    global ws_thread
    try:
        asyncio.run(connect_to_websocket())
    finally:
        with lock:
            ws_thread = None
            # A quick Stop/Start can arrive while the previous worker exits.
            if ws_enabled:
                start_websocket_connection()


def start_websocket_connection():
    global ws_thread, ws_enabled
    with lock:
        ws_enabled = True
        ws_stop.clear()
        if ws_thread and ws_thread.is_alive():
            return
        ws_thread = threading.Thread(target=run_state_feed, daemon=True)
        ws_thread.start()


def stop_websocket_connection():
    global ws_connected, ws_enabled
    with lock:
        ws_enabled = False
        ws_connected = False
        ws_stop.set()


# Function to poll OBS for the active scene
def poll_active_scene():
    global active_scene
    while True:
        try:
            with obs_lock:
                scene_info = obs_client.get_current_program_scene()
            with lock:
                active_scene = scene_info.current_program_scene_name
        except Exception as e:
            print(f"Error polling active scene: {e}")
        time.sleep(1)  # Poll every second


# Start polling thread
def start_polling():
    global polling_thread
    if polling_thread and polling_thread.is_alive():
        return
    polling_thread = threading.Thread(target=poll_active_scene, daemon=True)
    polling_thread.start()


# Blueprint Routes
@obs_blueprint.route("/")
def index():
    global manual_override, ws_connected, active_scene, current_state
    with obs_lock:
        scenes = obs_client.get_scene_list().scenes
    scenes = reversed(scenes)
    with lock:
        current_active_scene = active_scene
    return render_template(
        "index.html",
        scenes=[scene["sceneName"] for scene in scenes],
        active_scene=current_active_scene,
        manual_override=manual_override,
        ws_connected=ws_connected,
        current_state=current_state["state"],
    )


@obs_blueprint.route("/switch_scene", methods=["POST"])
def switch_scene():
    global manual_override
    scene_name = request.json.get("scene_name")
    if scene_name:
        try:
            with lock:
                manual_override = True
                with obs_lock:
                    obs_service.manual_scene(scene_name)
            return jsonify(success=True, manual_override=True)
        except Exception as e:
            return jsonify(success=False, error=str(e)), 500
    return jsonify(success=False, error="No scene name provided"), 400


# Streaming function for Server-Sent Events
def event_stream():
    global manual_override, ws_connected, active_scene
    while True:
        with lock:
            data = {
                "active_scene": active_scene,
                "ws_connected": ws_connected,
                "manual_override": manual_override,
                "state": current_state.get("state", "unknown"),
                "ws_enabled": ws_enabled,
                "automation_error": getattr(handle_state_change, "last_error", None),
            }
        yield f"data: {json.dumps(data)}\n\n"
        time.sleep(1)  # Send updates every second

@obs_blueprint.route("/events")
def events():
    return Response(event_stream(), content_type="text/event-stream")


@obs_blueprint.route("/toggle_override", methods=["POST"])
def toggle_override():
    global manual_override
    with lock:
        manual_override = not manual_override
    return jsonify(success=True, manual_override=manual_override)

@obs_blueprint.route("/report_override", methods=["GET"])
def report_override():
    global manual_override
    with lock:
        if manual_override:
            return jsonify(success=True, automation_on=0)
        else:
            return jsonify(success=True, automation_on=1)


@obs_blueprint.route("/report_websocket", methods=["GET"])
def report_websocket():
    global ws_connected
    with lock:
        return jsonify(success=True, ws_connected=ws_connected)


@obs_blueprint.route("/toggle_websocket", methods=["POST"])
def toggle_websocket():
    global ws_connected
    with lock:
        if ws_enabled:
            stop_websocket_connection()
        else:
            start_websocket_connection()
    return jsonify(success=True, connected=ws_connected, enabled=ws_enabled)

@obs_blueprint.route("/ws_control", methods=["POST"])
def ws_control():
    action = request.json.get("action")
    if action == "start":
        start_websocket_connection()
    elif action == "stop":
        stop_websocket_connection()
    return jsonify(success=True, connected=ws_connected)


# Initialize background polling when the blueprint is registered
@obs_blueprint.record_once
def start_background_tasks(state):
    start_polling()
    if state.app.config.get("AUTO_CONNECT", True):
        start_websocket_connection()
