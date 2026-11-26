from unittest.mock import Mock
from functools import partial

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import voice_routes
from app.core.config import Settings
from app.main import create_app


def test_voice_route_requires_auth_and_only_passes_audio_to_the_local_model(tmp_path, monkeypatch):
    for name in ("model.bin", "config.json", "tokenizer.json"):
        (tmp_path / name).touch()
    recognize = Mock(return_value="Проверка голосового ввода")
    monkeypatch.setattr(voice_routes, "recognize", recognize)
    settings = Settings(session_signing_key="x" * 32, demo_mode=True, whisper_model_path=str(tmp_path))
    with TestClient(create_app(settings, session_service=Mock()), base_url="https://testserver") as client:
        path = voice_routes.TRANSCRIPTION_PATH
        assert client.post(path, content=b"audio", headers={"Content-Type": "audio/webm"}).status_code == 401
        launch = client.post("/api/v1/auth/launch", json={"mode": "demo"}).json()
        headers = {"Authorization": "Bearer " + launch["access_token"], "Content-Type": "audio/webm;codecs=opus"}
        assert client.post(path, content=b"").status_code == 401
        assert client.post(path, headers=headers, content=b"").status_code == 422
        assert client.post(path, headers={**headers, "Content-Type": "text/plain"}, content=b"audio").status_code == 415
        assert client.post(path, headers=headers, content=b"x" * (voice_routes.MAX_AUDIO_BYTES + 1)).status_code == 413
        audio = b"x" * 17000
        result = client.post(path, headers=headers, content=audio)
        assert result.status_code == 200
        assert result.json() == {"text": "Проверка голосового ввода"}
        assert result.headers["cache-control"] == "no-store"
        recognize.assert_called_once_with(str(tmp_path.resolve()), bytearray(audio), "matroska")


@pytest.mark.parametrize("status,payload,expected", [
    (200, {"text": "  Проверка записи  ", "duration": 3.5}, 200),
    (200, {"text": "", "duration": 2}, 422),
    (200, {"text": "Длинная запись", "duration": 36}, 413),
    (200, {"text": "Нет длительности"}, 503),
    (200, {"text": "Некорректная длительность", "duration": "NaN"}, 503),
    (400, {"error": "private provider response"}, 422),
    (401, {"error": "private provider response"}, 503),
    (429, {}, 429),
    (500, {"error": "private provider response"}, 503),
])
def test_groq_voice_without_local_model(monkeypatch, status, payload, expected):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(status, json=payload)

    monkeypatch.setattr(voice_routes.httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(handle)))
    settings = Settings(session_signing_key="x" * 32, demo_mode=True, voice_provider="groq", groq_api_key="private-test-key")
    with TestClient(create_app(settings, session_service=Mock()), base_url="https://testserver") as client:
        path = voice_routes.TRANSCRIPTION_PATH
        assert client.post(path, content=b"audio", headers={"Content-Type": "audio/webm"}).status_code == 401
        token = client.post("/api/v1/auth/launch", json={"mode": "demo"}).json()["access_token"]
        headers = {"Authorization": "Bearer " + token, "Content-Type": "audio/webm;codecs=opus"}
        assert client.post(path, content=b"", headers=headers).status_code == 422
        assert client.post(path, content=b"x" * (voice_routes.MAX_AUDIO_BYTES + 1), headers=headers).status_code == 413
        assert not requests
        result = client.post(path, content=b"synthetic-audio", headers=headers)
        assert result.status_code == expected
        assert "private" not in result.text
        if expected == 200:
            assert result.json() == {"text": "Проверка записи"}
        assert len(requests) == 1
        outgoing = requests[0]
        assert str(outgoing.url) == "https://api.groq.com/openai/v1/audio/transcriptions"
        assert outgoing.headers["authorization"] == "Bearer private-test-key"
        assert token.encode() not in outgoing.content
        assert b'filename="recording.webm"' in outgoing.content
        assert b"synthetic-audio" in outgoing.content
        assert b"whisper-large-v3-turbo" in outgoing.content


def test_groq_voice_timeout_is_sanitized(monkeypatch):
    def handle(request):
        raise httpx.ReadTimeout("secret response", request=request)

    monkeypatch.setattr(voice_routes.httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(handle)))
    settings = Settings(session_signing_key="x" * 32, demo_mode=True, voice_provider="groq", groq_api_key="secret")
    with TestClient(create_app(settings, session_service=Mock()), base_url="https://testserver") as client:
        token = client.post("/api/v1/auth/launch", json={"mode": "demo"}).json()["access_token"]
        response = client.post(voice_routes.TRANSCRIPTION_PATH, content=b"audio", headers={"Content-Type": "audio/ogg", "Authorization": "Bearer " + token})
        assert response.status_code == 503
        assert response.json() == {"detail": "voice_unavailable"}
