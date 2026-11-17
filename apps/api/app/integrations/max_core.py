"""MAX host authentication hook for the API foundation."""
from fastapi import HTTPException
from app.core.config import Settings

class MaxCoreClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def resolve_user_id(self, user_token: str) -> str:
        raise HTTPException(status_code=503, detail="host_auth_not_configured")
