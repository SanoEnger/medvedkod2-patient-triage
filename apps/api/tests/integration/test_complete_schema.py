import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.core.config import Settings
from app.core.encryption import (
    DataEncryptionError,
    JsonCipher,
    audit_context,
    rule_context,
    triage_context,
)
from app.db.audit import record_audit
from app.db.models import (
    AuditEventRecord,
    IntegrationNonceRecord,
    SafetyRuleVersionRecord,
    TriageResultRecord,
)
from app.db.nonces import (
    consume_nonce,
    delete_expired_nonces,
    nonce_hash,
    register_nonce,
)
from app.db.repository import create_session, delete_expired_sessions, delete_session
from app.db.results import encode_result, get_triage_result, save_triage_result
from app.db.safety_catalog import result_version, runtime_rules, verify_runtime_catalog
from sqlalchemy import delete, func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

pytestmark = [pytest.mark.postgres, pytest.mark.asyncio]
OWNER = "synthetic:complete-schema"
RESULT = {
    "analysis": None,
    "analysis_source": None,
    "urgency": "EMERGENCY",
    "specialty": None,
    "place": "synthetic destination",
    "rationale": "synthetic confidential rationale",
    "disclaimer": "synthetic disclaimer",
    "rule_codes": ["RF_CHEST_PAIN"],
    "needs_clarification": False,
}


def cipher():
    return JsonCipher.from_file(Settings.from_env().data_encryption_key_file)


async def test_complete_schema_indexes_and_rules(engine, db):
    async with engine.connect() as connection:
        names = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
        audit_indexes = await connection.run_sync(
            lambda sync: inspect(sync).get_indexes("audit_events")
        )
    assert set(names) == {
        "alembic_version",
        "sessions",
        "answers",
        "messages",
        "triage_results",
        "safety_rule_versions",
        "audit_events",
        "integration_nonces",
        "clinic_organizations",
        "clinic_branches",
        "clinic_payments",
        "clinic_addresses",
        "clinic_sources",
        "clinic_oms_participants",
    }
    assert any(index["column_names"] == ["created_at"] for index in audit_indexes)
    await verify_runtime_catalog(db, cipher())
    rows = list(await db.scalars(select(SafetyRuleVersionRecord)))
    assert {row.code for row in rows} == {rule["code"] for rule in runtime_rules()}
    expected = {rule["code"]: rule for rule in runtime_rules()}
    for row in rows:
        assert set(row.predicates) == {"v", "n", "c"}
        assert (
            cipher().decrypt(row.predicates, rule_context(row.code, row.version))
            == expected[row.code]["predicates"]
        )


async def test_rule_catalog_change_requires_matching_implementation(db):
    record = await db.get(SafetyRuleVersionRecord, "RF_CHEST_PAIN")
    record.enabled = False
    await db.flush()
    with pytest.raises(DataEncryptionError, match="does not match"):
        await verify_runtime_catalog(db, cipher())


async def test_result_roundtrip_encryption_upsert_and_owner(db):
    session = await create_session(db, OWNER, demo_mode=True)
    first = await save_triage_result(db, session.id, OWNER, RESULT, cipher=cipher())
    identifier = first.id
    assert await get_triage_result(db, session.id, OWNER, cipher=cipher()) == RESULT
    assert (
        await get_triage_result(db, session.id, "synthetic:other", cipher=cipher())
        is None
    )
    for field in ("specialty", "place", "rationale", "rule_codes", "details_jsonb"):
        sealed = getattr(first, field)
        assert set(sealed) == {"v", "n", "c"}
        assert "confidential" not in json.dumps(sealed)
    version, versions = result_version(RESULT["rule_codes"])
    assert first.version == version
    assert (
        cipher().decrypt(first.rule_codes, triage_context(session.id, "rule_codes"))[
            "versions"
        ]
        == versions
    )
    changed = {**RESULT, "rationale": "synthetic updated rationale", "analysis": "synthetic confidential analysis", "analysis_source": "groq"}
    updated = await save_triage_result(db, session.id, OWNER, changed, cipher=cipher())
    assert "confidential analysis" not in json.dumps(updated.details_jsonb)
    assert updated.id == identifier
    assert await db.scalar(select(func.count()).select_from(TriageResultRecord)) == 1
    assert await get_triage_result(db, session.id, OWNER, cipher=cipher()) == changed


async def test_result_is_unique_and_does_not_accept_unknown_urgency(db):
    session = await create_session(db, OWNER, demo_mode=True)
    await save_triage_result(db, session.id, OWNER, RESULT, cipher=cipher())
    values = encode_result(session.id, RESULT, cipher(), "synthetic-v0", {})
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(TriageResultRecord(**values))
            await db.flush()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.execute(
                TriageResultRecord.__table__.update().values(urgency="INVALID")
            )
    with pytest.raises(LookupError):
        await save_triage_result(
            db, session.id, "synthetic:other", RESULT, cipher=cipher()
        )


async def test_result_ciphertext_cannot_be_moved_between_columns(db):
    session = await create_session(db, OWNER, demo_mode=True)
    record = await save_triage_result(db, session.id, OWNER, RESULT, cipher=cipher())
    record.rationale = record.place
    await db.flush()
    with pytest.raises(DataEncryptionError):
        await get_triage_result(db, session.id, OWNER, cipher=cipher())


async def test_result_cascade_audit_anonymization_and_ttl(db):
    session = await create_session(db, OWNER, demo_mode=True)
    identifier = session.id
    await save_triage_result(db, identifier, OWNER, RESULT, cipher=cipher())
    assert await delete_session(db, identifier, OWNER)
    assert await db.scalar(select(func.count()).select_from(TriageResultRecord)) == 0
    audits = list(
        await db.scalars(select(AuditEventRecord).order_by(AuditEventRecord.created_at))
    )
    assert {row.kind for row in audits} == {"session_created", "session_deleted"}
    assert all(row.session_id is None for row in audits)
    for row in audits:
        meta = cipher().decrypt(row.meta, audit_context(row.id))
        assert set(meta) <= {"status", "step", "version"}
        row.created_at = datetime.now(UTC) - timedelta(hours=25)
    await db.flush()
    await delete_expired_sessions(db)
    remaining = list(await db.scalars(select(AuditEventRecord)))
    assert remaining == []


async def test_expired_result_cannot_be_read_and_is_purged(db):
    session = await create_session(db, OWNER, demo_mode=True)
    await save_triage_result(db, session.id, OWNER, RESULT, cipher=cipher())
    session.created_at = datetime.now(UTC) - timedelta(hours=2)
    session.expires_at = datetime.now(UTC) - timedelta(hours=1)
    await db.flush()
    assert await get_triage_result(db, session.id, OWNER, cipher=cipher()) is None
    assert await delete_expired_sessions(db) == 1
    assert await db.scalar(select(func.count()).select_from(TriageResultRecord)) == 0


@pytest.mark.parametrize("key", ["text", "prompt", "token", "owner_id", "snils"])
async def test_audit_rejects_patient_input_and_secrets(db, key):
    with pytest.raises(ValueError, match="allowlisted"):
        await record_audit(
            db, None, "session_deleted", {key: "synthetic forbidden content"}
        )


async def test_plaintext_audit_and_rule_predicates_are_rejected_by_database(db):
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(
                AuditEventRecord(
                    kind="session_deleted", meta={"text": "synthetic plaintext"}
                )
            )
            await db.flush()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(
                SafetyRuleVersionRecord(
                    code="SYNTHETIC_NEW",
                    version="v0",
                    severity="P0",
                    predicates={},
                    enabled=False,
                )
            )
            await db.flush()


async def test_nonce_consumption_is_atomic_and_only_hash_is_stored(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    raw = "synthetic-nonce-" + str(uuid4())
    expires = datetime.now(UTC) + timedelta(minutes=5)
    async with factory.begin() as db:
        assert await register_nonce(db, raw, expires)
        assert not await register_nonce(db, raw, expires)

    async def consume():
        async with factory.begin() as db:
            return await consume_nonce(db, raw)

    try:
        assert sum(await asyncio.gather(*(consume() for _ in range(5)))) == 1
        async with factory() as db:
            row = await db.get(IntegrationNonceRecord, nonce_hash(raw))
            assert row.used_at is not None
            assert raw != row.nonce_hash and len(row.nonce_hash) == 64
    finally:
        async with factory.begin() as db:
            await db.execute(
                delete(IntegrationNonceRecord).where(
                    IntegrationNonceRecord.nonce_hash == nonce_hash(raw)
                )
            )


async def test_nonce_expiration_and_cleanup(db):
    raw = "synthetic-expired-nonce"
    db.add(
        IntegrationNonceRecord(
            nonce_hash=nonce_hash(raw),
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    )
    await db.flush()
    assert not await consume_nonce(db, raw)
    assert await delete_expired_nonces(db) == 1
    assert not await consume_nonce(db, "synthetic-unregistered")
    with pytest.raises(ValueError):
        await register_nonce(db, raw, datetime.now(UTC) - timedelta(seconds=1))
