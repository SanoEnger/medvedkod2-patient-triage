from datetime import UTC, datetime
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import DataEncryptionError, JsonCipher, triage_context
from app.db.models import SessionRecord, TriageResultRecord
from app.db.repository import get_session
from app.db.safety_catalog import result_version
from app.schemas.survey import TriageResponse


def encode_result(
    session_id: UUID, result: dict, cipher: JsonCipher, version: str, versions: dict
) -> dict:
    value = TriageResponse.model_validate(result).model_dump(mode="json")
    return {
        "session_id": session_id,
        "urgency": value["urgency"],
        "version": version,
        **{
            field: cipher.encrypt(
                {"value": value[field]}, triage_context(session_id, field)
            )
            for field in ("specialty", "place", "rationale")
        },
        "rule_codes": cipher.encrypt(
            {"codes": value["rule_codes"], "versions": versions},
            triage_context(session_id, "rule_codes"),
        ),
        "details_jsonb": cipher.encrypt(
            {
                "disclaimer": value["disclaimer"],
                "needs_clarification": value["needs_clarification"],
            },
            triage_context(session_id, "details_jsonb"),
        ),
    }


def decode_result(record: TriageResultRecord, cipher: JsonCipher) -> dict:
    try:
        value = {
            "urgency": record.urgency,
            **{
                field: cipher.decrypt(
                    getattr(record, field), triage_context(record.session_id, field)
                )["value"]
                for field in ("specialty", "place", "rationale")
            },
            "rule_codes": cipher.decrypt(
                record.rule_codes, triage_context(record.session_id, "rule_codes")
            )["codes"],
            **cipher.decrypt(
                record.details_jsonb, triage_context(record.session_id, "details_jsonb")
            ),
        }
        return TriageResponse.model_validate(value).model_dump(mode="json")
    except (KeyError, TypeError, ValidationError):
        raise DataEncryptionError(
            "Stored result schema authentication failed"
        ) from None


async def get_triage_result(
    db: AsyncSession, session_id: UUID, owner_id: str, *, cipher: JsonCipher
) -> dict | None:
    record = await db.scalar(
        select(TriageResultRecord)
        .join(SessionRecord)
        .where(
            TriageResultRecord.session_id == session_id,
            SessionRecord.owner_id == owner_id,
            SessionRecord.expires_at > datetime.now(UTC),
        )
    )
    return decode_result(record, cipher) if record is not None else None


async def save_triage_result(
    db: AsyncSession,
    session_id: UUID,
    owner_id: str,
    result: dict,
    *,
    cipher: JsonCipher,
) -> TriageResultRecord:
    if await get_session(db, session_id, owner_id, for_update=True) is None:
        raise LookupError("session_not_found")
    version, versions = result_version(result["rule_codes"])
    values = encode_result(session_id, result, cipher, version, versions)
    record = await db.scalar(
        select(TriageResultRecord).where(TriageResultRecord.session_id == session_id)
    )
    if record is None:
        record = TriageResultRecord(**values)
        db.add(record)
    else:
        for field, value in values.items():
            setattr(record, field, value)
        record.updated_at = datetime.now(UTC)
    await db.flush()
    return record


async def delete_triage_result(
    db: AsyncSession, session_id: UUID, owner_id: str
) -> None:
    if await get_session(db, session_id, owner_id, for_update=True) is None:
        raise LookupError("session_not_found")
    await db.execute(
        delete(TriageResultRecord).where(TriageResultRecord.session_id == session_id)
    )
