"""Correlation IDs and structured JSON logs shared by the API and worker.

One ID follows a request into the job it creates, the provider runs and artifacts that job
records, and every log line in between. Logs carry identifiers and measurements only: never
request bodies, dialogue text, file paths or credentials.
"""

import json
import logging
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import event

HEADER = "X-Request-ID"
_VALID = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
correlation: ContextVar[str | None] = ContextVar("cinedub_correlation_id", default=None)
logger = logging.getLogger("cinedub")


def new_correlation_id() -> str:
    return uuid4().hex


def accepted_id(value: str | None) -> str:
    """Accept a caller's ID only if it is a short opaque token; otherwise mint one."""
    return value if value and _VALID.fullmatch(value) else new_correlation_id()


@contextmanager
def bound(correlation_id: str | None):
    token = correlation.set(correlation_id)
    try:
        yield
    finally:
        correlation.reset(token)


def log_event(name: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, name, extra={"event_fields": fields})


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str):
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "service": self.service,
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": record.getMessage(),
            "correlation_id": correlation.get(),
        }
        payload.update(getattr(record, "event_fields", {}))
        if record.exc_info:
            # Exception type only: messages may contain provider responses or paths.
            payload["error_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(service: str, level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for name in ("cinedub", "cinedub.worker"):
        logging.getLogger(name).setLevel(level)


class CorrelationMiddleware:
    """Pure ASGI middleware: binds the request ID and echoes it on every response."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {key.decode().lower(): value.decode() for key, value in scope["headers"]}
        identifier = accepted_id(headers.get(HEADER.lower()))
        started = time.monotonic()
        status = {"code": 500}

        async def wrapped(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                message.setdefault("headers", [])
                message["headers"] = [
                    *message["headers"],
                    (HEADER.lower().encode(), identifier.encode()),
                ]
            await send(message)

        with bound(identifier):
            try:
                await self.app(scope, receive, wrapped)
            finally:
                route = scope.get("route")
                log_event(
                    "http_request",
                    method=scope["method"],
                    route=getattr(route, "path", None) or "unmatched",
                    status=status["code"],
                    duration_ms=round((time.monotonic() - started) * 1000, 1),
                )


def stamp_correlation(mapper, connection, target) -> None:
    if getattr(target, "correlation_id", None) is None:
        target.correlation_id = correlation.get()


def install_model_hooks(*models) -> None:
    for model in models:
        if not event.contains(model, "before_insert", stamp_correlation):
            event.listen(model, "before_insert", stamp_correlation)
