"""Allowlisted JSON diagnostics. Never serialize request bodies or exceptions."""

import contextvars
import json
import logging
import sys
import time
from datetime import UTC, datetime
from uuid import uuid4

request_id = contextvars.ContextVar("request_id", default="-")
logger = logging.getLogger("medved")


class SafeJsonFormatter(logging.Formatter):
    def format(self, record):
        data = {"time": datetime.now(UTC).isoformat(), "service": getattr(record, "service", "api"),
                "level": record.levelname, "event": record.msg,
                "request_id": getattr(record, "request_id", "-")}
        for key in ("route", "method", "status", "duration_ms", "code", "mode", "phase", "error_type"):
            if hasattr(record, key):
                data[key] = getattr(record, key)
        # Ignore args, exc_info, stack_info, and any arbitrary extra fields.
        return json.dumps(data, ensure_ascii=False)


def configure_logging():
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(SafeJsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    # HTTP-client INFO/DEBUG includes full URLs, including the MAX launch JWT.
    for name in ("httpx", "httpcore", "sqlalchemy.engine"):
        logging.getLogger(name).setLevel(logging.CRITICAL)


def event(name: str, **fields):
    logger.info(name, extra={"request_id": request_id.get(), **fields})


class RequestLoggingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        identifier = uuid4().hex
        token = request_id.set(identifier)
        started = time.monotonic()
        status, sent = 500, False

        async def wrapped_send(message):
            nonlocal status, sent
            if message["type"] == "http.response.start":
                status, sent = message["status"], True
                message["headers"] = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"]
                message["headers"].append((b"x-request-id", identifier.encode()))
            await send(message)

        try:
            await self.app(scope, receive, wrapped_send)
        except Exception as error:
            event("http.unhandled_error", error_type=type(error).__name__)
            if sent:
                raise
            body = b'{"detail":"internal_error"}'
            await wrapped_send({"type": "http.response.start", "status": 500, "headers": [
                (b"content-type", b"application/json"), (b"cache-control", b"no-store")]})
            await wrapped_send({"type": "http.response.body", "body": body})
        finally:
            route = getattr(scope.get("route"), "path", "unmatched")
            # Route templates contain no session UUIDs, query tokens or user text.
            if route != "/health" or status >= 400:
                event("http.completed", route=route,
                      method=scope["method"] if scope["method"] in {"GET", "POST", "DELETE", "OPTIONS", "HEAD"} else "OTHER",
                      status=status, duration_ms=round((time.monotonic() - started) * 1000))
            request_id.reset(token)
