import argparse
import json

from flask import Flask
from app.obs_controller import obs_blueprint

# Initialize Flask app
app = Flask(__name__)

parser = argparse.ArgumentParser(description='OBS Controller')
parser.add_argument('game', type=str, choices=['ddr', 'sdvx'], help='Game name')
parser.add_argument('config', type=str, help='JSON config file')
parser.add_argument('--host', type=str, default='0.0.0.0', help='Host address')
parser.add_argument('--port', type=int, default=5001, help='Port number')
parser.add_argument('--debug', action='store_true', help='Enable debug mode')
args = parser.parse_args()

with open(args.config, "r") as f:
    config_data = json.load(f)
    app.config.update(config_data)

if args.game == "ddr":
    from handler_ddr import handle_state_change
    app.config["state_handler"] = handle_state_change
elif args.game == "sdvx":
    from handler_sdvx import handle_state_change
    app.config["state_handler"] = handle_state_change
else:
    raise NotImplementedError(f"Unexpected game: {app.config['GAME']}. Expected 'ddr' or 'sdvx'.")

# Register the OBS blueprint
app.register_blueprint(obs_blueprint, url_prefix="/obs")
# app.register_blueprint(obs_blueprint)

if __name__ == "__main__":
    app.run(host=args.host, port=args.port, debug=args.debug)
