import asyncio
from uuid import uuid4

import pytest
from app.integrations.chat_agent import SurveyAnalysis
from app.integrations.groq.exceptions import GroqTimeout
from app.schemas.survey import AnswerRequest, RedFlags
from app.services.sessions import SessionService
from fastapi import HTTPException


class Analyst:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    async def analyze(self, answers):
        self.calls.append(answers)
        if self.fail:
            raise GroqTimeout()
        return SurveyAnalysis(specialty="Терапевт", rationale="Первичное обращение по поводу кашля.", text="Указан кашель два дня. Уточните изменение симптомов.", needs_clarification=False)


async def completed(service):
    survey = await service.create('owner')
    for key, value in (
        ('primary_complaint', {'category': 'other', 'text': 'Кашель 2 дня'}),
        ('patient_context', {'age_years': 30}),
        ('symptom_details', {'duration': '2 дня', 'severity_0_10': 2}),
        ('red_flags', {key: False for key in RedFlags.model_fields}),
        ('medical_history', {'allergies': ['Синтетический пример']}),
    ):
        await service.answer(survey.id, 'owner', AnswerRequest(question_key=key, value=value, idempotency_key=uuid4()))
    return survey.id


def test_analysis_uses_whole_survey_and_preserves_rules_and_cached_result():
    async def run():
        analyst = Analyst()
        service = SessionService(analyst=analyst)
        identifier = await completed(service)
        result = await service.triage(identifier, 'owner')
        assert result.urgency == 'UNKNOWN' and result.specialty == 'Терапевт'
        assert result.analysis_source == 'groq' and 'кашель' in result.analysis
        assert analyst.calls[0]['medical_history']['allergies'] == ['Синтетический пример']
        assert len(analyst.calls[0]) == 5
        assert (await service.get(identifier, 'owner')).result['analysis'] == result.analysis
        assert await service.triage(identifier, 'owner') == result
        assert len(analyst.calls) == 1
        await service.back(identifier, 'owner', 0)
        assert (await service.get(identifier, 'owner')).result is None
    asyncio.run(run())


def test_failure_is_explicit_and_does_not_erase_rules():
    async def run():
        service = SessionService(analyst=Analyst(fail=True))
        result = await service.triage(await completed(service), 'owner')
        assert result.analysis is None and result.analysis_source == 'unavailable'
        assert result.urgency == 'UNKNOWN' and result.needs_clarification
    asyncio.run(run())


def test_emergency_and_incomplete_skip_analysis():
    async def run():
        analyst = Analyst()
        service = SessionService(analyst=analyst)
        identifier = (await service.create('owner')).id
        assert (await service.triage(identifier, 'owner')).urgency == 'UNKNOWN'
        await service.answer(identifier, 'owner', AnswerRequest(question_key='primary_complaint',
            value={'category': 'pain', 'text': 'Болит грудь'}, idempotency_key=uuid4()))
        assert (await service.triage(identifier, 'owner')).urgency == 'EMERGENCY'
        assert analyst.calls == []
    asyncio.run(run())


@pytest.mark.parametrize('action', ['edit', 'delete'])
def test_late_analysis_cannot_restore_edited_or_deleted_survey(action):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        class Slow(Analyst):
            async def analyze(self, answers):
                entered.set()
                await release.wait()
                return await super().analyze(answers)
        service = SessionService(analyst=Slow())
        identifier = await completed(service)
        pending = asyncio.create_task(service.triage(identifier, 'owner'))
        await asyncio.wait_for(entered.wait(), 1)
        if action == 'edit':
            await service.back(identifier, 'owner', 0)
        else:
            await service.delete(identifier, 'owner')
        release.set()
        with pytest.raises(HTTPException) as error:
            await pending
        assert error.value.status_code == (409 if action == 'edit' else 404)
    asyncio.run(run())
