from flask import render_template


def register_routes(app):
    """ Register app routes. """
    @app.route('/')
    def index():
        return render_template('index.html')
