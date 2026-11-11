import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone

from app.config import settings

# The id of the request that is being handled. Every log line gets it.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

TEXT_FORMAT = "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"

# These libraries write a line for every request, which hides the useful messages
NOISY_LOGGERS = ["httpx", "huggingface_hub", "sentence_transformers", "uvicorn.access"]


def get_request_id() -> str:
    """Return the id of the request that is being handled, or '-' if there is none."""
    return request_id_var.get()


def set_request_id(value: str) -> None:
    """Remember the id of the request that is being handled."""
    request_id_var.set(value)


class RequestIdFilter(logging.Filter):
    """Adds the request id to every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Put the id on the record and let the record through."""
        record.request_id = get_request_id()
        return True


class JsonFormatter(logging.Formatter):
    """Writes every log record as one JSON object on one line."""

    def format(self, record: logging.LogRecord) -> str:
        """Turn a log record into a JSON line."""
        entry = {
            "time": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }

        # A log call can add fields with: logger.info("text", extra={"fields": {"status": 200}})
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            entry.update(fields)

        if record.exc_info:
            entry["error"] = self.formatException(record.exc_info)

        return json.dumps(entry)


def setup_logging() -> None:
    """Set one log format for the whole app."""
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    if settings.log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(TEXT_FORMAT))

    root = logging.getLogger()
    # Replace what was set before, so no line is written twice
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)