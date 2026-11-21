from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from app.schemas.survey import SessionResponse, StrictModel, TriageResponse


class ChatCreate(StrictModel):
    accepted_disclaimer: Literal[True]
    questionnaire_id: UUID | None = None


class ChatSend(StrictModel):
    client_message_id: UUID
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def strip_text(cls, value):
        if not value.strip():
            raise ValueError("empty_message")
        return value.strip()


class ChatMessage(StrictModel):
    id: UUID
    role: Literal["user", "assistant"]
    text: str
    created_at: str
    emergency: bool = False
    client_message_id: UUID | None = None


class ChatResponse(StrictModel):
    id: UUID
    questionnaire_id: UUID | None
    messages: list[ChatMessage]
    result: TriageResponse | None
    emergency: bool = False
    pending: bool = False
    retryable: bool = False


class ChatAvailability(StrictModel):
    active_survey: SessionResponse | None


class ChatSummary(StrictModel):
    id: UUID
    kind: Literal["chat", "questionnaire"]
    title: str
    created_at: datetime
    last_activity_at: datetime
    expires_at: datetime
    emergency: bool


class ChatHistory(StrictModel):
    items: list[ChatSummary]
    next_cursor: str | None


class ChatError(StrictModel):
    detail: str
