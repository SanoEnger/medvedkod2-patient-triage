"""Short-lived, HMAC-authenticated bearer tokens. Does not encode medical data."""

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time

from fastapi import HTTPException, Request, status


def _b64_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64_decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def issue_access_token(subject: str, key: str, ttl_seconds: int) -> str:
    payload = {"sub": subject, "exp": int(time.time()) + ttl_seconds, "jti": secrets.token_hex(16)}
    body = _b64_encode(json.dumps(payload, separators=(",", ":")).encode())
    message = ("v1." + body).encode()
    signature = _b64_encode(hmac.new(key.encode(), message, hashlib.sha256).digest())
    return message.decode() + "." + signature


def verify_access_token(token: str, key: str) -> str:
    try:
        version, body, signature = token.split(".")
        if version != "v1" or len(token) > 2048:
            raise ValueError
        message = (version + "." + body).encode()
        expected = hmac.new(key.encode(), message, hashlib.sha256).digest()
        if not hmac.compare_digest(_b64_decode(signature), expected):
            raise ValueError
        payload = json.loads(_b64_decode(body))
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("sub"), str)
            or not payload["sub"]
            or type(payload.get("exp")) is not int
            or payload["exp"] <= int(time.time())
        ):
            raise ValueError
        return payload["sub"]
    except (ValueError, KeyError, TypeError, UnicodeError, binascii.Error, json.JSONDecodeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_access_token") from None


def get_principal(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer ") or header.count(" ") != 1:
        raise HTTPException(status_code=401, detail="access_token_required")
    return verify_access_token(header[7:], request.app.state.settings.session_signing_key)
