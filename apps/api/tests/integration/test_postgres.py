import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy", reason="Install the postgres extra")
pytest.importorskip("alembic", reason="Install the postgres extra")
pytest.importorskip("asyncpg", reason="Install the postgres extra")
pytest.importorskip("pytest_asyncio", reason="Install the test extra")

from alembic import command
from alembic.config import Config
from app.core.config import Settings
from app.core.encryption import JsonCipher, answer_context
from app.db import cleanup
from app.db.engine import create_engine
from app.db.models import AnswerRecord, SessionRecord
from app.db.repository import (
    append_answer,
    create_session,
    delete_expired_sessions,
    delete_session,
    get_answers,
    get_session,
)
from app.schemas.survey import SurveyStatus
from sqlalchemy import delete, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

pytestmark = pytest.mark.postgres
OWNER = "synthetic:owner"

def seal(session_id, question_key, value):
    return JsonCipher.from_file(Settings.from_env().data_encryption_key_file).encrypt(value, answer_context(session_id, question_key))


def test_migration_round_trip(database_url):
    from pathlib import Path

    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, "head")
    command.check(config)
    command.downgrade(config, "base")

    async def remaining_tables():
        engine = create_engine(database_url)
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(lambda sync: inspect(sync).get_table_names())
        finally:
            await engine.dispose()

    assert set(asyncio.run(remaining_tables())) <= {"alembic_version"}
    command.upgrade(config, "head")
    command.check(config)


@pytest.mark.asyncio
async def test_indexes_and_foreign_key(engine):
    async with engine.connect() as connection:
        def schema(sync):
            inspector = inspect(sync)
            return (
                inspector.get_indexes("sessions"),
                inspector.get_indexes("answers"),
                inspector.get_foreign_keys("answers"),
            )
        sessions, answers, foreign_keys = await connection.run_sync(schema)
    assert any(index["column_names"] == ["expires_at"] for index in sessions)
    assert any(index["column_names"] == ["session_id", "sequence_no"] and index["unique"]
               for index in answers)
    assert foreign_keys[0]["referred_table"] == "sessions"
    assert foreign_keys[0]["options"]["ondelete"] == "CASCADE"


@pytest.mark.asyncio
async def test_server_defaults(db):
    result = (await db.execute(text(
        "INSERT INTO sessions (owner_id) VALUES (:owner) "
        "RETURNING id, status, step, demo_mode, created_at, expires_at"
    ), {"owner": OWNER})).mappings().one()
    assert result["id"] is not None
    assert result["status"] == "COLLECTING"
    assert result["step"] == 0
    assert result["demo_mode"] is False
    assert result["created_at"].tzinfo is not None
    assert result["expires_at"] - result["created_at"] == timedelta(hours=24)


@pytest.mark.asyncio
async def test_jsonb_order_and_owner_isolation(db):
    survey = await create_session(db, OWNER, demo_mode=True)
    payload = {"synthetic": True, "values": [1, None, "example"]}
    await append_answer(db, survey.id, OWNER, "primary_complaint", payload)
    await append_answer(db, survey.id, OWNER, "patient_context", {"synthetic": True})
    answers = await get_answers(db, survey.id, OWNER)
    assert [answer.sequence_no for answer in answers] == [1, 2]
    assert set(answers[0].value_jsonb) == {"v", "n", "c"}
    assert JsonCipher.from_file(Settings.from_env().data_encryption_key_file).decrypt(answers[0].value_jsonb, answer_context(survey.id, "primary_complaint")) == payload
    assert survey.step == 2
    assert survey.demo_mode is True
    assert await get_session(db, survey.id, "synthetic:other") is None
    assert await get_answers(db, survey.id, "synthetic:other") == []
    assert await delete_session(db, survey.id, "synthetic:other") is False
    with pytest.raises(LookupError):
        await append_answer(db, survey.id, "synthetic:other", "other", {})
    assert await get_session(db, survey.id, OWNER) is not None


@pytest.mark.asyncio
async def test_delete_cascades_without_orm_relationships(db):
    survey = await create_session(db, OWNER, demo_mode=True)
    await append_answer(db, survey.id, OWNER, "primary_complaint", {"synthetic": True})
    assert await delete_session(db, survey.id, OWNER) is True
    assert await db.scalar(select(func.count()).select_from(AnswerRecord)) == 0
    assert await delete_session(db, survey.id, OWNER) is False


@pytest.mark.asyncio
async def test_expired_sessions_are_hidden_and_purged_with_answers(db):
    now = datetime.now(UTC)
    expired = SessionRecord(
        owner_id=OWNER, created_at=now - timedelta(hours=2),
        expires_at=now - timedelta(hours=1), demo_mode=True,
    )
    boundary = SessionRecord(
        owner_id=OWNER, created_at=now - timedelta(hours=1),
        expires_at=now, demo_mode=True,
    )
    db.add_all([expired, boundary])
    active = await create_session(db, OWNER, demo_mode=True)
    db.add(AnswerRecord(
        session_id=expired.id, question_key="synthetic", value_jsonb=seal(expired.id, "synthetic", {}),
        sequence_no=1,
    ))
    await db.flush()
    assert await get_session(db, expired.id, OWNER) is None
    assert await get_answers(db, expired.id, OWNER) == []
    assert await delete_expired_sessions(db, before=now) == 2
    assert await db.scalar(select(func.count()).select_from(AnswerRecord)) == 0
    assert await get_session(db, active.id, OWNER) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("ttl_seconds", [0, 86401])
async def test_invalid_application_ttl(db, ttl_seconds):
    with pytest.raises(ValueError, match="TTL"):
        await create_session(db, OWNER, demo_mode=True, ttl_seconds=ttl_seconds)


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("expires_at", "too_long"),
    ("expires_at", "zero"),
    ("step", -1),
    ("status", "UNRECOGNIZED"),
])
async def test_database_rejects_invalid_session_state(db, field, value):
    now = datetime.now(UTC)
    values = {"owner_id": OWNER, "created_at": now, "expires_at": now + timedelta(hours=1)}
    values[field] = (
        now + timedelta(hours=25) if value == "too_long" else
        now if value == "zero" else value
    )
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(SessionRecord(**values))
            await db.flush()


@pytest.mark.asyncio
async def test_answer_requires_existing_session(db):
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(AnswerRecord(
                session_id=uuid4(), question_key="synthetic",
                value_jsonb=seal(uuid4(), "synthetic", {}), sequence_no=1,
            ))
            await db.flush()


@pytest.mark.asyncio
@pytest.mark.parametrize("duplicate", ["sequence", "question"])
async def test_answer_order_and_question_are_unique(db, duplicate):
    survey = await create_session(db, OWNER, demo_mode=True)
    await append_answer(db, survey.id, OWNER, "primary_complaint", {})
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(AnswerRecord(
                session_id=survey.id,
                question_key="primary_complaint" if duplicate == "question" else "other",
                value_jsonb=seal(survey.id, "primary_complaint" if duplicate == "question" else "other", {}), sequence_no=2 if duplicate == "question" else 1,
            ))
            await db.flush()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [SurveyStatus.EMERGENCY_STOP, SurveyStatus.COMPLETED])
async def test_terminal_session_rejects_new_answers(db, status):
    survey = await create_session(db, OWNER, demo_mode=True)
    survey.status = status
    await db.flush()
    with pytest.raises(ValueError, match="session_not_collecting"):
        await append_answer(db, survey.id, OWNER, "synthetic", {})
    assert survey.step == 0


@pytest.mark.asyncio
async def test_concurrent_answers_lock_and_refresh_the_session(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory.begin() as db:
        survey = await create_session(db, OWNER, demo_mode=True)
        session_id = survey.id
    barrier = asyncio.Event()
    ready = 0

    async def write(question_key):
        nonlocal ready
        async with factory.begin() as db:
            snapshot = await get_session(db, session_id, OWNER)
            ready += 1
            if ready == 2:
                barrier.set()
            await barrier.wait()
            answer = await append_answer(db, session_id, OWNER, question_key, {})
            assert snapshot.step == answer.sequence_no
            return answer.sequence_no

    try:
        order = await asyncio.wait_for(
            asyncio.gather(write("primary_complaint"), write("patient_context")),
            timeout=15,
        )
        assert sorted(order) == [1, 2]
        async with factory() as db:
            assert (await get_session(db, session_id, OWNER)).step == 2
    finally:
        async with factory.begin() as db:
            await delete_session(db, session_id, OWNER)


@pytest.mark.asyncio
async def test_cleanup_command_commits_and_reports_only_count(engine, capsys):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    async with factory.begin() as db:
        expired = SessionRecord(
            owner_id=OWNER, created_at=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1), demo_mode=True,
        )
        db.add(expired)
        await create_session(db, OWNER, demo_mode=True)
    try:
        await cleanup.main()
        assert capsys.readouterr().out.strip() == '{"deleted_sessions": 1}'
        async with factory() as db:
            assert await db.scalar(select(func.count()).select_from(SessionRecord)) == 1
    finally:
        async with factory.begin() as db:
            await db.execute(delete(SessionRecord).where(SessionRecord.owner_id == OWNER))
