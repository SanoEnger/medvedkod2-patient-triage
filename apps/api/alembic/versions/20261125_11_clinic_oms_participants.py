"""Record verified participation in the regional ambulatory OMS program."""

import sqlalchemy as sa

from alembic import op

revision = "20261125_11"
down_revision = "20261125_10"
branch_labels = None
depends_on = None


def upgrade():
    participants = op.create_table(
        "clinic_oms_participants",
        sa.Column("poliklinika45_id", sa.String(160), primary_key=True),
        sa.Column("evidence_url", sa.Text(), nullable=False),
    )
    evidence = "https://base.garant.ru/414160161/c9c989f1e999992b41b30686f0032f7d/"
    portal_ids = (
        "37",  # Курганская детская поликлиника
        "35",  # Курганская областная больница № 2
        "31",  # Кожно-венерологический диспансер
        "30",  # Областная инфекционная больница
        "1155017", "1143538",  # Курганские поликлиники № 1 и № 2
        "41",  # Городская стоматологическая поликлиника
        "1135792",  # Онкологический диспансер
        "27",  # Кардиологический диспансер
        "26",  # Детская больница имени Красного Креста
        "56",  # Перинатальный центр
        "1071207",  # Центр имени Илизарова
    )
    op.bulk_insert(participants, [
        {"poliklinika45_id": portal_id, "evidence_url": evidence} for portal_id in portal_ids
    ])


def downgrade():
    op.drop_table("clinic_oms_participants")
