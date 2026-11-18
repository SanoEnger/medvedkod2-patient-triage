import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.core.config import Settings
from app.core.encryption import JsonCipher, answer_context, message_context
from app.db.engine import create_engine
from sqlalchemy import text

pytestmark = pytest.mark.postgres


def test_existing_plaintext_is_encrypted_and_backfilled_as_history(database_url):
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    identifier = uuid4()
    original = {"category": "skin", "text": "synthetic migration marker"}
    cipher = JsonCipher.from_file(Settings.from_env().data_encryption_key_file)

    async def query(sql, parameters=None):
        engine = create_engine(database_url)
        try:
            async with engine.begin() as connection:
                result = await connection.execute(text(sql), parameters or {})
                return list(result.mappings()) if result.returns_rows else []
        finally:
            await engine.dispose()

    command.downgrade(config, "20261118_01")
    try:
        asyncio.run(query(
            "INSERT INTO sessions (id, owner_id, demo_mode) VALUES (:id, 'synthetic:migration', true)",
            {"id": identifier},
        ))
        asyncio.run(query(
            "INSERT INTO answers (session_id, question_key, sequence_no, value_jsonb) "
            "VALUES (:id, 'primary_complaint', 1, CAST(:value AS jsonb))",
            {"id": identifier, "value": json.dumps(original)},
        ))
        command.upgrade(config, "20261118_02")
        sealed = asyncio.run(query("SELECT value_jsonb FROM answers WHERE session_id=:id", {"id": identifier}))[0]["value_jsonb"]
        assert set(sealed) == {"v", "n", "c"}
        assert cipher.decrypt(sealed, answer_context(identifier, "primary_complaint")) == original
        with pytest.raises(RuntimeError, match="Cannot remove encryption"):
            command.downgrade(config, "20261118_01")
        command.upgrade(config, "head")
        rows = asyncio.run(query(
            "SELECT id, role, kind, content_jsonb FROM messages WHERE session_id=:id ORDER BY sequence_no",
            {"id": identifier},
        ))
        assert [(row["role"], row["kind"]) for row in rows] == [
            ("assistant", "question"), ("user", "answer"), ("assistant", "question"),
        ]
        assert cipher.decrypt(rows[1]["content_jsonb"], message_context(identifier, rows[1]["id"]))["value"] == original
        with pytest.raises(RuntimeError, match="Cannot remove history"):
            command.downgrade(config, "20261118_02")
    finally:
        asyncio.run(query("DELETE FROM sessions WHERE id=:id", {"id": identifier}))
        command.upgrade(config, "head")

