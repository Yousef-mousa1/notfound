"""Flask application factory.

This module is the thin web layer. It must not contain scientific logic; all
work belongs to the ``harmonizer`` package.
"""

from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify, request

from harmonizer.config import load_config

from .db import init_database
from .errors import register_error_handlers
from .jobs import JobRunner
from .routes.health import health_blueprint
from .routes.ui import ui_blueprint
from .routes.v1.analytics import analytics_blueprint
from .routes.v1.anomalies import anomalies_blueprint
from .routes.v1.dashboard import dashboard_blueprint
from .routes.v1.exports import exports_blueprint
from .routes.v1.harmonization import harmonization_blueprint
from .routes.v1.ingestion import ingestion_blueprint
from .routes.v1.jobs import jobs_blueprint
from .routes.v1.observations import observations_blueprint
from .routes.v1.processing import processing_blueprint
from .routes.v1.validation import validation_blueprint


def create_app(config_path: str | Path | None = None) -> Flask:
    """Create and configure the Flask application.

    Args:
        config_path: Optional path to a YAML config file. Defaults to
            ``config/default.yaml``. Tests pass a config with a temporary
            DuckDB path.

    Returns:
        The configured Flask application.
    """
    app = Flask(__name__)

    config = load_config(config_path)
    app.config["HARMONIZER"] = config
    app.config["HARMONIZER_CONFIG_PATH"] = str(config_path) if config_path else None

    init_database(app)
    app.extensions["job_runner"] = JobRunner(app.extensions["db"], config)
    register_error_handlers(app)

    # CORS: the React frontend (Vite dev server or a separate static host) is
    # served from a different origin than this API. Origins are configured in
    # config/default.yaml -> api.cors_origins.
    allowed_origins = set(
        (config.get("api") or {}).get("cors_origins")
        or ["http://localhost:5173", "http://127.0.0.1:5173"]
    )

    @app.after_request
    def add_cors_headers(response):
        origin = request.headers.get("Origin")
        if origin and origin in allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
            response.headers["Access-Control-Max-Age"] = "600"
        return response

    app.register_blueprint(health_blueprint)
    app.register_blueprint(ui_blueprint)

    prefix = str((config.get("api") or {}).get("prefix") or "/api/v1")
    app.register_blueprint(ingestion_blueprint, url_prefix=prefix)
    app.register_blueprint(observations_blueprint, url_prefix=prefix)
    app.register_blueprint(processing_blueprint, url_prefix=prefix)
    app.register_blueprint(harmonization_blueprint, url_prefix=prefix)
    app.register_blueprint(validation_blueprint, url_prefix=prefix)
    app.register_blueprint(anomalies_blueprint, url_prefix=prefix)
    app.register_blueprint(analytics_blueprint, url_prefix=prefix)
    app.register_blueprint(dashboard_blueprint, url_prefix=prefix)
    app.register_blueprint(exports_blueprint, url_prefix=prefix)
    app.register_blueprint(jobs_blueprint, url_prefix=prefix)

    @app.get("/")
    def index():
        return jsonify(
            {
                "service": "pyroscope-api",
                "api_prefix": prefix,
                "health": "/health",
                "demo": "/demo",
                "groups": [
                    f"{prefix}/ingestion",
                    f"{prefix}/observations",
                    f"{prefix}/processing",
                    f"{prefix}/harmonization",
                    f"{prefix}/validation",
                    f"{prefix}/anomalies",
                    f"{prefix}/analytics",
                    f"{prefix}/dashboard",
                    f"{prefix}/exports",
                    f"{prefix}/jobs",
                ],
            }
        )

    return app
