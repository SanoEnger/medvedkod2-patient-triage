from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.encryption import JsonCipher, answer_context, message_context
from app.db.audit import delete_expired_audit_events, record_audit
from app.db.models import AnswerRecord, MessageRecord, SessionRecord
from app.db.nonces import delete_expired_nonces
from app.schemas.survey import SurveyStatus


async def lock_owner(db: AsyncSession, owner_id: str) -> None:
    await db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(owner_id, 0))))


async def create_session(
    db: AsyncSession,
    owner_id: str,
    *,
    demo_mode: bool,
    ttl_seconds: int = 86400,
    kind: str = "questionnaire",
    cipher: JsonCipher | None = None,
) -> SessionRecord:
    if not 0 < ttl_seconds <= 86400:
        raise ValueError("Session TTL must be between 1 and 86400 seconds")
    await lock_owner(db, owner_id)
    if kind not in ("questionnaire", "chat"):
        raise ValueError("Invalid session kind")
    now = datetime.now(UTC)
    record = SessionRecord(
        owner_id=owner_id,
        kind=kind,
        status=SurveyStatus.COMPLETED if kind == "chat" else SurveyStatus.COLLECTING,
        demo_mode=demo_mode,
        created_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
    )
    db.add(record)
    await db.flush()
    await record_audit(
        db,
        record.id,
        "session_created",
        {"step": 0, "status": str(record.status)},
        cipher=cipher,
    )
    return record


async def get_session(
    db: AsyncSession,
    session_id: UUID,
    owner_id: str,
    *,
    for_update: bool = False,
) -> SessionRecord | None:
    query = select(SessionRecord).where(
        SessionRecord.id == session_id,
        SessionRecord.owner_id == owner_id,
        SessionRecord.expires_at > func.now(),
    )
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    return await db.scalar(query)


async def append_answer(
    db: AsyncSession,
    session_id: UUID,
    owner_id: str,
    question_key: str,
    value: dict[str, Any],
    *,
    cipher: JsonCipher | None = None,
) -> AnswerRecord:
    record = await get_session(db, session_id, owner_id, for_update=True)
    if record is None:
        raise LookupError("session_not_found")
    if record.status != SurveyStatus.COLLECTING:
        raise ValueError("session_not_collecting")
    record.step += 1
    answer = AnswerRecord(
        session_id=record.id,
        question_key=question_key,
        value_jsonb=(
            cipher or JsonCipher.from_file(Settings.from_env().data_encryption_key_file)
        ).encrypt(
            value,
            answer_context(record.id, question_key),
        ),
        sequence_no=record.step,
    )
    db.add(answer)
    await db.flush()
    await record_audit(
        db,
        record.id,
        "answer_saved",
        {"step": record.step, "status": str(record.status)},
        cipher=cipher,
    )
    return answer


async def get_answers(
    db: AsyncSession, session_id: UUID, owner_id: str
) -> list[AnswerRecord]:
    result = await db.scalars(
        select(AnswerRecord)
        .join(SessionRecord)
        .where(
            SessionRecord.id == session_id,
            SessionRecord.owner_id == owner_id,
            SessionRecord.expires_at > func.now(),
        )
        .order_by(AnswerRecord.sequence_no),
    )
    return list(result)


async def delete_session(
    db: AsyncSession,
    session_id: UUID,
    owner_id: str,
    *,
    cipher: JsonCipher | None = None,
) -> bool:
    deleted = (
        await db.execute(
            delete(SessionRecord)
            .where(
                SessionRecord.id == session_id,
                SessionRecord.owner_id == owner_id,
            )
            .returning(SessionRecord.id, SessionRecord.status, SessionRecord.step),
        )
    ).first()
    if deleted is not None:
        await record_audit(
            db,
            None,
            "session_deleted",
            {"step": deleted.step, "status": str(deleted.status)},
            cipher=cipher,
        )
    return deleted is not None


async def delete_expired_sessions(
    db: AsyncSession,
    before: datetime | None = None,
    *,
    cipher: JsonCipher | None = None,
) -> int:
    now = before if before is not None else datetime.now(UTC)
    deleted = (
        await db.execute(
            delete(SessionRecord)
            .where(SessionRecord.expires_at <= now)
            .returning(SessionRecord.id, SessionRecord.status, SessionRecord.step),
        )
    ).all()
    for row in deleted:
        await record_audit(
            db,
            None,
            "session_expired",
            {"step": row.step, "status": str(row.status)},
            cipher=cipher,
        )
    await delete_expired_audit_events(db, now)
    await delete_expired_nonces(db, now)
    return len(deleted)


async def list_sessions(
    db: AsyncSession,
    owner_id: str,
    *,
    limit: int = 20,
    offset: int = 0,
) -> list[SessionRecord]:
    if not 1 <= limit <= 100 or offset < 0:
        raise ValueError("Invalid history pagination")
    rows = await db.scalars(
        select(SessionRecord)
        .where(
            SessionRecord.owner_id == owner_id,
            SessionRecord.expires_at > func.now(),
        )
        .order_by(SessionRecord.created_at.desc(), SessionRecord.id.desc())
        .limit(limit)
        .offset(offset),
    )
    return list(rows)


async def append_message(
    db: AsyncSession,
    session_id: UUID,
    owner_id: str,
    role: str,
    kind: str,
    content: dict[str, Any],
    *,
    cipher: JsonCipher | None = None,
    message_id: UUID | None = None,
) -> MessageRecord:
    if role not in ("assistant", "user", "system") or kind not in (
        "question",
        "answer",
        "result",
        "back",
        "text",
    ):
        raise ValueError("Invalid message role or kind")
    if await get_session(db, session_id, owner_id, for_update=True) is None:
        raise LookupError("session_not_found")
    sequence = await db.scalar(
        select(func.coalesce(func.max(MessageRecord.sequence_no), 0)).where(
            MessageRecord.session_id == session_id
        ),
    )
    identifier = message_id or uuid4()
    record = MessageRecord(
        id=identifier,
        session_id=session_id,
        role=role,
        kind=kind,
        sequence_no=sequence + 1,
        content_jsonb=(
            cipher or JsonCipher.from_file(Settings.from_env().data_encryption_key_file)
        ).encrypt(
            content,
            message_context(session_id, identifier),
        ),
    )
    db.add(record)
    await db.flush()
    return record


async def get_messages(
    db: AsyncSession, session_id: UUID, owner_id: str
) -> list[MessageRecord]:
    rows = await db.scalars(
        select(MessageRecord)
        .join(SessionRecord)
        .where(
            SessionRecord.id == session_id,
            SessionRecord.owner_id == owner_id,
            SessionRecord.expires_at > func.now(),
        )
        .order_by(MessageRecord.sequence_no),
    )
    return list(rows)
