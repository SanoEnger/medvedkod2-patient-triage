import re
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.encryption import JsonCipher, audit_context
from app.db.models import AuditEventRecord
from app.schemas.survey import SurveyStatus

AUDIT_KINDS = {
    "session_created",
    "answer_saved",
    "session_rewound",
    "triage_saved",
    "session_deleted",
    "session_expired",
}


async def record_audit(
    db: AsyncSession,
    session_id: UUID | None,
    kind: str,
    meta: dict,
    *,
    cipher: JsonCipher | None = None,
) -> AuditEventRecord:
    if kind not in AUDIT_KINDS or set(meta) - {"step", "status", "version"}:
        raise ValueError("Only allowlisted technical audit metadata may be stored")
    if "step" in meta and (type(meta["step"]) is not int or meta["step"] < 0):
        raise ValueError("Invalid audit step")
    if "status" in meta and meta["status"] not in {
        str(status) for status in SurveyStatus
    }:
        raise ValueError("Invalid audit status")
    if "version" in meta and (
        not isinstance(meta["version"], str)
        or not re.fullmatch(r"[a-zA-Z0-9._-]{1,128}", meta["version"])
    ):
        raise ValueError("Invalid audit version")
    identifier = uuid4()
    cipher = cipher or JsonCipher.from_file(
        Settings.from_env().data_encryption_key_file
    )
    record = AuditEventRecord(
        id=identifier,
        session_id=session_id,
        kind=kind,
        meta=cipher.encrypt(meta, audit_context(identifier)),
    )
    db.add(record)
    await db.flush()
    return record


async def delete_expired_audit_events(
    db: AsyncSession, now: datetime | None = None
) -> int:
    rows = await db.scalars(
        delete(AuditEventRecord)
        .where(
            AuditEventRecord.created_at
            <= (now or datetime.now(UTC)) - timedelta(hours=24),
        )
        .returning(AuditEventRecord.id)
    )
    return len(rows.all())
