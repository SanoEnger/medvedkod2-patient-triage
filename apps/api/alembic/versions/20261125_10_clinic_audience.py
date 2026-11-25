"""Store verified clinic branch age groups."""

import sqlalchemy as sa

from alembic import op

revision = "20261125_10"
down_revision = "20261125_09"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("clinic_branches", sa.Column("audience", sa.String(5), nullable=True))
    op.create_check_constraint("ck_clinic_branch_audience", "clinic_branches", "audience IN ('child', 'adult', 'all')")


def downgrade():
    op.drop_constraint("ck_clinic_branch_audience", "clinic_branches", type_="check")
    op.drop_column("clinic_branches", "audience")
