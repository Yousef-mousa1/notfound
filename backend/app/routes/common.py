"""Shared route helpers: validation and response envelopes."""

from __future__ import annotations

from typing import Any, TypeVar

from flask import jsonify, request
from pydantic import BaseModel, ValidationError

from ..errors import ApiError

ModelT = TypeVar("ModelT", bound=BaseModel)


def ok(data: Any, meta: dict[str, Any] | None = None, status: int = 200):
    """Build the standard success envelope."""
    return jsonify({"data": data, "meta": meta or {}}), status


def page_meta(total: int, limit: int, offset: int) -> dict[str, Any]:
    """Pagination metadata."""
    remaining = max(total - offset, 0)
    return {
        "limit": limit,
        "offset": offset,
        "total": total,
        "returned": min(remaining, limit),
    }


def _validation_error(error: ValidationError) -> ApiError:
    return ApiError(
        "validation_error",
        "Invalid request parameters.",
        422,
        error.errors(include_url=False, include_context=False),
    )


def parse_query(
    model: type[ModelT], default_limit: int | None = None
) -> ModelT:
    """Validate query-string parameters against a pydantic model."""
    data: dict[str, Any] = request.args.to_dict()
    if default_limit is not None and "limit" not in data:
        data["limit"] = default_limit
    try:
        return model(**data)
    except ValidationError as error:
        raise _validation_error(error) from error


def parse_body(model: type[ModelT], *, required: bool = True) -> ModelT:
    """Validate a JSON request body against a pydantic model."""
    payload = request.get_json(silent=True)
    if payload is None:
        if required:
            raise ApiError("invalid_body", "A JSON body is required.", 400)
        payload = {}
    if not isinstance(payload, dict):
        raise ApiError("invalid_body", "The JSON body must be an object.", 400)
    try:
        return model(**payload)
    except ValidationError as error:
        raise _validation_error(error) from error
