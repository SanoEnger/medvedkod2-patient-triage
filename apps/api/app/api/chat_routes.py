from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.core.security import get_principal
from app.schemas.chat import ChatAvailability, ChatCreate, ChatResponse, ChatSend

router = APIRouter(prefix="/api/v1/chats", tags=["chat"])


def service(request):
    if request.app.state.chat is None:
        raise HTTPException(status_code=503, detail="chat_unavailable")
    return request.app.state.chat


@router.get("/availability", response_model=ChatAvailability)
async def availability(request: Request, owner: str = Depends(get_principal)):
    identifier = await service(request).active_id(owner)
    survey = await request.app.state.sessions.get(identifier, owner) if identifier else None
    return ChatAvailability(active_survey=survey)


@router.post("", response_model=ChatResponse, status_code=201)
async def open_chat(body: ChatCreate, request: Request, owner: str = Depends(get_principal)):
    return await service(request).open(owner, body.questionnaire_id)


@router.get("/{identifier}", response_model=ChatResponse)
async def get_chat(identifier: UUID, request: Request, owner: str = Depends(get_principal)):
    return await service(request).get(identifier, owner)


@router.post("/{identifier}/messages", response_model=ChatResponse)
async def send_message(identifier: UUID, body: ChatSend, request: Request, owner: str = Depends(get_principal)):
    await request.app.state.launch_limiter.check("chat:" + owner)
    return await service(request).send(identifier, owner, body)


@router.delete("/{identifier}", status_code=204)
async def delete_chat(identifier: UUID, request: Request, owner: str = Depends(get_principal)):
    await service(request).delete(identifier, owner)
    return Response(status_code=204)
