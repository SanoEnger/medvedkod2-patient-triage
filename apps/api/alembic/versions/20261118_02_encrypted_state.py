"""Encrypt answer JSON and persist encrypted session state."""

import os

import sqlalchemy as sa
from alembic import context, op
from app.core.encryption import JsonCipher, answer_context, state_context
from sqlalchemy.dialects import postgresql

revision = "20261118_02"
down_revision = "20261118_01"
branch_labels = None
depends_on = None


def envelope_check(column):
    return (
        f"{column} ?& ARRAY['v','n','c'] AND "
        f"({column}->'v') = '1'::jsonb AND "
        f"jsonb_typeof({column}->'n') = 'string' AND "
        f"jsonb_typeof({column}->'c') = 'string' AND "
        f"({column} - 'v' - 'n' - 'c') = '{{}}'::jsonb"
    )


def upgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Encryption migration requires an online connection and key file")
    cipher = JsonCipher.from_file(os.getenv("DATA_ENCRYPTION_KEY_FILE", ""))
    connection = op.get_bind()
    op.add_column("sessions", sa.Column("state_jsonb", postgresql.JSONB(), nullable=True))
    answers = sa.table(
        "answers", sa.column("id", postgresql.UUID()),
        sa.column("session_id", postgresql.UUID()), sa.column("question_key", sa.String()),
        sa.column("value_jsonb", postgresql.JSONB()),
    )
    sessions = sa.table(
        "sessions", sa.column("id", postgresql.UUID()),
        sa.column("state_jsonb", postgresql.JSONB()),
    )
    for answer in connection.execute(sa.select(answers)).mappings():
        sealed = cipher.encrypt(
            answer["value_jsonb"], answer_context(answer["session_id"], answer["question_key"]),
        )
        connection.execute(answers.update().where(answers.c.id == answer["id"]).values(value_jsonb=sealed))
    for session_id in connection.execute(sa.select(sessions.c.id)).scalars():
        sealed = cipher.encrypt(
            {"idempotency": {}, "rule_codes": [], "result": None}, state_context(session_id),
        )
        connection.execute(sessions.update().where(sessions.c.id == session_id).values(state_jsonb=sealed))
    op.create_check_constraint("ck_answers_encrypted", "answers", envelope_check("value_jsonb"))
    op.create_check_constraint(
        "ck_sessions_state_encrypted", "sessions",
        "state_jsonb IS NULL OR (" + envelope_check("state_jsonb") + ")",
    )


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Encryption rollback requires an online connection")
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM sessions)")):
        raise RuntimeError("Cannot remove encryption while sessions exist; back up and delete sessions first")
    op.drop_constraint("ck_sessions_state_encrypted", "sessions", type_="check")
    op.drop_constraint("ck_answers_encrypted", "answers", type_="check")
    op.drop_column("sessions", "state_jsonb")
