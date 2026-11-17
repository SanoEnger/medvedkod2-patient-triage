"""Server-to-server host launch verification; never return SNILS, OMS or names."""

import httpx
from fastapi import HTTPException

from app.core.config import Settings


class MaxCoreClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client

    async def resolve_user_id(self, user_token: str) -> str:
        """Ask organizer core to authenticate a 5-minute host JWT."""
        if not self._settings.core_service_token:
            raise HTTPException(status_code=503, detail="host_auth_not_configured")
        if not user_token or len(user_token) > 6000:
            raise HTTPException(status_code=401, detail="invalid_host_token")
        own_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._settings.core_timeout_seconds)
        try:
            resp = await client.get(
                self._settings.core_url + "/api/v3/users/user-for-external-service",
                params={"token": user_token},
                headers={"Authorization": "Bearer " + self._settings.core_service_token},
                timeout=self._settings.core_timeout_seconds,
            )
        except httpx.RequestError:
            raise HTTPException(status_code=503, detail="host_auth_unavailable") from None
        finally:
            if own_client:
                await client.aclose()
        if resp.status_code in (401, 404):
            raise HTTPException(status_code=401, detail="invalid_host_token")
        if resp.status_code == 403:
            raise HTTPException(status_code=503, detail="host_service_unauthorized")
        if resp.status_code != 200:
            raise HTTPException(status_code=503, detail="host_auth_unavailable")
        try:
            data = resp.json()
            user_id = data["_id"]
            if not isinstance(user_id, str) or not (1 <= len(user_id) <= 128):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise HTTPException(status_code=503, detail="host_auth_invalid_response") from None
        # Personal fields from core deliberately discarded, not persisted/logged.
        return "max:" + user_id
