"""Add the local OpenStreetMap address directory."""

import sqlalchemy as sa

from alembic import op

revision = "20261125_08"
down_revision = "20261125_07"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "clinic_addresses",
        sa.Column("osm_id", sa.String(32), primary_key=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("street_key", sa.Text(), nullable=False),
        sa.Column("street_type", sa.Text(), nullable=False),
        sa.Column("house_key", sa.Text(), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
    )
    op.create_index("ix_clinic_addresses_house_key", "clinic_addresses", ["house_key"])


def downgrade():
    op.drop_table("clinic_addresses")
