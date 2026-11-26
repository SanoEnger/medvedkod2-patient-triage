"""Create session and answer storage."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261118_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("owner_id", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), server_default="COLLECTING", nullable=False),
        sa.Column("step", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True),
                  server_default=sa.text("CURRENT_TIMESTAMP + INTERVAL '24 hours'"),
                  nullable=False),
        sa.Column("demo_mode", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_sessions"),
        sa.CheckConstraint("step >= 0", name="ck_sessions_step"),
        sa.CheckConstraint(
            "status IN ('COLLECTING', 'REVIEWING', 'COMPLETED', 'EMERGENCY_STOP', 'EXPIRED')",
            name="ck_sessions_status",
        ),
        sa.CheckConstraint(
            "expires_at > created_at AND expires_at <= created_at + INTERVAL '24 hours'",
            name="ck_sessions_ttl",
        ),
    )
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])
    op.create_table(
        "answers",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question_key", sa.String(50), nullable=False),
        sa.Column("value_jsonb", postgresql.JSONB(none_as_null=True), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_answers"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.id"], ondelete="CASCADE", name="fk_answers_session",
        ),
        sa.UniqueConstraint("session_id", "question_key", name="uq_answers_session_question"),
        sa.CheckConstraint("sequence_no > 0", name="ck_answers_sequence_no"),
    )
    op.create_index(
        "ix_answers_session_sequence", "answers", ["session_id", "sequence_no"], unique=True,
    )


def downgrade() -> None:
    op.drop_table("answers")
    op.drop_table("sessions")
