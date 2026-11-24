import asyncio
import json
from uuid import uuid4

import pytest

from app.integrations.groq import SymptomExtractor
from app.integrations.groq.exceptions import GroqTimeout
from app.schemas.survey import AnswerRequest, MedicalHistory
from app.services.sessions import SessionService

PHRASE = "За грудиной сжимает и давит прямо сейчас"
STEPS = [
    ("primary_complaint", {"category": "other", "text": "Кашель"}),
    ("patient_context", {"age_years": 30, "temperature_c": 36.6}),
    ("symptom_details", {"location": "горло", "duration": "два дня"}),
    ("red_flags", {}),
    ("medical_history", {}),
]


def test_migration_seed_matches_current_safety_implementation():
    from pathlib import Path
    from app.db.safety_catalog import runtime_rules

    seed = Path(__file__).parents[1] / "alembic/seeds/20261124_06_safety_rules.json"
    assert json.loads(seed.read_text(encoding="utf-8")) == list(runtime_rules())


class SemanticProvider:
    def __init__(self, status="present", code="chest_pain"):
        self.calls = []
        self.status, self.code = status, code

    async def complete(self, text):
        self.calls.append(text)
        symptoms = []
        if PHRASE in text:
            symptoms = [{"code": self.code, "evidence": PHRASE, "status": self.status}]
        return json.dumps({"symptoms": symptoms, "details": [], "needs_clarification": False})


def body(question, value):
    return AnswerRequest(question_key=question, value=value, idempotency_key=uuid4())


@pytest.mark.parametrize("step,field", [
    (0, "text"), (2, "location"), (2, "duration"), (2, "additional_text"),
    *((4, field) for field in MedicalHistory.model_fields),
])
def test_semantic_emergency_on_every_free_text_field(step, field):
    async def scenario():
        provider = SemanticProvider()
        service = SessionService(extractor=SymptomExtractor(provider))
        survey = await service.create("owner")
        for question, value in STEPS[:step]:
            await service.answer(survey.id, "owner", body(question, value))
        question, defaults = STEPS[step]
        value = {**defaults, field: [PHRASE] if step == 4 else PHRASE}
        request = body(question, value)
        response = await service.answer(survey.id, "owner", request)
        assert response.emergency and response.status == "EMERGENCY_STOP"
        assert response.current_question is None
        assert response.result["urgency"] == "EMERGENCY"
        assert response.matched_rule_codes == ["RF_CHEST_PAIN"]
        assert "103/112" in response.message
        assert PHRASE in provider.calls[-1]
        count = len(provider.calls)
        assert await service.answer(survey.id, "owner", request) == response
        assert len(provider.calls) == count
        assert (await service.get(survey.id, "owner")).emergency
        assert (await service.triage(survey.id, "owner")).urgency == "EMERGENCY"
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as stopped:
            await service.back(survey.id, "owner", 0)
        assert stopped.value.status_code == 409
    asyncio.run(scenario())


@pytest.mark.parametrize("status", ["negated", "uncertain"])
def test_model_negation_and_uncertainty_do_not_stop_survey(status):
    async def scenario():
        service = SessionService(extractor=SymptomExtractor(SemanticProvider(status)))
        survey = await service.create("owner")
        result = await service.answer(survey.id, "owner", body("primary_complaint", {"category": "other", "text": PHRASE}))
        assert not result.emergency
        assert result.current_question == "patient_context"
    asyncio.run(scenario())


@pytest.mark.parametrize("text", ["В прошлом была боль в груди", "У мамы боль в груди", "Нет боли в груди"])
def test_historical_family_and_negated_reports_are_not_current_flags(text):
    async def scenario():
        service = SessionService(extractor=SymptomExtractor(SemanticProvider()))
        survey = await service.create("owner")
        for question, value in STEPS[:4]:
            await service.answer(survey.id, "owner", body(question, value))
        result = await service.answer(survey.id, "owner", body("medical_history", {"family_history": [text]}))
        assert not result.emergency
    asyncio.run(scenario())


def test_ordinary_symptoms_and_negative_history_complete_without_emergency():
    async def scenario():
        provider = SemanticProvider()
        service = SessionService(extractor=SymptomExtractor(provider))
        survey = await service.create("owner")
        for question, value in STEPS:
            if question == "medical_history":
                value = {field: ["Нет"] for field in MedicalHistory.model_fields}
            result = await service.answer(survey.id, "owner", body(question, value))
            assert not result.emergency
        assert result.status == "REVIEWING"
        assert len(provider.calls) == 3  # text on steps 1, 3, 5; numeric step 2 needs no LLM.
    asyncio.run(scenario())


def test_child_temperature_stops_on_second_step_without_provider():
    async def scenario():
        provider = SemanticProvider()
        service = SessionService(extractor=SymptomExtractor(provider))
        survey = await service.create("owner")
        await service.answer(survey.id, "owner", body(*STEPS[0]))
        calls = len(provider.calls)
        result = await service.answer(survey.id, "owner", body("patient_context", {"age_years": 8, "temperature_c": 40}))
        assert result.emergency and "RF_CHILD_FEVER_39_5" in result.matched_rule_codes
        assert len(provider.calls) == calls
    asyncio.run(scenario())


def test_provider_timeout_still_checks_raw_text_on_last_step():
    class Timeout:
        async def complete(self, text):
            raise GroqTimeout()

    async def scenario():
        service = SessionService(extractor=SymptomExtractor(Timeout()))
        survey = await service.create("owner")
        for question, value in STEPS[:4]:
            await service.answer(survey.id, "owner", body(question, value))
        result = await service.answer(survey.id, "owner", body("medical_history", {"allergies": ["Сейчас отекает горло"]}))
        assert result.emergency and "RF_ANAPHYLAXIS" in result.matched_rule_codes
    asyncio.run(scenario())


def test_late_model_emergency_is_not_lost_when_a_later_answer_arrives():
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        class Slow(SemanticProvider):
            async def complete(self, text):
                entered.set()
                await release.wait()
                return await super().complete(text)

        service = SessionService(extractor=SymptomExtractor(Slow()))
        survey = await service.create("owner")
        first = body("primary_complaint", {"category": "other", "text": PHRASE})
        pending = asyncio.create_task(service.answer(survey.id, "owner", first))
        await asyncio.wait_for(entered.wait(), 1)
        second = body("patient_context", {"age_years": 30})
        assert not (await service.answer(survey.id, "owner", second)).emergency
        release.set()
        assert (await pending).emergency
        assert (await service.answer(survey.id, "owner", second)).emergency
        assert (await service.get(survey.id, "owner")).emergency
    asyncio.run(scenario())


@pytest.mark.parametrize("step", [0, 4])
def test_api_returns_model_emergency_in_the_answer_response(step):
    from fastapi.testclient import TestClient
    from app.core.config import Settings
    from app.main import create_app

    service = SessionService(extractor=SymptomExtractor(SemanticProvider()))
    app = create_app(Settings(demo_mode=True, session_signing_key="x" * 40), session_service=service)
    with TestClient(app, base_url="https://testserver") as client:
        token = client.post("/api/v1/auth/launch", json={"mode": "demo"}).json()["access_token"]
        headers = {"Authorization": "Bearer " + token}
        sid = client.post("/api/v1/sessions", json={"accepted_disclaimer": True}, headers=headers).json()["id"]
        for index, (question, defaults) in enumerate(STEPS[:step + 1]):
            value = dict(defaults)
            if index == step:
                value["text" if step == 0 else "allergies"] = PHRASE if step == 0 else [PHRASE]
            request = body(question, value).model_dump(mode="json")
            response = client.post(f"/api/v1/sessions/{sid}/answers", headers=headers, json=request)
            assert response.status_code == 200
        assert response.json()["emergency"]
        assert response.json()["state"] == "EMERGENCY_STOP"
        assert response.json()["next_question"] is None
        assert client.get(f"/api/v1/sessions/{sid}", headers=headers).json()["emergency"]
