"""Store independently sourced clinic catalog data."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "20261125_09"
down_revision = "20261125_08"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "clinic_sources",
        sa.Column("source", sa.String(32), primary_key=True),
        sa.Column("external_id", sa.String(160), primary_key=True),
        sa.Column("kind", sa.String(12), primary_key=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verification_status", sa.String(16), nullable=False),
        sa.Column("organization_id", sa.String(80), sa.ForeignKey("clinic_organizations.id", ondelete="SET NULL")),
        sa.Column("branch_id", sa.String(80), sa.ForeignKey("clinic_branches.id", ondelete="SET NULL")),
        sa.Column("fields", JSONB(), nullable=False),
        sa.Column("specialty_codes", JSONB(), nullable=False),
        sa.Column("schedule_as_of", sa.Date()),
        sa.CheckConstraint("kind IN ('organization', 'branch')", name="ck_clinic_source_kind"),
        sa.CheckConstraint("verification_status IN ('verified', 'needs_review')", name="ck_clinic_source_status"),
    )
    op.create_index("ix_clinic_sources_branch_id", "clinic_sources", ["branch_id"])


def downgrade():
    op.drop_table("clinic_sources")
