"""Sanitized, consistent public API error responses."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.domain.schemas import INPUT_RANGES


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    message: str


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    details: list[ErrorDetail] | None = None


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ErrorBody


def internal_error_response() -> JSONResponse:
    """Return a generic 500 response without implementation details."""

    payload = ErrorResponse(
        error=ErrorBody(
            code="INTERNAL_ERROR",
            message="An unexpected error occurred while processing the request.",
        )
    )
    return JSONResponse(status_code=500, content=payload.model_dump(exclude_none=True))


def _field_name(error: dict[str, Any]) -> str:
    location = [str(part) for part in error.get("loc", ()) if part != "body"]
    return ".".join(location) if location else "body"


def _validation_message(field: str, error_type: str) -> str:
    if field in INPUT_RANGES and error_type in {
        "greater_than_equal",
        "less_than_equal",
        "finite_number",
    }:
        minimum, maximum = INPUT_RANGES[field]
        return f"Value must be between {minimum:g} and {maximum:g}."
    if error_type == "missing":
        return "Field is required."
    if error_type == "extra_forbidden":
        return "Unknown field."
    if field == "gear" and error_type == "literal_error":
        return "Value must be 'main' or 'nose'."
    if error_type in {"float_type", "int_type"}:
        return "Value must be a number."
    return "Value is invalid."


def install_error_handlers(app: FastAPI) -> None:
    """Register validation handlers on an application instance."""

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        errors: list[dict[str, Any]] = [dict(error) for error in exc.errors()]
        if any(error.get("type") == "json_invalid" for error in errors):
            payload = ErrorResponse(
                error=ErrorBody(
                    code="MALFORMED_JSON",
                    message="The request body contains malformed JSON.",
                    details=[ErrorDetail(field="body", message="Malformed JSON request body.")],
                )
            )
            return JSONResponse(status_code=400, content=payload.model_dump())

        details = [
            ErrorDetail(
                field=_field_name(error),
                message=_validation_message(_field_name(error), str(error.get("type", ""))),
            )
            for error in errors
        ]
        payload = ErrorResponse(
            error=ErrorBody(
                code="INVALID_INPUT",
                message="One or more calculator inputs are invalid.",
                details=details,
            )
        )
        return JSONResponse(status_code=422, content=payload.model_dump())
