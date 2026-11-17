"""Gunicorn entrypoint for the deployed Flask application."""

import os

from app import create_app

application = create_app(os.environ.get("HARMONIZER_CONFIG"))
app = application
