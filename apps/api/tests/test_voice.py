from unittest.mock import Mock

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
