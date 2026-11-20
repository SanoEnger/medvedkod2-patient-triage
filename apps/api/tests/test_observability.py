import asyncio
import io
import json
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.observability import RequestLoggingMiddleware, SafeJsonFormatter, logger


def test_safe_logs_use_route_template_and_never_echo_input():
    app = FastAPI()
    @app.get('/synthetic/{identifier}')
    async def synthetic(identifier: str):
        return {"ok": True}
    app.add_middleware(RequestLoggingMiddleware)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(SafeJsonFormatter())
    logger.addHandler(handler)
    old_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        with TestClient(app) as c:
            response = c.get('/synthetic/private-marker?token=synthetic-secret', headers={'Authorization': 'Bearer hidden'})
        assert len(response.headers['x-request-id']) == 32
        record = json.loads(stream.getvalue().strip())
        assert record['request_id'] == response.headers['x-request-id']
        assert record['route'] == '/synthetic/{identifier}'
        assert record['status'] == 200
        assert all(value not in stream.getvalue() for value in ('private-marker', 'synthetic-secret', 'hidden'))
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)


def test_formatter_ignores_arbitrary_extras_and_tracebacks():
    try:
        raise ValueError('synthetic-secret')
    except ValueError:
        import sys
        record = logging.LogRecord('medved', logging.ERROR, '', 1, 'safe.event', (), sys.exc_info())
    record.patient_text = 'private-marker'
    rendered = SafeJsonFormatter().format(record)
    assert 'synthetic-secret' not in rendered and 'private-marker' not in rendered


def test_unhandled_error_response_and_logs_are_sanitized():
    app = FastAPI()
    @app.get('/failure')
    async def failure():
        raise ValueError('synthetic-secret')
    app.add_middleware(RequestLoggingMiddleware)
    with TestClient(app) as c:
        response = c.get('/failure')
    assert response.status_code == 500
    assert response.json() == {"detail": "internal_error"}


def test_compose_preserves_api_env_mode():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[3] / 'compose.yaml').read_text()
    assert 'NLP_MODE: ${NLP_MODE:-mock}' not in text
