from flask import Flask
from .obs_controller import obs_blueprint

def create_app():
    app = Flask(__name__)
    app.register_blueprint(obs_blueprint, url_prefix="/")
    return app
