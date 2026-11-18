from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.encryption import encrypted_json_check
from app.schemas.survey import SurveyStatus


class Base(DeclarativeBase):
    pass


class SessionRecord(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint("step >= 0", name="ck_sessions_step"),
        CheckConstraint(
            "status IN ('COLLECTING', 'REVIEWING', 'COMPLETED', 'EMERGENCY_STOP', 'EXPIRED')",
            name="ck_sessions_status",
        ),
        CheckConstraint(
            "expires_at > created_at AND expires_at <= created_at + INTERVAL '24 hours'",
            name="ck_sessions_ttl",
        ),
        Index("ix_sessions_expires_at", "expires_at"),
        Index("ix_sessions_owner_created", "owner_id", "created_at", "id"),
        CheckConstraint(
            "state_jsonb IS NULL OR (" + encrypted_json_check("state_jsonb") + ")",
            name="ck_sessions_state_encrypted",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    owner_id: Mapped[str] = mapped_column(Text, nullable=False)
    state_jsonb: Mapped[dict[str, Any] | None] = mapped_column(JSONB(), nullable=True)
    status: Mapped[SurveyStatus] = mapped_column(
        Enum(
            SurveyStatus,
            native_enum=False,
            create_constraint=False,
            name="ck_sessions_status",
            length=32,
        ),
        nullable=False,
        default=SurveyStatus.COLLECTING,
        server_default="COLLECTING",
    )
    step: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP + INTERVAL '24 hours'"),
    )
    demo_mode: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )


class AnswerRecord(Base):
    __tablename__ = "answers"
    __table_args__ = (
        CheckConstraint("sequence_no > 0", name="ck_answers_sequence_no"),
        CheckConstraint(
            encrypted_json_check("value_jsonb"), name="ck_answers_encrypted"
        ),
        UniqueConstraint(
            "session_id", "question_key", name="uq_answers_session_question"
        ),
        Index("ix_answers_session_sequence", "session_id", "sequence_no", unique=True),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE", name="fk_answers_session"),
        nullable=False,
    )
    question_key: Mapped[str] = mapped_column(String(50), nullable=False)
    value_jsonb: Mapped[dict[str, Any]] = mapped_column(
        JSONB(none_as_null=True), nullable=False
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class MessageRecord(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("sequence_no > 0", name="ck_messages_sequence_no"),
        CheckConstraint(
            "role IN ('assistant', 'user', 'system')", name="ck_messages_role"
        ),
        CheckConstraint(
            "kind IN ('question', 'answer', 'result', 'back', 'text')",
            name="ck_messages_kind",
        ),
        CheckConstraint(
            encrypted_json_check("content_jsonb"), name="ck_messages_encrypted"
        ),
        Index("ix_messages_session_sequence", "session_id", "sequence_no", unique=True),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE", name="fk_messages_session"),
        nullable=False,
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    content_jsonb: Mapped[dict[str, Any]] = mapped_column(
        JSONB(none_as_null=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class TriageResultRecord(Base):
    __tablename__ = "triage_results"
    __table_args__ = (
        UniqueConstraint("session_id", name="uq_triage_results_session"),
        CheckConstraint(
            "urgency IN ('EMERGENCY', 'WITHIN_24H', 'PLANNED', 'SELF_CARE', 'UNKNOWN')",
            name="ck_triage_results_urgency",
        ),
        CheckConstraint(
            "length(version) BETWEEN 1 AND 128", name="ck_triage_results_version"
        ),
        *(
            CheckConstraint(
                encrypted_json_check(column),
                name=f"ck_triage_results_{column}_encrypted",
            )
            for column in (
                "specialty",
                "place",
                "rationale",
                "rule_codes",
                "details_jsonb",
            )
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE", name="fk_triage_results_session"),
        nullable=False,
    )
    urgency: Mapped[str] = mapped_column(String(32), nullable=False)
    specialty: Mapped[dict[str, Any]] = mapped_column(
        JSONB(none_as_null=True), nullable=False
    )
    place: Mapped[dict[str, Any]] = mapped_column(
        JSONB(none_as_null=True), nullable=False
    )
    rationale: Mapped[dict[str, Any]] = mapped_column(
        JSONB(none_as_null=True), nullable=False
    )
    rule_codes: Mapped[dict[str, Any]] = mapped_column(
        JSONB(none_as_null=True), nullable=False
    )
    details_jsonb: Mapped[dict[str, Any]] = mapped_column(
        JSONB(none_as_null=True), nullable=False
    )
    version: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class SafetyRuleVersionRecord(Base):
    __tablename__ = "safety_rule_versions"
    __table_args__ = (
        CheckConstraint("code ~ '^[A-Z0-9_]{1,64}$'", name="ck_safety_rules_code"),
        CheckConstraint(
            "version ~ '^[a-zA-Z0-9._-]{1,128}$'", name="ck_safety_rules_version"
        ),
        CheckConstraint(
            "severity IN ('P0', 'P1', 'P2', 'P3', 'UNKNOWN')",
            name="ck_safety_rules_severity",
        ),
        CheckConstraint(
            encrypted_json_check("predicates"),
            name="ck_safety_rules_predicates_encrypted",
        ),
    )

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[str] = mapped_column(String(128), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    predicates: Mapped[dict[str, Any]] = mapped_column(
        JSONB(none_as_null=True), nullable=False
    )


class AuditEventRecord(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('session_created', 'answer_saved', 'session_rewound', 'triage_saved', 'session_deleted', 'session_expired')",
            name="ck_audit_events_kind",
        ),
        CheckConstraint(
            encrypted_json_check("meta"), name="ck_audit_events_meta_encrypted"
        ),
        Index("ix_audit_events_created_at", "created_at"),
        Index("ix_audit_events_session_created", "session_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    session_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="SET NULL", name="fk_audit_events_session"),
        nullable=True,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB(none_as_null=True), nullable=False
    )


class IntegrationNonceRecord(Base):
    __tablename__ = "integration_nonces"
    __table_args__ = (
        CheckConstraint(
            "nonce_hash ~ '^[0-9a-f]{64}$'", name="ck_integration_nonces_hash"
        ),
        CheckConstraint(
            "used_at IS NULL OR used_at < expires_at",
            name="ck_integration_nonces_used_at",
        ),
        Index("ix_integration_nonces_expires_at", "expires_at"),
    )

    nonce_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
