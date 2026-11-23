import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core_relay import create_relay
from app.integrations.max_core import MaxCoreClient

SECRET = "synthetic-relay-secret-" + "x" * 32


def test_relay_requires_secret_and_discards_personal_fields():
    seen = []

    async def core_response(request):
        seen.append(request)
        assert request.url.params["token"] == "synthetic-user-jwt"
        assert request.headers["Authorization"] == "Bearer synthetic-service"
        return httpx.Response(200, json={"_id": "synthetic-id", "SNILS": "private", "phone": "private"})

    core = MaxCoreClient(Settings(core_service_token="synthetic-service"),
                         httpx.AsyncClient(transport=httpx.MockTransport(core_response)))
    with TestClient(create_relay(core, SECRET)) as client:
        assert client.post("/resolve", json={"token": "synthetic-user-jwt"}).status_code == 401
        assert seen == []
        result = client.post("/resolve", json={"token": "synthetic-user-jwt"}, headers={"Authorization": "Bearer " + SECRET})
        assert result.json() == {"_id": "synthetic-id"}
        assert result.headers["Cache-Control"] == "no-store"
        assert client.get("/docs").status_code == 404


@pytest.mark.parametrize("status", [401, 503])
def test_relay_failure_never_grants_identity(status):
    async def response(request):
        return httpx.Response(status)

    core = MaxCoreClient(Settings(core_service_token="synthetic-service"),
                         httpx.AsyncClient(transport=httpx.MockTransport(response)))
    with TestClient(create_relay(core, SECRET)) as client:
        result = client.post("/resolve", json={"token": "synthetic-user-jwt"}, headers={"Authorization": "Bearer " + SECRET})
        assert result.status_code == status
        assert "_id" not in result.json()


def test_backend_posts_jwt_in_body_to_authenticated_relay():
    async def response(request):
        assert request.method == "POST"
        assert str(request.url) == "https://relay.example/resolve"
        assert request.headers["Authorization"] == "Bearer " + SECRET
        assert request.content == b'{"token":"synthetic-user-jwt"}'
        return httpx.Response(200, json={"_id": "synthetic-id"})

    settings = Settings(core_relay_url="https://relay.example", core_relay_token=SECRET)
    client = MaxCoreClient(settings, httpx.AsyncClient(transport=httpx.MockTransport(response)))
    assert asyncio.run(client.resolve_user_id("synthetic-user-jwt")) == "max:synthetic-id"


def test_relay_configuration_requires_https_and_secret():
    for url, secret in [("http://relay.example", SECRET), ("https://relay.example?token=x", SECRET), ("https://relay.example", "short")]:
        with pytest.raises(ValueError):
            Settings(session_signing_key="x" * 40, core_relay_url=url, core_relay_token=secret).validate()
