"""Questionnaire rules with transactional storage."""

import asyncio
import hashlib
import json
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from app.integrations.groq import SymptomExtractor
from app.integrations.groq.schemas import ExtractionResult
from app.integrations.groq.exceptions import GroqError
from app.core.observability import event
from app.schemas.survey import (
    QUESTION_MODELS,
    QUESTIONS,
    AnswerRequest,
    Progress,
    SessionResponse,
    SurveyStatus,
    TriageResponse,
)
from app.services.safety import find_emergency_rules

EMERGENCY_MESSAGE = "Вызовите скорую помощь (103/112). Не ждите окончания опроса."
DISCLAIMER = (
    "Демонстрационный прототип не ставит диагноз, не назначает лечение и не заменяет врача. "
    "При ухудшении состояния обратитесь за медицинской помощью, при опасных симптомах звоните 103/112."
)


@dataclass
class Survey:
    id: UUID
    owner_id: str
    created_at: datetime
    expires_at: datetime
    status: SurveyStatus = SurveyStatus.COLLECTING
    answers: dict[str, dict[str, Any]] = field(default_factory=dict)
    idempotency: dict[str, tuple[str, dict[str, Any]]] = field(default_factory=dict)
    rule_codes: list[str] = field(default_factory=list)
    result: dict[str, Any] | None = None
    nlp: dict[str, ExtractionResult] = field(default_factory=dict)
    revision: int = 0


class SurveyStore(Protocol):
    async def create(self, owner_id: str, ttl_seconds: int) -> Survey: ...
    def open(self, session_id: UUID, owner_id: str) -> AbstractAsyncContextManager[Survey]: ...
    async def delete(self, session_id: UUID, owner_id: str) -> None: ...


class MemorySurveyStore:
    """Explicit offline test store; the running API uses PostgreSQL."""
    def __init__(self):
        self._sessions: dict[UUID, Survey] = {}
        self._lock = asyncio.Lock()

    def _cleanup(self):
        now = datetime.now(UTC)
        for sid in [sid for sid, obj in self._sessions.items() if obj.expires_at <= now]:
            del self._sessions[sid]

    async def create(self, owner_id: str, ttl_seconds: int) -> Survey:
        async with self._lock:
            self._cleanup()
            now = datetime.now(UTC)
            survey = Survey(id=uuid4(), owner_id=owner_id, created_at=now,
                            expires_at=now + timedelta(seconds=ttl_seconds))
            self._sessions[survey.id] = survey
            return survey

    @asynccontextmanager
    async def open(self, session_id: UUID, owner_id: str):
        async with self._lock:
            self._cleanup()
            survey = self._sessions.get(session_id)
            if survey is None:
                raise HTTPException(status_code=404, detail="session_not_found")
            if survey.owner_id != owner_id:
                raise HTTPException(status_code=403, detail="session_forbidden")
            yield survey

    async def delete(self, session_id: UUID, owner_id: str) -> None:
        async with self.open(session_id, owner_id):
            del self._sessions[session_id]


class SessionService:
    """Questionnaire engine with transactional storage."""
    def __init__(self, ttl_seconds: int = 86400, store: SurveyStore | None = None, *, extractor: SymptomExtractor | None = None,
                 analyst=None, analysis_source: str = "groq") -> None:
        self._extractor = extractor
        self._analyst = analyst
        self._analysis_source = analysis_source
        self._ttl_seconds = ttl_seconds
        self._store = store or MemorySurveyStore()

    @staticmethod
    def _progress(survey: Survey) -> Progress:
        answered = len(survey.answers)
        return Progress(answered=answered, total=len(QUESTIONS), percent=int(100 * answered / len(QUESTIONS)))

    @staticmethod
    def _serialize(survey: Survey) -> SessionResponse:
        current = QUESTIONS[len(survey.answers)] if survey.status == SurveyStatus.COLLECTING else None
        is_emergency = survey.status == SurveyStatus.EMERGENCY_STOP
        return SessionResponse(
            id=survey.id, status=survey.status, state=survey.status,
            progress=SessionService._progress(survey), current_question=current, next_question=current,
            expires_at=survey.expires_at.isoformat(), emergency=is_emergency,
            urgency="EMERGENCY" if is_emergency else None,
            message=EMERGENCY_MESSAGE if is_emergency else None,
            matched_rule_codes=survey.rule_codes.copy(), result=survey.result, nlp=survey.nlp.copy(),
            answers=survey.answers.copy(),
        )

    @staticmethod
    def _validate(question_key: str, value: dict[str, Any]) -> dict[str, Any]:
        model = QUESTION_MODELS.get(question_key)
        if model is None:
            raise HTTPException(status_code=400, detail="unknown_question")
        try:
            validated = model.model_validate(value)
        except ValidationError:
            raise HTTPException(status_code=400, detail="invalid_answer") from None
        # Do not turn unknown fields into confidential, untracked persistence.
        return validated.model_dump(mode="json")

    @staticmethod
    def _triage(survey: Survey) -> TriageResponse:
        if survey.rule_codes:
            return TriageResponse(
                urgency="EMERGENCY", specialty=None, place="Скорая помощь: 103/112",
                rationale="Выявлен один или несколько признаков, требующих экстренного предупреждения.",
                disclaimer=DISCLAIMER, rule_codes=survey.rule_codes, needs_clarification=False,
            )
        # No P1/P3 rule is approved for the MVP. Uncertain cases stay UNKNOWN.
        if len(survey.answers) != len(QUESTIONS):
            return TriageResponse(
                urgency="UNKNOWN", specialty=None, place=None,
                rationale="Опрос ещё не завершён. Требуется уточнение сведений.",
                disclaimer=DISCLAIMER, rule_codes=[], needs_clarification=True,
            )
        flags = survey.answers["red_flags"]
        details = survey.answers["symptom_details"]
        complaint = survey.answers["primary_complaint"]
        # Strictly restricted synthetic low-severity example, NOT an approved medical protocol.
        safe_demo_template = (
            all(value is False for value in flags.values())
            and details.get("severity_0_10") is not None
            and details["severity_0_10"] <= 3
            and bool(details.get("duration"))
            and complaint["category"] == "skin"
            and not complaint.get("text")
            and not details.get("additional_text")
        )
        if safe_demo_template:
            return TriageResponse(
                urgency="PLANNED", specialty="Дерматолог", place="Поликлиника (плановая запись)",
                rationale="Ограниченный синтетический сценарий с явно отрицательными экстренными признаками. "
                          "Правило требует проверки медицинским ментором.",
                disclaimer=DISCLAIMER, rule_codes=["DEMO_SKIN_MILD_V0"], needs_clarification=False,
            )
        return TriageResponse(
            urgency="UNKNOWN", specialty=None, place="Очная консультация медицинского специалиста",
            rationale="Недостаточно проверенных правил для безопасного определения срочности. "
                      "Нужна дополнительная оценка специалистом.",
            disclaimer=DISCLAIMER, rule_codes=[], needs_clarification=True,
        )

    async def create(self, owner_id: str) -> SessionResponse:
        return self._serialize(await self._store.create(owner_id, self._ttl_seconds))

    async def get(self, session_id: UUID, owner_id: str) -> SessionResponse:
        async with self._store.open(session_id, owner_id) as survey:
            return self._serialize(survey)

    async def answer(self, session_id: UUID, owner_id: str, request: AnswerRequest) -> SessionResponse:
        """Run safety first; enrich outside the repository lock, without changing urgency.

        Optimistic revision check discards late results after back/edit/delete.
        Idempotent retries do not replay the provider request.
        """
        response, revision = await self._answer(session_id, owner_id, request)
        if revision is None or response.emergency or self._extractor is None:
            return response
        field = {"primary_complaint": "text", "symptom_details": "additional_text"}.get(request.question_key)
        text = request.value.get(field, "") if field else ""
        if not isinstance(text, str) or not text.strip():
            return response
        extraction = await self._extractor.extract(text)
        async with self._store.open(session_id, owner_id) as survey:
            if survey.revision == revision and survey.status != SurveyStatus.EMERGENCY_STOP:
                survey.nlp[request.question_key] = extraction
                survey.rule_codes = find_emergency_rules(survey.answers)
                if survey.rule_codes:
                    survey.status = SurveyStatus.EMERGENCY_STOP
                    survey.result = self._triage(survey).model_dump()
                # The accepted-answer snapshot is immutable for idempotency,
                # including retries from other workers during enrichment.
                # GET exposes the latest persisted NLP result.
        return response

    async def _answer(self, session_id: UUID, owner_id: str, request: AnswerRequest) -> tuple[SessionResponse, int | None]:
        async with self._store.open(session_id, owner_id) as survey:
            payload_hash = hashlib.sha256(json.dumps(
                {"question_key": request.question_key, "value": request.value},
                sort_keys=True, ensure_ascii=False, separators=(",", ":"),
            ).encode()).hexdigest()
            key = str(request.idempotency_key)
            if key in survey.idempotency:
                previous_hash, previous_response = survey.idempotency[key]
                if previous_hash != payload_hash:
                    raise HTTPException(status_code=409, detail="idempotency_conflict")
                return SessionResponse.model_validate(previous_response), None
            if survey.status != SurveyStatus.COLLECTING:
                raise HTTPException(status_code=409, detail="session_not_collecting")
            expected = QUESTIONS[len(survey.answers)]
            if request.question_key != expected:
                raise HTTPException(status_code=409, detail="unexpected_question")
            survey.answers[expected] = self._validate(expected, request.value)
            survey.revision += 1
            survey.rule_codes = find_emergency_rules(survey.answers)
            if survey.rule_codes:
                survey.status = SurveyStatus.EMERGENCY_STOP
                survey.result = self._triage(survey).model_dump()
            elif len(survey.answers) == len(QUESTIONS):
                survey.status = SurveyStatus.REVIEWING
                survey.result = self._triage(survey).model_dump()
            response = self._serialize(survey)
            survey.idempotency[key] = (payload_hash, response.model_dump(mode="json"))
            return response, survey.revision

    async def back(self, session_id: UUID, owner_id: str, target_step: int) -> SessionResponse:
        async with self._store.open(session_id, owner_id) as survey:
            if survey.status == SurveyStatus.EMERGENCY_STOP:
                raise HTTPException(status_code=409, detail="emergency_requires_new_session")
            if survey.status not in (SurveyStatus.COLLECTING, SurveyStatus.REVIEWING, SurveyStatus.COMPLETED):
                raise HTTPException(status_code=409, detail="invalid_session_state")
            if target_step >= len(survey.answers):
                raise HTTPException(status_code=409, detail="invalid_target_step")
            for question in QUESTIONS[target_step:]:
                survey.answers.pop(question, None)
                survey.nlp.pop(question, None)
            survey.revision += 1
            # Prior idempotency responses must never resurrect outdated triage results.
            survey.idempotency.clear()
            survey.result = None
            survey.rule_codes = find_emergency_rules(survey.answers)
            survey.status = SurveyStatus.COLLECTING
            return self._serialize(survey)

    async def triage(self, session_id: UUID, owner_id: str) -> TriageResponse:
        async with self._store.open(session_id, owner_id) as survey:
            if survey.status == SurveyStatus.COMPLETED and survey.result and survey.result.get("analysis_source"):
                return TriageResponse.model_validate(survey.result)
            survey.rule_codes = find_emergency_rules(survey.answers)
            if survey.rule_codes:
                survey.status = SurveyStatus.EMERGENCY_STOP
            result = self._triage(survey)
            survey.result = result.model_dump()
            if survey.status == SurveyStatus.REVIEWING:
                survey.status = SurveyStatus.COMPLETED
            if survey.status != SurveyStatus.COMPLETED or survey.rule_codes or self._analyst is None:
                return result
            revision = survey.revision
            context = {"answers": json.loads(json.dumps(survey.answers)), "result": result.model_dump()}
        # The provider must not hold database locks or rewrite medical routing.
        event("survey.analysis_started", mode=self._analysis_source)
        try:
            reply = await self._analyst.reply([{"role": "user", "content": (
                "Составь разбор завершённой анкеты: кратко обобщи указанные жалобы, их длительность, "
                "выраженность и важные сведения анамнеза. Укажи, каких данных не хватает, и вопросы врачу. "
                "Используй только факты из анкеты, отличай неизвестное от отрицательного ответа. "
                "Не ставь диагноз, не назначай лечение, не меняй срочность и маршрут из результата. "
                "При UNKNOWN поясни, что срочность не определена и требуется оценка специалиста."
            )}], context)
            result.analysis = reply.text
            result.analysis_source = self._analysis_source
            event("survey.analysis_completed", mode=self._analysis_source)
        except GroqError as error:
            result.analysis_source = "unavailable"
            event("survey.analysis_failed", code=error.code)
        async with self._store.open(session_id, owner_id) as survey:
            if survey.revision != revision or survey.status != SurveyStatus.COMPLETED:
                raise HTTPException(status_code=409, detail="questionnaire_changed")
            if survey.result and survey.result.get("analysis_source"):
                return TriageResponse.model_validate(survey.result)
            survey.result = result.model_dump()
        return result

    async def delete(self, session_id: UUID, owner_id: str) -> None:
        await self._store.delete(session_id, owner_id)
