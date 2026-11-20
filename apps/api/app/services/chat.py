import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid5

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.encryption import (
    DataEncryptionError,
    answer_context,
    message_context,
    state_context,
)
from app.db.models import AnswerRecord, MessageRecord, SessionRecord
from app.db.repository import (
    append_message,
    create_session,
    delete_session,
    get_session,
    lock_owner,
)
from app.db.results import get_triage_result
from app.integrations.chat_agent import AgentReply
from app.integrations.groq.exceptions import GroqError
from app.schemas.chat import ChatMessage, ChatResponse
from app.schemas.survey import SurveyStatus
from app.services.safety import find_emergency_rules
from app.services.sessions import EMERGENCY_MESSAGE

GREETING = "Здравствуйте! Я МедВед. Спросите, что вас беспокоит или что нужно уточнить перед обращением к врачу."
FOLLOW_UP = "Я вижу ответы и результат вашего опроса. Что вы хотите уточнить?"


class ChatService:
    def __init__(self, factory, cipher, agent, *, ttl_seconds=86400, demo_mode=False):
        self.factory, self.cipher, self.agent = factory, cipher, agent
        self.ttl_seconds, self.demo_mode = ttl_seconds, demo_mode

    @asynccontextmanager
    async def transaction(self):
        try:
            async with self.factory.begin() as db:
                yield db
        except (SQLAlchemyError, OSError, DataEncryptionError):
            raise HTTPException(status_code=503, detail="chat_storage_unavailable") from None

    async def active_survey(self, db, owner):
        return await db.scalar(select(SessionRecord).where(
            SessionRecord.owner_id == owner, SessionRecord.kind == "questionnaire",
            SessionRecord.status.in_([SurveyStatus.COLLECTING, SurveyStatus.REVIEWING]),
            SessionRecord.expires_at > datetime.now(UTC),
        ).order_by(SessionRecord.created_at.desc()).limit(1))

    async def active_id(self, owner):
        async with self.transaction() as db:
            record = await self.active_survey(db, owner)
            return record.id if record else None

    async def available(self, db, owner):
        await lock_owner(db, owner)
        if await self.active_survey(db, owner) is not None:
            raise HTTPException(status_code=409, detail="questionnaire_in_progress")

    async def session(self, db, identifier, owner):
        record = await get_session(db, identifier, owner, for_update=True)
        if record is None:
            raise HTTPException(status_code=404, detail="chat_not_found")
        if record.kind == "questionnaire" and record.status != SurveyStatus.COMPLETED:
            raise HTTPException(status_code=409, detail="questionnaire_not_completed")
        return record

    async def rows(self, db, identifier):
        return list(await db.scalars(select(MessageRecord).where(
            MessageRecord.session_id == identifier, MessageRecord.kind == "text",
        ).order_by(MessageRecord.sequence_no)))

    def content(self, row):
        return self.cipher.decrypt(row.content_jsonb, message_context(row.session_id, row.id))

    async def response(self, db, record, owner):
        messages = []
        pending = False
        retryable = False
        for row in await self.rows(db, record.id):
            value = self.content(row)
            messages.append(ChatMessage(id=row.id, role=row.role, text=value["text"],
                created_at=row.created_at.isoformat(), emergency=value.get("emergency", False),
                client_message_id=value.get("client_message_id")))
            if row.role == "user":
                pending = True
                retryable = value.get("processing_until", 0) <= datetime.now(UTC).timestamp()
            else:
                pending = False
                retryable = False
        result = await get_triage_result(db, record.id, owner, cipher=self.cipher) if record.kind == "questionnaire" else None
        return ChatResponse(
            id=record.id, questionnaire_id=record.id if record.kind == "questionnaire" else None,
            messages=messages, result=result, pending=pending, retryable=retryable,
            emergency=any(message.emergency for message in messages),
        )

    async def open(self, owner, questionnaire_id=None):
        async with self.transaction() as db:
            await self.available(db, owner)
            if questionnaire_id:
                record = await self.session(db, questionnaire_id, owner)
                if record.kind != "questionnaire":
                    raise HTTPException(status_code=400, detail="invalid_questionnaire")
            else:
                record = await create_session(db, owner, kind="chat",
                    ttl_seconds=self.ttl_seconds, demo_mode=self.demo_mode, cipher=self.cipher)
            if not await self.rows(db, record.id):
                await append_message(db, record.id, owner, "assistant", "text",
                    {"text": FOLLOW_UP if questionnaire_id else GREETING}, cipher=self.cipher)
            return await self.response(db, record, owner)

    async def get(self, identifier, owner):
        async with self.transaction() as db:
            record = await self.session(db, identifier, owner)
            return await self.response(db, record, owner)

    async def context(self, db, record, owner):
        if record.kind == "chat":
            return {}, 0
        rows = await db.scalars(select(AnswerRecord).where(AnswerRecord.session_id == record.id))
        answers = {row.question_key: self.cipher.decrypt(row.value_jsonb,
            answer_context(record.id, row.question_key)) for row in rows}
        state = self.cipher.decrypt(record.state_jsonb, state_context(record.id)) if record.state_jsonb else {}
        return {"answers": answers, "result": await get_triage_result(db, record.id, owner, cipher=self.cipher)}, state.get("revision", 0)

    async def clear_lease(self, identifier, message_id, owner):
        async with self.transaction() as db:
            if await get_session(db, identifier, owner, for_update=True):
                row = await db.get(MessageRecord, message_id)
                if row:
                    value = self.content(row)
                    value["processing_until"] = 0
                    row.content_jsonb = self.cipher.encrypt(value, message_context(identifier, message_id))

    async def send(self, identifier, owner, request):
        message_id = uuid5(identifier, str(request.client_message_id))
        reply_id = uuid5(message_id, "assistant")
        async with self.transaction() as db:
            await self.available(db, owner)
            record = await self.session(db, identifier, owner)
            rows = await self.rows(db, identifier)
            if any(self.content(row).get("emergency") for row in rows):
                raise HTTPException(status_code=409, detail="chat_emergency_stop")
            previous = next((row for row in rows if row.id == message_id), None)
            if len(rows) >= 201 and previous is None:
                raise HTTPException(status_code=429, detail="chat_message_limit")
            if previous:
                value = self.content(previous)
                if value["text"] != request.text:
                    raise HTTPException(status_code=409, detail="idempotency_conflict")
                if any(row.id == reply_id for row in rows):
                    return await self.response(db, record, owner)
                if value.get("processing_until", 0) > datetime.now(UTC).timestamp():
                    raise HTTPException(status_code=409, detail="chat_reply_pending")
            else:
                if rows and rows[-1].role == "user":
                    raise HTTPException(status_code=409, detail="chat_turn_pending")
                previous = await append_message(db, identifier, owner, "user", "text",
                    {"text": request.text}, cipher=self.cipher, message_id=message_id)
                rows.append(previous)
            previous.content_jsonb = self.cipher.encrypt(
                {"text": request.text, "client_message_id": str(request.client_message_id), "processing_until": datetime.now(UTC).timestamp() + 90},
                message_context(identifier, message_id))
            context, revision = await self.context(db, record, owner)
            history, size = [], 0
            for row in reversed(rows[-20:]):
                value = self.content(row)
                if size + len(value["text"]) > 12000:
                    break
                history.insert(0, {"role": row.role, "content": value["text"]})
                size += len(value["text"])
        try:
            answers = {**context.get("answers", {}),
                "primary_complaint": {"text": request.text, "category": "other"}}
            emergency = bool(find_emergency_rules(answers))
            reply = AgentReply(text=EMERGENCY_MESSAGE, emergency=True) if emergency else await self.agent.reply(history, context)
            if reply.emergency:
                # A model-triggered escalation uses the same reviewed message.
                reply = AgentReply(text=EMERGENCY_MESSAGE, emergency=True)
        except (GroqError, asyncio.CancelledError) as error:
            await self.clear_lease(identifier, message_id, owner)
            if isinstance(error, asyncio.CancelledError):
                raise
            raise HTTPException(status_code=503, detail="chat_agent_unavailable") from None
        async with self.transaction() as db:
            await self.available(db, owner)
            record = await self.session(db, identifier, owner)
            _, current_revision = await self.context(db, record, owner)
            if current_revision != revision:
                raise HTTPException(status_code=409, detail="questionnaire_changed")
            if not await db.get(MessageRecord, reply_id):
                await append_message(db, identifier, owner, "assistant", "text",
                    reply.model_dump(), cipher=self.cipher, message_id=reply_id)
            return await self.response(db, record, owner)

    async def delete(self, identifier, owner):
        async with self.transaction() as db:
            record = await self.session(db, identifier, owner)
            if record.kind != "chat":
                raise HTTPException(status_code=409, detail="delete_questionnaire_from_survey")
            await delete_session(db, identifier, owner, cipher=self.cipher)
