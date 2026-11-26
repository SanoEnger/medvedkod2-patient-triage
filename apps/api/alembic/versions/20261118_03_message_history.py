"""Encrypted conversation history attached to survey sessions."""

import os
from uuid import uuid4

import sqlalchemy as sa
from alembic import context, op
from app.core.encryption import (
    JsonCipher,
    answer_context,
    message_context,
    state_context,
)
from sqlalchemy.dialects import postgresql

revision = "20261118_03"
down_revision = "20261118_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("History migration requires an online connection")
    op.create_index("ix_sessions_owner_created", "sessions", ["owner_id", "created_at", "id"])
    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("content_jsonb", postgresql.JSONB(none_as_null=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE", name="fk_messages_session"),
        sa.CheckConstraint("sequence_no > 0", name="ck_messages_sequence_no"),
        sa.CheckConstraint("role IN ('assistant', 'user', 'system')", name="ck_messages_role"),
        sa.CheckConstraint("kind IN ('question', 'answer', 'result', 'back', 'text')", name="ck_messages_kind"),
        sa.CheckConstraint(
            "content_jsonb ?& ARRAY['v','n','c'] AND (content_jsonb->'v') = '1'::jsonb AND "
            "jsonb_typeof(content_jsonb->'n') = 'string' AND jsonb_typeof(content_jsonb->'c') = 'string' AND "
            "(content_jsonb - 'v' - 'n' - 'c') = '{}'::jsonb",
            name="ck_messages_encrypted",
        ),
    )
    op.create_index("ix_messages_session_sequence", "messages", ["session_id", "sequence_no"], unique=True)
    connection = op.get_bind()
    cipher = JsonCipher.from_file(os.getenv("DATA_ENCRYPTION_KEY_FILE", ""))
    sessions = sa.table(
        "sessions", sa.column("id", postgresql.UUID()), sa.column("state_jsonb", postgresql.JSONB()),
        sa.column("status", sa.String()), sa.column("created_at", sa.DateTime(timezone=True)),
    )
    answers = sa.table(
        "answers", sa.column("session_id", postgresql.UUID()), sa.column("question_key", sa.String()),
        sa.column("sequence_no", sa.Integer()), sa.column("value_jsonb", postgresql.JSONB()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    messages = sa.table(
        "messages", sa.column("id", postgresql.UUID()), sa.column("session_id", postgresql.UUID()),
        sa.column("sequence_no", sa.Integer()), sa.column("role", sa.String()), sa.column("kind", sa.String()),
        sa.column("content_jsonb", postgresql.JSONB()), sa.column("created_at", sa.DateTime(timezone=True)),
    )
    questions = ("primary_complaint", "patient_context", "symptom_details", "red_flags", "medical_history")
    for session in connection.execute(sa.select(sessions)).mappings():
        sequence = 0

        def add(role, kind, content, created_at, session_id=session["id"]):
            nonlocal sequence
            sequence += 1
            identifier = uuid4()
            connection.execute(messages.insert().values(
                id=identifier, session_id=session_id, sequence_no=sequence, role=role, kind=kind,
                content_jsonb=cipher.encrypt(content, message_context(session_id, identifier)),
                created_at=created_at,
            ))

        snapshot = {}
        last_time = session["created_at"]
        for answer in connection.execute(
            sa.select(answers).where(answers.c.session_id == session["id"]).order_by(answers.c.sequence_no),
        ).mappings():
            last_time = answer["created_at"]
            value = cipher.decrypt(answer["value_jsonb"], answer_context(session["id"], answer["question_key"]))
            snapshot[answer["question_key"]] = value
            add("assistant", "question", {"question_key": answer["question_key"]}, last_time)
            add("user", "answer", {"question_key": answer["question_key"], "value": value}, last_time)
        state = cipher.decrypt(session["state_jsonb"], state_context(session["id"])) if session["state_jsonb"] else {}
        if state.get("result") is not None:
            add("assistant", "result", {"result": state["result"], "answers": snapshot}, last_time)
        elif session["status"] == "COLLECTING" and len(snapshot) < len(questions):
            add("assistant", "question", {"question_key": questions[len(snapshot)]}, last_time)


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("History rollback requires an online connection")
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM messages)")):
        raise RuntimeError("Cannot remove history while messages exist; back up and delete sessions first")
    op.drop_table("messages")
    op.drop_index("ix_sessions_owner_created", table_name="sessions")
