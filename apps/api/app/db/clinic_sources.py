import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from app.db.models import Base

CATALOG_IMPORT_LOCK = 1093497173
POLIKLINIKA45 = "poliklinika45"

clinic_sources = sa.Table(
    "clinic_sources", Base.metadata,
    sa.Column("source", sa.String(32), primary_key=True),
    sa.Column("external_id", sa.String(160), primary_key=True),
    sa.Column("kind", sa.String(12), primary_key=True),
    sa.Column("url", sa.Text, nullable=False),
    sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("verification_status", sa.String(16), nullable=False),
    sa.Column("organization_id", sa.String(80), sa.ForeignKey("clinic_organizations.id", ondelete="SET NULL")),
    sa.Column("branch_id", sa.String(80), sa.ForeignKey("clinic_branches.id", ondelete="SET NULL"), index=True),
    sa.Column("fields", JSONB, nullable=False),
    sa.Column("specialty_codes", JSONB, nullable=False),
    sa.Column("schedule_as_of", sa.Date),
    sa.CheckConstraint("kind IN ('organization', 'branch')", name="ck_clinic_source_kind"),
    sa.CheckConstraint("verification_status IN ('verified', 'needs_review')", name="ck_clinic_source_status"),
)
