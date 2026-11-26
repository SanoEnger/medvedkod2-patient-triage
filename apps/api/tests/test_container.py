import pytest
from dotenv import dotenv_values
from sqlalchemy.engine import make_url

from app.container import configure, initialize


@pytest.fixture(autouse=True)
def skip_container_ownership_on_host(monkeypatch):
    monkeypatch.setattr("app.container.os.chown", lambda *_: None, raising=False)


def test_initialize_keeps_keys_and_database_password_on_restart(tmp_path):
    runtime, postgres, web = (tmp_path / name for name in ("runtime", "postgres", "web"))
    initialize(runtime, postgres, web)
    originals = {path.name: path.read_bytes() for path in runtime.iterdir()}
    initialize(runtime, postgres, web)
    assert originals == {path.name: path.read_bytes() for path in runtime.iterdir()}
    assert (web / "web.key").read_bytes() == (runtime / "api.key").read_bytes()
    assert (postgres / "postgres.key").read_bytes() == (runtime / "postgres.key").read_bytes()
    assert (postgres / "password").read_text() == dotenv_values(runtime / "backend.env")["POSTGRES_PASSWORD"]
    assert {path.name for path in web.iterdir()} == {"ca.crt", "web.crt", "web.key"}
    assert {path.name for path in postgres.iterdir()} == {"postgres.crt", "postgres.key", "password"}


def test_initialize_rejects_partial_secrets_without_overwriting(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    key = runtime / "encryption.key"
    key.write_bytes(b"existing-key")
    with pytest.raises(ValueError, match="Incomplete Docker secrets"):
        initialize(runtime, tmp_path / "postgres", tmp_path / "web")
    assert key.read_bytes() == b"existing-key"


def test_configure_uses_docker_network_and_preserves_external_settings(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    initialize(runtime, tmp_path / "postgres", tmp_path / "web")
    for name in dotenv_values(runtime / "backend.env"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("CORE_SERVICE_TOKEN", "synthetic-host-token")
    configure(runtime)
    import os

    actual = make_url(os.environ["DATABASE_URL"])
    original = make_url(dotenv_values(runtime / "backend.env")["DATABASE_URL"])
    assert actual.host == "postgres"
    assert actual.port == 5432
    assert actual.password == original.password
    assert os.environ["DATA_ENCRYPTION_KEY_FILE"] == str(runtime / "encryption.key")
    assert os.environ["API_HOST"] == "0.0.0.0"
    assert os.environ["DEMO_MODE"] == "false"
    assert os.environ["CORE_SERVICE_TOKEN"] == "synthetic-host-token"
