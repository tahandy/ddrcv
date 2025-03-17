from flask import Flask
from app.obs_controller import obs_blueprint

# Initialize Flask app
app = Flask(__name__)

# Register the OBS blueprint
app.register_blueprint(obs_blueprint, url_prefix="/obs")

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=4999, debug=True)
