import threading
import asyncio
import time
import websockets
import json
from flask import Blueprint, request, jsonify, render_template, Response
from obsws_python import ReqClient

# OBS WebSocket Configuration
OBS_HOST = "localhost"
OBS_PORT = 4455
OBS_PASSWORD = "6s0sjd7n1M1ybhb1"

# External WebSocket Server
STATE_SERVER_URI = "ws://localhost:9000"

# OBS Client Initialization
obs_client = ReqClient(host=OBS_HOST, port=OBS_PORT, password=OBS_PASSWORD)

# Shared State
manual_override = False
ws_connected = False
ws_thread = None
polling_thread = None
previous_state = {"state": "unknown"}
current_state = {"state": "unknown"}
active_scene = None
lock = threading.Lock()

# Define the blueprint
obs_blueprint = Blueprint("obs", __name__, template_folder="templates")


# Function to connect to the external WebSocket server
async def connect_to_websocket():
    global ws_connected, previous_state, current_state
    try:
        async with websockets.connect(STATE_SERVER_URI) as websocket:
            ws_connected = True
            while ws_connected:
                raw_message = await websocket.recv()
                try:
                    # Ensure the message is a dictionary
                    if isinstance(raw_message, str):
                        message = json.loads(raw_message)
                    elif isinstance(raw_message, dict):
                        message = raw_message
                    else:
                        print(f"Invalid message format: {raw_message}")
                        continue

                    # Process the new state
                    if "state" in message:
                        with lock:
                            previous_state = current_state
                            current_state = message
                        handle_state_change(previous_state, current_state)
                    else:
                        print(f"Missing 'state' key in message: {message}")
                except json.JSONDecodeError as e:
                    print(f"Error decoding WebSocket message: {e}")
    except Exception as e:
        print(f"WebSocket Error: {e}")
    finally:
        ws_connected = False


# Function to handle state changes and update OBS
def handle_state_change(prev, curr):
    global obs_client, manual_override
    prev_tag = prev.get("state", "unknown")
    curr_tag = curr.get("state", "unknown")

    # State-to-Scene Mapping
    # target_scene = None
    # if prev_tag == "song_select" and prev_tag != curr_tag:
    #     target_scene = "Gameplay"
    # elif prev_tag == "results" and prev_tag != curr_tag:
    #     target_scene = "Commentator"
    scene_map = {'unknown': 'Scene - Unknown',
                 'entry': 'Scene - Entry',
                 'gameplay': 'Scene - Gameplay',
                 'song_select': 'Scene - Song Select',
                 'song_result': 'Scene - Song Result',
                 'total_result': 'Scene - Total Result'}

    target_scene = scene_map.get(curr_tag, None)

    # If a target scene is found, respect the manual override
    if target_scene:
        if manual_override:
            print("Manual override enabled; ignoring WebSocket state changes.")
            return

        try:
            obs_client.set_current_program_scene(target_scene)
            print(f"Scene switched to: {target_scene}")
        except Exception as e:
            print(f"Error switching scene: {e}")


# Function to start the WebSocket connection in a background thread
def start_websocket_connection():
    global ws_thread
    if ws_thread and ws_thread.is_alive():
        return
    ws_thread = threading.Thread(target=asyncio.run, args=(connect_to_websocket(),), daemon=True)
    ws_thread.start()


# Function to stop the WebSocket connection
def stop_websocket_connection():
    global ws_connected
    ws_connected = False


# Function to poll OBS for the active scene
def poll_active_scene():
    global active_scene
    while True:
        try:
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
    scene_name = request.json.get("scene_name")
    if scene_name:
        try:
            obs_client.set_current_program_scene(scene_name)
            return jsonify(success=True)
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
