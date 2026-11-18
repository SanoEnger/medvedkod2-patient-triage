"""Async Groq Chat Completions adapter with injectable HTTP transport."""

import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from .exceptions import GroqError, GroqTimeout, InvalidResponse
from .prompts import SYSTEM_PROMPT
from app.environment import load_local_environment


class CompletionClient(Protocol):
    async def complete(self, text: str) -> str:
        """Return raw JSON; raise a sanitized GroqError on expected failure."""
        ...


@dataclass(frozen=True)
class GroqSettings:
    api_key: str = field(default="", repr=False)
    model: str = ""
    timeout_seconds: float = 7.0

    def __post_init__(self) -> None:
        if not 0 < self.timeout_seconds <= 60:
            raise ValueError("timeout_seconds must be in (0, 60]")

    @classmethod
    def from_env(cls) -> "GroqSettings":
        load_local_environment()
        return cls(
            api_key=os.getenv("GROQ_API_KEY", ""),
            model=os.getenv("GROQ_MODEL", ""),
            timeout_seconds=float(os.getenv("GROQ_TIMEOUT_SECONDS", "7")),
        )


class GroqClient:
    def __init__(self, settings: GroqSettings, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings
        self.transport = transport

    async def complete(self, text: str) -> str:
        """One bounded request, no retries, no response bodies in errors or logs."""
        if not self.settings.api_key or not self.settings.model:
            raise GroqError("missing_configuration")
        failure = None
        content = None
        try:
            async with asyncio.timeout(self.settings.timeout_seconds):
                async with httpx.AsyncClient(
                    transport=self.transport, timeout=self.settings.timeout_seconds,
                    follow_redirects=False,
                ) as client:
                    response = await client.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={"Authorization": f"Bearer {self.settings.api_key}"},
                        json={
                            "model": self.settings.model,
                            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                                         {"role": "user", "content": json.dumps({"complaint": text}, ensure_ascii=False)}],
                            "response_format": {"type": "json_object"},
                            "temperature": 0,
                            "max_completion_tokens": 2048,
                        },
                    )
                    if response.status_code == 429:
                        failure = GroqError("rate_limited")
                    elif response.status_code >= 500:
                        failure = GroqError("server_error")
                    elif response.status_code != 200:
                        failure = GroqError("http_error")
                    else:
                        payload = response.json()
                        choice = payload["choices"][0]
                        if choice.get("finish_reason") != "stop":
                            failure = InvalidResponse()
                        else:
                            content = choice["message"]["content"]
                            if not isinstance(content, str) or len(content) > 50000:
                                failure = InvalidResponse()
        except (TimeoutError, httpx.TimeoutException):
            failure = GroqTimeout()
        except httpx.RequestError:
            failure = GroqError("network_error")
        except (ValueError, KeyError, IndexError, TypeError):
            failure = InvalidResponse()
        # Raise outside except blocks: provider exceptions cannot leak via context.
        if failure is not None:
            raise failure
        if content is None:
            raise InvalidResponse()
        return content


class MockGroqClient:
    """Canned synthetic responses, independent of the fallback implementation."""

    async def complete(self, text: str) -> str:
        fixtures = {
            "У меня сильно болит грудь, тяжело дышать": [
                {"code": "chest_pain", "evidence": "болит грудь", "status": "present"},
                {"code": "dyspnea", "evidence": "тяжело дышать", "status": "present"},
            ],
            "Кашель 2 дня": [
                {"code": "cough", "evidence": "Кашель", "status": "present", "duration": "2 дня"},
            ],
        }
        return json.dumps({"symptoms": fixtures.get(text, []), "details": [], "needs_clarification": True}, ensure_ascii=False)
