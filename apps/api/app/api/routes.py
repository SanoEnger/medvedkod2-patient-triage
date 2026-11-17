"""Public, versioned FastAPI contract. No frontend, database or LLM dependencies."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.core.security import get_principal, issue_access_token
from app.schemas.survey import (
    AnswerRequest, BackRequest, CreateSessionRequest, LaunchRequest, LaunchResponse,
    SessionResponse, TriageResponse,
)

router = APIRouter()


@router.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/api/v1/auth/launch", response_model=LaunchResponse, tags=["auth"])
async def auth_launch(body: LaunchRequest, request: Request) -> LaunchResponse:
    settings = request.app.state.settings
    # Rate limit by socket address; no host JWT or raw complaint enters limiter state.
    await request.app.state.launch_limiter.check("launch:" + (request.client.host if request.client else "unknown"))
    if body.mode == "demo":
        if not settings.demo_mode or body.host_token:
            raise HTTPException(status_code=401, detail="demo_auth_disabled")
        owner = "demo:synthetic"
    else:
        if not body.host_token:
            raise HTTPException(status_code=401, detail="host_token_required")
        owner = await request.app.state.max_core.resolve_user_id(body.host_token)
    return LaunchResponse(
        access_token=issue_access_token(owner, settings.session_signing_key, settings.auth_ttl_seconds),
        expires_in=settings.auth_ttl_seconds,
    )


@router.post("/api/v1/sessions", status_code=status.HTTP_201_CREATED, response_model=SessionResponse, tags=["sessions"])
async def create_session(
    body: CreateSessionRequest, request: Request, owner: str = Depends(get_principal),
) -> SessionResponse:
    return await request.app.state.sessions.create(owner)


@router.get("/api/v1/sessions/{session_id}", response_model=SessionResponse, tags=["sessions"])
async def get_session(
    session_id: UUID, request: Request, owner: str = Depends(get_principal),
) -> SessionResponse:
    return await request.app.state.sessions.get(session_id, owner)


@router.post("/api/v1/sessions/{session_id}/answers", response_model=SessionResponse, tags=["sessions"])
async def answer_session(
    session_id: UUID, body: AnswerRequest, request: Request, owner: str = Depends(get_principal),
) -> SessionResponse:
    return await request.app.state.sessions.answer(session_id, owner, body)


@router.post("/api/v1/sessions/{session_id}/back", response_model=SessionResponse, tags=["sessions"])
async def back_session(
    session_id: UUID, body: BackRequest, request: Request, owner: str = Depends(get_principal),
) -> SessionResponse:
    return await request.app.state.sessions.back(session_id, owner, body.target_step)


@router.post("/api/v1/sessions/{session_id}/triage", response_model=TriageResponse, tags=["sessions"])
async def triage_session(
    session_id: UUID, request: Request, owner: str = Depends(get_principal),
) -> TriageResponse:
    return await request.app.state.sessions.triage(session_id, owner)


@router.delete("/api/v1/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["sessions"])
async def delete_session(
    session_id: UUID, request: Request, owner: str = Depends(get_principal),
) -> Response:
    await request.app.state.sessions.delete(session_id, owner)
    return Response(status_code=204)
