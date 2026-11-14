"""Structured API errors."""

from __future__ import annotations

from typing import Any

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException


class ApiError(Exception):
    """An error that maps directly to a structured JSON response."""

    def __init__(
        self,
        code: str,
        message: str,
        status: int = 400,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details


def error_response(code: str, message: str, status: int, details: Any = None):
    """Build the standard error envelope."""
    payload: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details is not None:
        payload["error"]["details"] = details
    return jsonify(payload), status


def register_error_handlers(app: Flask) -> None:
    """Register JSON error handlers (never return HTML for API routes)."""

    @app.errorhandler(ApiError)
    def handle_api_error(error: ApiError):
        return error_response(error.code, error.message, error.status, error.details)

    @app.errorhandler(HTTPException)
    def handle_http_error(error: HTTPException):
        code = (error.name or "http_error").lower().replace(" ", "_")
        return error_response(code, error.description or "", error.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(error: Exception):
        app.logger.exception("Unhandled error")
        return error_response("internal_error", str(error), 500)
