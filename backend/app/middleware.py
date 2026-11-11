import logging
import time
import uuid

from app.config import settings
from app.errors import make_error_response
from app.logging import set_request_id
from app.rate_limit import check_rate_limit, find_rule, make_identity

logger = logging.getLogger("app.access")

MAX_REQUEST_ID_LENGTH = 64
MEGABYTE = 1024 * 1024
METHODS_WITH_BODY = ["POST", "PUT", "PATCH"]


def read_header(scope: dict, name: bytes) -> str:
    """Read one header of the request. Returns an empty text if it is missing."""
    for key, value in scope["headers"]:
        if key == name:
            return value.decode("latin-1")
    return ""


def clean_request_id(value: str) -> str:
    """Use the request id that the client sent only if it is short and harmless. Otherwise make a new one."""
    cleaned = ""
    for character in value[:MAX_REQUEST_ID_LENGTH]:
        if character.isalnum() or character in "-_":
            cleaned += character

    if cleaned == "":
        return uuid.uuid4().hex
    return cleaned


def get_body_limit(method: str, path: str) -> int:
    """Return the largest allowed body size in bytes for a request. 0 means no limit."""
    if method not in METHODS_WITH_BODY:
        return 0
    if path == "/documents/upload":
        # A little extra room for the form fields around the file
        return (settings.max_upload_mb + 1) * MEGABYTE
    return settings.max_json_body_bytes


async def find_rejection(scope: dict):
    """Check size and rate limits. Returns (status, message, headers) if the request must be stopped, otherwise None."""
    method = scope["method"]
    path = scope["path"]

    # The size is checked from the header, before the body is read
    limit = get_body_limit(method, path)
    length_text = read_header(scope, b"content-length")
    if limit > 0 and length_text != "":
        if not length_text.isdigit():
            return 400, "The Content-Length header is not valid.", None
        if int(length_text) > limit:
            return 413, "The request is too large.", None

    rule = find_rule(method, path)
    if rule is None:
        return None

    name, limit_per_minute, by_user = rule
    client = scope.get("client")
    client_ip = "unknown"
    if client:
        client_ip = client[0]

    identity = make_identity(client_ip, read_header(scope, b"authorization"), by_user)
    seconds_to_wait = await check_rate_limit(name, identity, limit_per_minute)
    if seconds_to_wait > 0:
        message = "Too many requests. Please wait " + str(seconds_to_wait) + " seconds and try again."
        return 429, message, {"Retry-After": str(seconds_to_wait)}

    return None


class RequestMiddleware:
    """Gives every request an id, stops oversized and too frequent requests, and writes one log line per request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        """Handle one request."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = clean_request_id(read_header(scope, b"x-request-id"))
        # Every request runs in its own task, so this value never leaks into another request
        set_request_id(request_id)

        started = time.monotonic()
        result = {"status": 0}

        async def send_with_id(message):
            """Add the request id to the response headers, and remember the status."""
            if message["type"] == "http.response.start":
                result["status"] = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        try:
            rejection = await find_rejection(scope)
            if rejection is not None:
                status, message, headers = rejection
                response = make_error_response(status, message, headers)
                await response(scope, receive, send_with_id)
            else:
                await self.app(scope, receive, send_with_id)
        finally:
            duration_ms = round((time.monotonic() - started) * 1000)
            text = scope["method"] + " " + scope["path"] + " -> " + str(result["status"]) + " in " + str(duration_ms) + " ms"
            fields = {
                "method": scope["method"],
                "path": scope["path"],
                "status": result["status"],
                "duration_ms": duration_ms,
            }
            logger.info(text, extra={"fields": fields})