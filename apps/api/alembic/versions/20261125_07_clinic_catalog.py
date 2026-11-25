"""Add the clinic directory."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "20261125_07"
down_revision = "20261124_06"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "clinic_organizations",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(7), nullable=False),
        sa.CheckConstraint("kind IN ('public', 'private')", name="ck_clinic_organization_kind"),
    )
    op.create_table(
        "clinic_branches",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("organization_id", sa.String(80), sa.ForeignKey("clinic_organizations.id"), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("phones", JSONB(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("website", sa.Text()),
        sa.Column("booking_url", sa.Text()),
        sa.Column("gosuslugi_confirmed", sa.Boolean(), nullable=False),
        sa.Column("gosuslugi_direct_url", sa.Text()),
        sa.Column("demo", sa.Boolean(), nullable=False),
        sa.CheckConstraint("lat BETWEEN -90 AND 90 AND lon BETWEEN -180 AND 180", name="ck_clinic_branch_coordinates"),
    )
    op.create_table(
        "clinic_payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("branch_id", sa.String(80), sa.ForeignKey("clinic_branches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("specialty_code", sa.String(80), nullable=False),
        sa.Column("method", sa.String(4), nullable=False),
        sa.Column("insurer", JSONB()),
        sa.Column("program", sa.Text()),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("checked_on", sa.Date(), nullable=False),
        sa.Column("confirmed", sa.Boolean(), nullable=False),
        sa.CheckConstraint("method IN ('oms', 'dms', 'paid')", name="ck_clinic_payment_method"),
    )
    op.create_index("ix_clinic_payments_branch_id", "clinic_payments", ["branch_id"])


def downgrade():
    op.drop_table("clinic_payments")
    op.drop_table("clinic_branches")
    op.drop_table("clinic_organizations")
