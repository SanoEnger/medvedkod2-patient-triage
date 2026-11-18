import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IntegrationNonceRecord


def nonce_hash(value: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 512:
        raise ValueError("Invalid nonce")
    return hashlib.sha256(value.encode()).hexdigest()


async def register_nonce(db: AsyncSession, value: str, expires_at: datetime) -> bool:
    now = datetime.now(UTC)
    if expires_at.tzinfo is None or not now < expires_at <= now + timedelta(hours=24):
        raise ValueError("Invalid nonce expiration")
    identifier = await db.scalar(
        insert(IntegrationNonceRecord)
        .values(
            nonce_hash=nonce_hash(value),
            expires_at=expires_at,
        )
        .on_conflict_do_nothing()
        .returning(IntegrationNonceRecord.nonce_hash)
    )
    return identifier is not None


async def consume_nonce(db: AsyncSession, value: str) -> bool:
    now = datetime.now(UTC)
    identifier = await db.scalar(
        update(IntegrationNonceRecord)
        .where(
            IntegrationNonceRecord.nonce_hash == nonce_hash(value),
            IntegrationNonceRecord.used_at.is_(None),
            IntegrationNonceRecord.expires_at > now,
        )
        .values(used_at=now)
        .returning(IntegrationNonceRecord.nonce_hash)
    )
    return identifier is not None


async def delete_expired_nonces(db: AsyncSession, now: datetime | None = None) -> int:
    rows = await db.scalars(
        delete(IntegrationNonceRecord)
        .where(
            IntegrationNonceRecord.expires_at <= (now or datetime.now(UTC)),
        )
        .returning(IntegrationNonceRecord.nonce_hash)
    )
    return len(rows.all())
