"""Complete the PostgreSQL schema and move current results into their own table."""

import json
import os
from pathlib import Path
from uuid import uuid4

import sqlalchemy as sa
from alembic import context, op
from app.core.encryption import (
    JsonCipher,
    encrypted_json_check,
    rule_context,
    state_context,
)
from app.db.results import encode_result
from sqlalchemy.dialects import postgresql

revision = "20261118_04"
down_revision = "20261118_03"
branch_labels = None
depends_on = None


def encrypted(column, name):
    return sa.CheckConstraint(encrypted_json_check(column), name=name)


def upgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError(
            "Final schema migration requires an online connection and encryption key"
        )
    cipher = JsonCipher.from_file(os.getenv("DATA_ENCRYPTION_KEY_FILE", ""))
    op.create_table(
        "triage_results",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("urgency", sa.String(32), nullable=False),
        *(
            sa.Column(name, postgresql.JSONB(none_as_null=True), nullable=False)
            for name in (
                "specialty",
                "place",
                "rationale",
                "rule_codes",
                "details_jsonb",
            )
        ),
        sa.Column("version", sa.String(128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", name="uq_triage_results_session"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            ondelete="CASCADE",
            name="fk_triage_results_session",
        ),
        sa.CheckConstraint(
            "urgency IN ('EMERGENCY', 'WITHIN_24H', 'PLANNED', 'SELF_CARE', 'UNKNOWN')",
            name="ck_triage_results_urgency",
        ),
        sa.CheckConstraint(
            "length(version) BETWEEN 1 AND 128", name="ck_triage_results_version"
        ),
        *(
            encrypted(column, f"ck_triage_results_{column}_encrypted")
            for column in (
                "specialty",
                "place",
                "rationale",
                "rule_codes",
                "details_jsonb",
            )
        ),
    )
    op.create_table(
        "safety_rule_versions",
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("version", sa.String(128), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column(
            "enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("predicates", postgresql.JSONB(none_as_null=True), nullable=False),
        sa.PrimaryKeyConstraint("code"),
        sa.CheckConstraint("code ~ '^[A-Z0-9_]{1,64}$'", name="ck_safety_rules_code"),
        sa.CheckConstraint(
            "version ~ '^[a-zA-Z0-9._-]{1,128}$'", name="ck_safety_rules_version"
        ),
        sa.CheckConstraint(
            "severity IN ('P0', 'P1', 'P2', 'P3', 'UNKNOWN')",
            name="ck_safety_rules_severity",
        ),
        encrypted("predicates", "ck_safety_rules_predicates_encrypted"),
    )
    op.create_table(
        "audit_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("meta", postgresql.JSONB(none_as_null=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            ondelete="SET NULL",
            name="fk_audit_events_session",
        ),
        sa.CheckConstraint(
            "kind IN ('session_created', 'answer_saved', 'session_rewound', 'triage_saved', 'session_deleted', 'session_expired')",
            name="ck_audit_events_kind",
        ),
        encrypted("meta", "ck_audit_events_meta_encrypted"),
    )
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])
    op.create_index(
        "ix_audit_events_session_created", "audit_events", ["session_id", "created_at"]
    )
    op.create_table(
        "integration_nonces",
        sa.Column("nonce_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("nonce_hash"),
        sa.CheckConstraint(
            "nonce_hash ~ '^[0-9a-f]{64}$'", name="ck_integration_nonces_hash"
        ),
        sa.CheckConstraint(
            "used_at IS NULL OR used_at < expires_at",
            name="ck_integration_nonces_used_at",
        ),
    )
    op.create_index(
        "ix_integration_nonces_expires_at", "integration_nonces", ["expires_at"]
    )
    connection = op.get_bind()
    rules = sa.table(
        "safety_rule_versions",
        sa.column("code", sa.String()),
        sa.column("version", sa.String()),
        sa.column("severity", sa.String()),
        sa.column("enabled", sa.Boolean()),
        sa.column("predicates", postgresql.JSONB()),
    )
    for rule in json.loads(
        (
            Path(__file__).parents[1] / "seeds" / "20261118_04_safety_rules.json"
        ).read_text(encoding="utf-8")
    ):
        connection.execute(
            rules.insert().values(
                **{key: value for key, value in rule.items() if key != "predicates"},
                predicates=cipher.encrypt(
                    rule["predicates"], rule_context(rule["code"], rule["version"])
                ),
            )
        )
    sessions = sa.table(
        "sessions",
        sa.column("id", postgresql.UUID()),
        sa.column("state_jsonb", postgresql.JSONB()),
    )
    results = sa.table(
        "triage_results",
        sa.column("id", postgresql.UUID()),
        sa.column("session_id", postgresql.UUID()),
        sa.column("urgency", sa.String()),
        sa.column("version", sa.String()),
        *(
            sa.column(name, postgresql.JSONB())
            for name in (
                "specialty",
                "place",
                "rationale",
                "rule_codes",
                "details_jsonb",
            )
        ),
    )
    for row in connection.execute(sa.select(sessions)).mappings():
        if row["state_jsonb"] is None:
            continue
        state = cipher.decrypt(row["state_jsonb"], state_context(row["id"]))
        result = state.pop("result", None)
        if result is not None:
            connection.execute(
                results.insert().values(
                    id=uuid4(),
                    **encode_result(
                        row["id"],
                        result,
                        cipher,
                        "legacy-unversioned",
                        {
                            code: "legacy-unversioned"
                            for code in result.get("rule_codes", [])
                        },
                    ),
                )
            )
        connection.execute(
            sessions.update()
            .where(sessions.c.id == row["id"])
            .values(
                state_jsonb=cipher.encrypt(state, state_context(row["id"])),
            )
        )


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Schema rollback requires an online connection")
    connection = op.get_bind()
    if connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM triage_results) OR EXISTS (SELECT 1 FROM audit_events) "
            "OR EXISTS (SELECT 1 FROM integration_nonces)",
        )
    ):
        raise RuntimeError(
            "Cannot remove final schema while results, audit or nonces exist; back up data first"
        )
    op.drop_table("integration_nonces")
    op.drop_table("audit_events")
    op.drop_table("safety_rule_versions")
    op.drop_table("triage_results")
