import base64
import binascii
import json
import os
from pathlib import Path
from typing import Any
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class DataEncryptionError(ValueError):
    pass


def answer_context(session_id: UUID, question_key: str) -> str:
    return f"medved/answer/v1/{session_id}/{question_key}"


def message_context(session_id: UUID, message_id: UUID) -> str:
    return f"medved/message/v1/{session_id}/{message_id}"


def state_context(session_id: UUID) -> str:
    return f"medved/session-state/v1/{session_id}"


def triage_context(session_id: UUID, field: str) -> str:
    return f"medved/triage/v1/{session_id}/{field}"


def rule_context(code: str, version: str) -> str:
    return f"medved/safety-rule/v1/{code}/{version}"


def audit_context(event_id: UUID) -> str:
    return f"medved/audit/v1/{event_id}"


def encrypted_json_check(column: str) -> str:
    return (
        f"{column} ?& ARRAY['v','n','c'] AND "
        f"({column}->'v') = '1'::jsonb AND "
        f"jsonb_typeof({column}->'n') = 'string' AND "
        f"jsonb_typeof({column}->'c') = 'string' AND "
        f"({column} - 'v' - 'n' - 'c') = '{{}}'::jsonb"
    )


class JsonCipher:
    def __init__(self, key: bytes):
        if len(key) != 32:
            raise ValueError("Data encryption requires a 32-byte AES key")
        self._aes = AESGCM(key)

    @classmethod
    def from_file(cls, path: str) -> "JsonCipher":
        if not path and not os.environ.get("DATA_ENCRYPTION_KEY"):
            raise ValueError("DATA_ENCRYPTION_KEY_FILE or DATA_ENCRYPTION_KEY is required")
        try:
            # Managed hosts provide persistent secrets as environment variables.
            encoded = Path(path).read_bytes().strip() if path else os.environ.get("DATA_ENCRYPTION_KEY", "").strip().encode("ascii")
            key = base64.b64decode(encoded, altchars=b"-_", validate=True)
        except (OSError, ValueError, binascii.Error):
            raise ValueError("Cannot read a valid data encryption key file") from None
        return cls(key)

    def encrypt(self, value: dict[str, Any], context: str) -> dict[str, Any]:
        nonce = os.urandom(12)
        plaintext = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        ciphertext = self._aes.encrypt(nonce, plaintext, context.encode("utf-8"))
        return {
            "v": 1,
            "n": base64.b64encode(nonce).decode("ascii"),
            "c": base64.b64encode(ciphertext).decode("ascii"),
        }

    def decrypt(self, envelope: dict[str, Any], context: str) -> dict[str, Any]:
        try:
            if type(envelope["v"]) is not int or envelope["v"] != 1:
                raise ValueError
            nonce = base64.b64decode(envelope["n"], validate=True)
            ciphertext = base64.b64decode(envelope["c"], validate=True)
            if len(nonce) != 12:
                raise ValueError
            plaintext = self._aes.decrypt(nonce, ciphertext, context.encode("utf-8"))
            value = json.loads(plaintext)
            if not isinstance(value, dict):
                raise TypeError
            return value
        except (KeyError, TypeError, ValueError, InvalidTag, UnicodeError):
            raise DataEncryptionError("Stored data authentication failed") from None
