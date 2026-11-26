"""MAX verification relay. Deploy behind managed HTTPS with server-side credentials."""

import hmac
import os

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import Settings
from app.integrations.max_core import MaxCoreClient


class ResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=1, max_length=6000)


def create_relay(core: MaxCoreClient | None = None, secret: str | None = None) -> FastAPI:
    secret = secret or os.environ.get("CORE_RELAY_TOKEN", "")
    if len(secret) < 32:
        raise ValueError("CORE_RELAY_TOKEN must contain at least 32 characters")
    if core is None:
        service_token = os.environ.get("CORE_SERVICE_TOKEN", "")
        if not service_token:
            raise ValueError("CORE_SERVICE_TOKEN is required")
        # No configurable forwarding destination: this is not an open proxy.
        core = MaxCoreClient(Settings(core_service_token=service_token, core_timeout_seconds=4))
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def authenticate(authorization: str = Header(default="")):
        if not hmac.compare_digest(authorization.encode(), ("Bearer " + secret).encode()):
            raise HTTPException(401, detail="relay_unauthorized")

    @app.middleware("http")
    async def limit_request(request, call_next):
        try:
            if int(request.headers.get("content-length", "0")) > 16384:
                return JSONResponse({"detail": "request_too_large"}, status_code=413)
        except ValueError:
            return JSONResponse({"detail": "invalid_content_length"}, status_code=400)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/resolve", dependencies=[Depends(authenticate)])
    async def resolve(body: ResolveRequest):
        owner = await core.resolve_user_id(body.token)
        return {"_id": owner.removeprefix("max:")}

    return app
