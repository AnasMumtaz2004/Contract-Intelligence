import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.logging import get_request_id

logger = logging.getLogger("app.errors")

# A short code for each status, so a program does not have to read the message text
ERROR_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "too_large",
    422: "invalid_input",
    429: "rate_limited",
}


def make_error_response(status_code: int, message: str, headers: dict | None = None) -> JSONResponse:
    """Build the error response that every error of the API uses."""
    code = ERROR_CODES.get(status_code, "error")
    if status_code >= 500:
        code = "server_error"

    body = {"detail": message, "code": code, "request_id": get_request_id()}
    return JSONResponse(status_code=status_code, content=body, headers=headers)


async def handle_http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
    """Handle the errors that we raise on purpose, like 404 and 401."""
    message = error.detail
    if not isinstance(message, str):
        message = "The request could not be completed."
    return make_error_response(error.status_code, message, getattr(error, "headers", None))


def describe_validation_error(error: RequestValidationError) -> str:
    """Turn the first validation problem into one readable sentence, like 'password: String should have at least 8 characters'."""
    problems = error.errors()
    if len(problems) == 0:
        return "The request is not valid."

    first = problems[0]
    parts = []
    for part in first.get("loc", []):
        if part in ("body", "query", "path", "form"):
            continue
        parts.append(str(part))

    message = first.get("msg", "Invalid value")
    if len(parts) > 0:
        return ".".join(parts) + ": " + message
    return message


async def handle_validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
    """Handle input that does not match what an endpoint expects."""
    return make_error_response(422, describe_validation_error(error))


async def handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
    """Handle every other error. The user gets a short message, and the details go to the log."""
    logger.error("Unhandled error on %s %s", request.method, request.url.path, exc_info=error)
    return make_error_response(500, "Something went wrong on the server. Please try again.")


def add_error_handlers(app: FastAPI) -> None:
    """Connect the three handlers to the app."""
    app.add_exception_handler(StarletteHTTPException, handle_http_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(Exception, handle_unexpected_error)