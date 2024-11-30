from flask import Flask
from app.obs_controller import obs_blueprint

# Initialize Flask app
app = Flask(__name__)

# Register the OBS blueprint
app.register_blueprint(obs_blueprint, url_prefix="/")

if __name__ == "__main__":
    app.run(port=5001, debug=True)
