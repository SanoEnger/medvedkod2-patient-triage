import os

import pytest
from sqlalchemy.engine import make_url

from app.hosting import prepare_environment


def test_managed_postgres_url_keeps_credentials_and_normalizes_driver(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic:password@example.test/db?sslmode=require&channel_binding=require")
    prepare_environment()
    url = make_url(os.environ["DATABASE_URL"])
    assert url.drivername == "postgresql+asyncpg"
    assert url.username == "synthetic" and url.password == "password"
    assert url.host == "example.test" and not url.query
    prepare_environment()
    assert make_url(os.environ["DATABASE_URL"]) == url


def test_managed_postgres_refuses_disabled_tls(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.test/db?sslmode=disable")
    with pytest.raises(ValueError, match="verified TLS"):
        prepare_environment()


def test_local_database_configuration_is_not_changed(monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    value = "postgresql+asyncpg://localhost/synthetic"
    monkeypatch.setenv("DATABASE_URL", value)
    prepare_environment()
    assert os.environ["DATABASE_URL"] == value
