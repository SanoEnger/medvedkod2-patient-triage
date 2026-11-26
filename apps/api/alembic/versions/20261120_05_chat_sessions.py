"""Distinguish standalone chats from questionnaires without changing history."""
import sqlalchemy as sa

from alembic import op

revision = "20261120_05"
down_revision = "20261118_04"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sessions", sa.Column("kind", sa.String(20), nullable=False, server_default="questionnaire"))
    op.create_check_constraint("ck_sessions_kind", "sessions", "kind IN ('questionnaire', 'chat')")


def downgrade():
    op.drop_constraint("ck_sessions_kind", "sessions", type_="check")
    op.drop_column("sessions", "kind")
