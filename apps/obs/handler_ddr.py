# Function to handle state changes and update OBS
def handle_state_change(prev, curr, client, override=False):
    prev_tag = prev.get("state", "unknown")
    curr_tag = curr.get("state", "unknown")

    # State-to-Scene Mapping
    target_scene = None
    if prev_tag == "song_select" and prev_tag != curr_tag:
        target_scene = "Gameplay"
    elif prev_tag == "results" and prev_tag != curr_tag:
        target_scene = "Commentator"

    # If a target scene is found, respect the manual override
    if target_scene:
        if override:
            print("Manual override enabled; ignoring WebSocket state changes.")
            return

        try:
            client.set_current_program_scene(target_scene)
            print(f"Scene switched to: {target_scene}")
        except Exception as e:
            print(f"Error switching scene: {e}")