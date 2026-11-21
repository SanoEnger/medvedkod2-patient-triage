from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from app.core.security import get_principal
from app.schemas.chat import (
    ChatAvailability,
    ChatCreate,
    ChatError,
    ChatHistory,
    ChatResponse,
    ChatSend,
)

router = APIRouter(prefix="/api/v1/chats", tags=["chat"], responses={
    401: {"model": ChatError, "description": "Authorization required"},
    422: {"model": ChatError, "description": "Invalid request"},
    503: {"model": ChatError, "description": "Chat storage or service unavailable"},
})


def service(request):
    if request.app.state.chat is None:
        raise HTTPException(status_code=503, detail="chat_unavailable")
    return request.app.state.chat


@router.get("/availability", response_model=ChatAvailability)
async def availability(request: Request, owner: str = Depends(get_principal)):
    identifier = await service(request).active_id(owner)
    survey = await request.app.state.sessions.get(identifier, owner) if identifier else None
    return ChatAvailability(active_survey=survey)


@router.get("", response_model=ChatHistory, summary="List saved chats")
async def list_chats(
    request: Request,
    owner: str = Depends(get_principal),
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None, max_length=80, description="next_cursor from the previous page"),
):
    boundary = None
    if cursor is not None:
        try:
            timestamp, identifier = cursor.split("|")
            activity = datetime.fromisoformat(timestamp)
            if activity.utcoffset() is None:
                raise ValueError
            boundary = (activity, UUID(identifier))
        except (ValueError, OverflowError):
            raise HTTPException(status_code=422, detail="invalid_chat_cursor") from None
    return await service(request).history(owner, limit, boundary)


@router.post("", response_model=ChatResponse, status_code=201)
async def open_chat(body: ChatCreate, request: Request, owner: str = Depends(get_principal)):
    return await service(request).open(owner, body.questionnaire_id)


@router.get("/{identifier}", response_model=ChatResponse, responses={404: {"model": ChatError}})
async def get_chat(identifier: UUID, request: Request, owner: str = Depends(get_principal)):
    return await service(request).get(identifier, owner)


@router.post("/{identifier}/messages", response_model=ChatResponse, responses={
    404: {"model": ChatError}, 409: {"model": ChatError},
})
async def send_message(identifier: UUID, body: ChatSend, request: Request, owner: str = Depends(get_principal)):
    await request.app.state.launch_limiter.check("chat:" + owner)
    return await service(request).send(identifier, owner, body)


@router.delete("/{identifier}", status_code=204, responses={404: {"model": ChatError}},
               description="Delete a chat. For a questionnaire chat this also deletes the questionnaire and its result.")
async def delete_chat(identifier: UUID, request: Request, owner: str = Depends(get_principal)):
    await service(request).delete(identifier, owner)
    return Response(status_code=204)
