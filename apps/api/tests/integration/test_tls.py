import os
import socket
import ssl
import threading
import time
from dataclasses import replace
from pathlib import Path

import asyncpg
import httpx
import pytest
import uvicorn
from app.core.config import Settings
from app.run_api import create_config
from sqlalchemy import text
from sqlalchemy.engine import make_url

pytestmark = pytest.mark.postgres


@pytest.mark.asyncio
async def test_postgres_tls_is_verified_and_plaintext_is_rejected(engine, database_url):
    async with engine.connect() as connection:
        enabled, version = (await connection.execute(text(
            "SELECT ssl, version FROM pg_stat_ssl WHERE pid = pg_backend_pid()",
        ))).one()
        assert enabled is True
        assert version in ("TLSv1.2", "TLSv1.3")
    url = make_url(database_url)
    parameters = {
        "host": url.host, "port": url.port, "user": url.username,
        "password": url.password, "database": url.database, "timeout": 5,
    }
    with pytest.raises(asyncpg.InvalidAuthorizationSpecificationError):
        await asyncpg.connect(**parameters, ssl=False)
    if Settings.from_env().database_ssl_ca_file:
        with pytest.raises(ssl.SSLCertVerificationError):
            await asyncpg.connect(**parameters, ssl=ssl.create_default_context())


def test_real_https_exchanges_plain_json_over_trusted_tls(database_url):
    settings = replace(Settings.from_env(), api_host="127.0.0.1", api_port=0, demo_mode=True)
    if not all(Path(path).is_file() for path in (
        settings.api_tls_cert_file, settings.api_tls_key_file, settings.database_ssl_ca_file,
    )):
        pytest.skip("Set local API_TLS_CERT_FILE, API_TLS_KEY_FILE and DATABASE_SSL_CA_FILE")
    # The factory runs inside the server thread and uses the same environment.
    old_demo = os.environ.get("DEMO_MODE")
    os.environ["DEMO_MODE"] = "true"
    server = uvicorn.Server(create_config(settings))
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started, "HTTPS server failed to start"
        tls = ssl.create_default_context(cafile=settings.database_ssl_ca_file)
        base = f"https://127.0.0.1:{port}"
        with httpx.Client(base_url=base, verify=tls, trust_env=False, timeout=5) as client:
            response = client.get("/health")
            assert response.json() == {"status": "ok"}
            assert response.headers["Strict-Transport-Security"]
            auth = client.post("/api/v1/auth/launch", json={"mode": "demo"})
            assert auth.status_code == 200
            client.headers["Authorization"] = "Bearer " + auth.json()["access_token"]
            created = client.post("/api/v1/sessions", json={"accepted_disclaimer": True})
            assert created.status_code == 201
            sid = created.json()["id"]
            try:
                from uuid import uuid4

                answered = client.post(f"/api/v1/sessions/{sid}/answers", json={
                    "question_key": "primary_complaint",
                    "value": {"category": "skin"},
                    "idempotency_key": str(uuid4()),
                })
                assert answered.status_code == 200
                assert answered.json()["current_question"] == "patient_context"
                assert answered.json()["progress"]["answered"] == 1
                assert not {"v", "n", "c"} <= answered.json().keys()
            finally:
                assert client.delete(f"/api/v1/sessions/{sid}").status_code == 204
        with pytest.raises(httpx.ConnectError):
            httpx.get(base + "/health", verify=ssl.create_default_context(), trust_env=False, timeout=5)
        with (
            socket.create_connection(("127.0.0.1", port), timeout=5) as connection,
            pytest.raises(ssl.SSLCertVerificationError),
        ):
            tls.wrap_socket(connection, server_hostname="incorrect.example")
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
        if old_demo is None:
            os.environ.pop("DEMO_MODE", None)
        else:
            os.environ["DEMO_MODE"] = old_demo
        assert not thread.is_alive()

