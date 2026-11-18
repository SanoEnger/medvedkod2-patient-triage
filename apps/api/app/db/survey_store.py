from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.encryption import (
    DataEncryptionError,
    JsonCipher,
    answer_context,
    state_context,
)
from app.db.audit import record_audit
from app.db.models import AnswerRecord, SessionRecord
from app.db.repository import append_message, create_session, delete_session
from app.db.results import delete_triage_result, get_triage_result, save_triage_result
from app.db.safety_catalog import result_version
from app.schemas.survey import QUESTIONS, SurveyStatus
from app.services.sessions import Survey
from app.integrations.groq.schemas import ExtractionResult


class PostgresSurveyStore:
    def __init__(
        self, factory: async_sessionmaker, cipher: JsonCipher, demo_mode: bool
    ):
        self._factory = factory
        self._cipher = cipher
        self._demo_mode = demo_mode

    @asynccontextmanager
    async def _transaction(self):
        try:
            async with self._factory.begin() as db:
                yield db
        except (SQLAlchemyError, OSError, DataEncryptionError):
            raise HTTPException(status_code=503, detail="storage_unavailable") from None

    def _state(self, survey: Survey):
        return {
            "idempotency": survey.idempotency,
            "rule_codes": survey.rule_codes,
            "nlp": {key: value.model_dump(mode="json") for key, value in survey.nlp.items()},
            "revision": survey.revision,
        }

    async def create(self, owner_id: str, ttl_seconds: int) -> Survey:
        async with self._transaction() as db:
            record = await create_session(
                db,
                owner_id,
                demo_mode=self._demo_mode,
                ttl_seconds=ttl_seconds,
                cipher=self._cipher,
            )
            survey = Survey(
                id=record.id,
                owner_id=record.owner_id,
                created_at=record.created_at,
                expires_at=record.expires_at,
            )
            record.state_jsonb = self._cipher.encrypt(
                self._state(survey), state_context(record.id)
            )
            await append_message(
                db,
                record.id,
                owner_id,
                "assistant",
                "question",
                {"question_key": QUESTIONS[0]},
                cipher=self._cipher,
            )
            return survey

    @asynccontextmanager
    async def open(self, session_id: UUID, owner_id: str):
        async with self._transaction() as db:
            record = await db.scalar(
                select(SessionRecord)
                .where(SessionRecord.id == session_id)
                .with_for_update(),
            )
            if record is None or record.expires_at <= datetime.now(UTC):
                raise HTTPException(status_code=404, detail="session_not_found")
            if record.owner_id != owner_id:
                raise HTTPException(status_code=403, detail="session_forbidden")
            rows = list(
                await db.scalars(
                    select(AnswerRecord)
                    .where(AnswerRecord.session_id == session_id)
                    .order_by(AnswerRecord.sequence_no),
                )
            )
            answers = {
                row.question_key: self._cipher.decrypt(
                    row.value_jsonb,
                    answer_context(session_id, row.question_key),
                )
                for row in rows
            }
            state = (
                self._cipher.decrypt(record.state_jsonb, state_context(session_id))
                if record.state_jsonb
                else {}
            )
            survey = Survey(
                id=record.id,
                owner_id=record.owner_id,
                created_at=record.created_at,
                expires_at=record.expires_at,
                status=record.status,
                answers=answers,
                idempotency={
                    key: (value[0], value[1])
                    for key, value in state.get("idempotency", {}).items()
                },
                rule_codes=state.get("rule_codes", []),
                nlp={key: ExtractionResult.model_validate(value) for key, value in state.get("nlp", {}).items()},
                revision=state.get("revision", 0),
                result=await get_triage_result(
                    db, session_id, owner_id, cipher=self._cipher
                ),
            )
            previous_answers = deepcopy(answers)
            previous_state = deepcopy(self._state(survey))
            previous_result = deepcopy(survey.result)
            previous_status = survey.status
            yield survey
            record.status = survey.status
            record.step = len(survey.answers)
            existing = {row.question_key: row for row in rows}
            for row in rows:
                if row.question_key not in survey.answers:
                    await db.delete(row)
            for sequence, (key, value) in enumerate(survey.answers.items(), start=1):
                row = existing.get(key)
                if row is None:
                    db.add(
                        AnswerRecord(
                            session_id=session_id,
                            question_key=key,
                            sequence_no=sequence,
                            value_jsonb=self._cipher.encrypt(
                                value, answer_context(session_id, key)
                            ),
                        )
                    )
                elif previous_answers[key] != value:
                    row.value_jsonb = self._cipher.encrypt(
                        value, answer_context(session_id, key)
                    )

            async def message(role, kind, content):
                await append_message(
                    db, session_id, owner_id, role, kind, content, cipher=self._cipher
                )

            if len(survey.answers) < len(previous_answers):
                await delete_triage_result(db, session_id, owner_id)
                await record_audit(
                    db,
                    session_id,
                    "session_rewound",
                    {"step": record.step, "status": str(survey.status)},
                    cipher=self._cipher,
                )
                await message("system", "back", {"target_step": len(survey.answers)})
            for key, value in survey.answers.items():
                if key not in previous_answers or previous_answers[key] != value:
                    await message(
                        "user", "answer", {"question_key": key, "value": value}
                    )
                    await record_audit(
                        db,
                        session_id,
                        "answer_saved",
                        {"step": record.step, "status": str(survey.status)},
                        cipher=self._cipher,
                    )
            if survey.result is not None and survey.result != previous_result:
                await save_triage_result(
                    db, session_id, owner_id, survey.result, cipher=self._cipher
                )
                await message(
                    "assistant",
                    "result",
                    {"result": survey.result, "answers": survey.answers},
                )
            if survey.result is not None and (
                survey.result != previous_result or survey.status != previous_status
            ):
                version, _ = result_version(survey.result["rule_codes"])
                await record_audit(
                    db,
                    session_id,
                    "triage_saved",
                    {
                        "step": record.step,
                        "status": str(survey.status),
                        "version": version,
                    },
                    cipher=self._cipher,
                )
            if (
                previous_answers != survey.answers
                and survey.status == SurveyStatus.COLLECTING
            ):
                await message(
                    "assistant",
                    "question",
                    {"question_key": QUESTIONS[len(survey.answers)]},
                )
            if previous_state != self._state(survey):
                record.state_jsonb = self._cipher.encrypt(
                    self._state(survey), state_context(session_id)
                )

    async def delete(self, session_id: UUID, owner_id: str) -> None:
        async with self._transaction() as db:
            record = await db.scalar(
                select(SessionRecord)
                .where(SessionRecord.id == session_id)
                .with_for_update(),
            )
            if record is None or record.expires_at <= datetime.now(UTC):
                raise HTTPException(status_code=404, detail="session_not_found")
            if record.owner_id != owner_id:
                raise HTTPException(status_code=403, detail="session_forbidden")
            await delete_session(db, session_id, owner_id, cipher=self._cipher)
