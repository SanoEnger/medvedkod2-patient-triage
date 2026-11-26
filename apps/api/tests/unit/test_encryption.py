import base64
import json
import ssl
from dataclasses import replace
from uuid import uuid4

import pytest
from app.core.config import Settings
from app.core.encryption import DataEncryptionError, JsonCipher, answer_context
from app.db.engine import create_engine


def test_unicode_roundtrip_random_nonce_and_no_plaintext():
    cipher = JsonCipher(b"x" * 32)
    context = answer_context(uuid4(), "primary_complaint")
    value = {"text": "\u0441\u0438\u043d\u0442\u0435\u0442\u0438\u043a\u0430", "nested": [1, None, True]}
    first = cipher.encrypt(value, context)
    assert set(first) == {"v", "n", "c"}
    assert first != cipher.encrypt(value, context)
    assert value["text"] not in json.dumps(first, ensure_ascii=False)
    assert cipher.decrypt(first, context) == value


@pytest.mark.parametrize("failure", ["ciphertext", "nonce", "key", "context", "plaintext"])
def test_cipher_fails_closed(failure):
    cipher = JsonCipher(b"x" * 32)
    context = "synthetic-context"
    sealed = cipher.encrypt({"synthetic": "secret"}, context)
    if failure == "ciphertext":
        data = bytearray(base64.b64decode(sealed["c"]))
        data[0] ^= 1
        sealed["c"] = base64.b64encode(data).decode()
    elif failure == "nonce":
        sealed["n"] = base64.b64encode(b"z" * 12).decode()
    elif failure == "key":
        cipher = JsonCipher(b"y" * 32)
    elif failure == "context":
        context = "another-row"
    else:
        sealed = {"synthetic": "secret"}
    with pytest.raises(DataEncryptionError, match="authentication failed"):
        cipher.decrypt(sealed, context)


def test_key_file_and_missing_key(tmp_path):
    path = tmp_path / "key"
    path.write_bytes(base64.urlsafe_b64encode(b"x" * 32))
    assert isinstance(JsonCipher.from_file(str(path)), JsonCipher)
    for invalid in (b"invalid", base64.urlsafe_b64encode(b"short")):
        path.write_bytes(invalid)
        with pytest.raises(ValueError):
            JsonCipher.from_file(str(path))
    with pytest.raises(ValueError):
        JsonCipher.from_file("")


def test_environment_key_for_managed_host(monkeypatch):
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", base64.b64encode(b"v" * 32).decode())
    cipher = JsonCipher.from_file("")
    assert cipher.decrypt(cipher.encrypt({"synthetic": True}, "test"), "test") == {"synthetic": True}


@pytest.mark.parametrize("key", ["invalid", "", base64.b64encode(b"short").decode()])
def test_invalid_environment_key_fails_closed(monkeypatch, key):
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", key)
    with pytest.raises(ValueError):
        JsonCipher.from_file("")


def test_database_uses_verified_tls(monkeypatch):
    captured = {}
    monkeypatch.setattr("app.db.engine.create_async_engine", lambda *a, **kw: captured.update(kw))
    create_engine("postgresql+asyncpg://localhost/synthetic")
    context = captured["connect_args"]["ssl"]
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2


@pytest.mark.parametrize("query", ["ssl=disable", "sslmode=disable", "ssl=require"])
def test_database_rejects_tls_override(query):
    with pytest.raises(ValueError):
        create_engine("postgresql+asyncpg://localhost/synthetic?" + query)


def test_api_requires_database_and_key():
    from app.main import create_app

    settings = Settings(session_signing_key="x" * 48)
    with pytest.raises(ValueError, match="DATA_ENCRYPTION_KEY_FILE"):
        create_app(settings)
    with pytest.raises(ValueError, match="DATABASE_URL"):
        create_engine(settings=replace(settings, database_url=""))
