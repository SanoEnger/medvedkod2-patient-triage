"""Register the reviewed cross-step safety implementation without changing sessions."""

import json
import os
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.encryption import JsonCipher, rule_context

revision = "20261124_06"
down_revision = "20261120_05"
branch_labels = None
depends_on = None


def replace_catalog(seed):
    cipher = JsonCipher.from_file(os.getenv("DATA_ENCRYPTION_KEY_FILE", ""))
    table = sa.table(
        "safety_rule_versions",
        sa.column("code", sa.String()),
        sa.column("version", sa.String()),
        sa.column("severity", sa.String()),
        sa.column("enabled", sa.Boolean()),
        sa.column("predicates", postgresql.JSONB()),
    )
    connection = op.get_bind()
    rules = json.loads((Path(__file__).parents[1] / "seeds" / seed).read_text(encoding="utf-8"))
    for rule in rules:
        values = {key: value for key, value in rule.items() if key != "predicates"}
        values["predicates"] = cipher.encrypt(rule["predicates"], rule_context(rule["code"], rule["version"]))
        statement = postgresql.insert(table).values(**values)
        connection.execute(statement.on_conflict_do_update(index_elements=["code"], set_=values))


def upgrade():
    replace_catalog("20261124_06_safety_rules.json")


def downgrade():
    replace_catalog("20261118_04_safety_rules.json")
