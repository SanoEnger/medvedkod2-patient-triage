import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.core.config import Settings
from app.core.encryption import (
    DataEncryptionError,
    JsonCipher,
    answer_context,
    message_context,
    state_context,
)
from app.db.engine import create_engine
from app.db.models import AnswerRecord, MessageRecord, SessionRecord, TriageResultRecord
from app.db.results import decode_result
from sqlalchemy import insert, select

pytestmark = pytest.mark.postgres
RESULT = {
    "urgency": "EMERGENCY",
    "specialty": None,
    "place": "synthetic destination",
    "rationale": "synthetic historical rationale",
    "disclaimer": "synthetic disclaimer",
    "rule_codes": ["RF_CHEST_PAIN"],
    "needs_clarification": False,
}


def test_revision_03_results_are_moved_without_losing_history_or_idempotency(
    database_url,
):
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    cipher = JsonCipher.from_file(Settings.from_env().data_encryption_key_file)
    sid, mid = uuid4(), uuid4()
    value = {"category": "pain", "text": "synthetic migration text"}
    cache = {"synthetic-key": ["synthetic-hash", {"id": str(sid)}]}
    sealed_answer = cipher.encrypt(value, answer_context(sid, "primary_complaint"))
    sealed_message = cipher.encrypt(
        {"question_key": "primary_complaint", "value": value}, message_context(sid, mid)
    )

    async def before():
        engine = create_engine(database_url)
        try:
            async with engine.begin() as db:
                await db.execute(
                    insert(SessionRecord).values(
                        id=sid,
                        owner_id="synthetic:migration-final",
                        status="EMERGENCY_STOP",
                        step=1,
                        state_jsonb=cipher.encrypt(
                            {
                                "result": RESULT,
                                "rule_codes": RESULT["rule_codes"],
                                "idempotency": cache,
                            },
                            state_context(sid),
                        ),
                        demo_mode=True,
                    )
                )
                await db.execute(
                    insert(AnswerRecord).values(
                        session_id=sid,
                        question_key="primary_complaint",
                        sequence_no=1,
                        value_jsonb=sealed_answer,
                    )
                )
                await db.execute(
                    insert(MessageRecord).values(
                        id=mid,
                        session_id=sid,
                        sequence_no=1,
                        role="user",
                        kind="answer",
                        content_jsonb=sealed_message,
                    )
                )
        finally:
            await engine.dispose()

    async def after():
        from sqlalchemy.ext.asyncio import AsyncSession

        engine = create_engine(database_url)
        try:
            async with AsyncSession(engine) as db:
                result = await db.scalar(
                    select(TriageResultRecord).where(
                        TriageResultRecord.session_id == sid
                    )
                )
                assert decode_result(result, cipher) == {**RESULT, "analysis": None, "analysis_source": None}
                assert result.version == "legacy-unversioned"
                session = await db.get(SessionRecord, sid)
                state = cipher.decrypt(session.state_jsonb, state_context(sid))
                assert "result" not in state
                assert state["idempotency"] == cache
                assert state["rule_codes"] == RESULT["rule_codes"]
                assert (
                    await db.get(MessageRecord, mid)
                ).content_jsonb == sealed_message
                answer = await db.scalar(
                    select(AnswerRecord).where(AnswerRecord.session_id == sid)
                )
                assert answer.value_jsonb == sealed_answer
        finally:
            await engine.dispose()

    async def cleanup():
        engine = create_engine(database_url)
        try:
            async with engine.begin() as db:
                await db.execute(
                    SessionRecord.__table__.delete().where(SessionRecord.id == sid)
                )
        finally:
            await engine.dispose()

    command.downgrade(config, "20261118_03")
    try:
        asyncio.run(before())
        command.upgrade(config, "head")
        asyncio.run(after())
        with pytest.raises(RuntimeError, match="Cannot remove final schema"):
            command.downgrade(config, "20261118_03")
    finally:
        asyncio.run(cleanup())
        command.upgrade(config, "head")


def test_bad_encryption_key_rolls_back_the_whole_schema_upgrade(database_url):
    from sqlalchemy import inspect, text

    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    sid = uuid4()

    async def query(add=False, remove=False):
        engine = create_engine(database_url)
        try:
            async with engine.begin() as db:
                if add:
                    await db.execute(
                        insert(SessionRecord).values(
                            id=sid,
                            owner_id="synthetic:migration-bad-key",
                            demo_mode=True,
                            state_jsonb=JsonCipher(b"z" * 32).encrypt(
                                {"result": RESULT}, state_context(sid)
                            ),
                        )
                    )
                if remove:
                    await db.execute(
                        SessionRecord.__table__.delete().where(SessionRecord.id == sid)
                    )
                names = await db.run_sync(lambda sync: inspect(sync).get_table_names())
                revision = await db.scalar(
                    text("SELECT version_num FROM alembic_version")
                )
                return set(names), revision
        finally:
            await engine.dispose()

    command.downgrade(config, "20261118_03")
    try:
        asyncio.run(query(add=True))
        with pytest.raises(DataEncryptionError):
            command.upgrade(config, "head")
        names, revision = asyncio.run(query())
        assert revision == "20261118_03"
        assert names == {"sessions", "answers", "messages", "alembic_version"}
    finally:
        asyncio.run(query(remove=True))
        command.upgrade(config, "head")
