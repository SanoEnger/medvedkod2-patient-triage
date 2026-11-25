import asyncio
import json
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.integrations.chat_agent import ChatAgent
from app.integrations.emergency_explanation import fallback_reason
from app.integrations.groq.exceptions import GroqTimeout, InvalidResponse
from app.schemas.survey import AnswerRequest
from app.services.sessions import SessionService

TEXT = "Опрос остановлен из-за указанной боли в груди."


def test_reason_uses_only_confirmed_signs_and_preserves_codes():
    async def scenario():
        provider = AsyncMock()
        provider.respond.return_value = json.dumps({"text": TEXT, "rule_codes": ["RF_CHEST_PAIN"]})
        assert await ChatAgent(provider).explain_emergency(["RF_CHEST_PAIN"]) == TEXT
        payload = json.loads(provider.respond.call_args.args[0][1]["content"])
        assert payload == {"signs": [{"code": "RF_CHEST_PAIN", "label": "боль или сдавление в груди"}]}
    asyncio.run(scenario())


@pytest.mark.parametrize("text,codes", [
    (TEXT, ["RF_SEIZURE"]), ("Продолжайте опрос, опасности нет.", ["RF_CHEST_PAIN"]),
    ("Принимайте 500 мг препарата.", ["RF_CHEST_PAIN"]),
    ("Перейдите https://example.com", ["RF_CHEST_PAIN"]),
    ("Опрос остановлен. Звоните 103.", ["RF_CHEST_PAIN"]),
])
def test_invalid_explanation_is_rejected(text, codes):
    async def scenario():
        provider = AsyncMock()
        provider.respond.return_value = json.dumps({"text": text, "rule_codes": codes})
        with pytest.raises(InvalidResponse):
            await ChatAgent(provider).explain_emergency(["RF_CHEST_PAIN"])
    asyncio.run(scenario())


@pytest.mark.parametrize("failed", [False, True])
def test_emergency_is_immediate_and_explanation_is_cached_separately(failed):
    async def scenario():
        analyst = AsyncMock()
        analyst.explain_emergency.return_value = TEXT
        if failed:
            analyst.explain_emergency.side_effect = GroqTimeout()
        service = SessionService(analyst=analyst)
        session = await service.create("owner")
        result = await service.answer(session.id, "owner", AnswerRequest(
            question_key="primary_complaint", value={"category": "pain", "text": "Боль в груди"}, idempotency_key=uuid4()))
        assert result.emergency
        assert "боль" in result.result["rationale"]
        analyst.explain_emergency.assert_not_called()
        reason = await service.explain_emergency(session.id, "owner")
        assert reason.emergency
        assert reason.result["analysis"] == (None if failed else TEXT)
        assert reason.result["analysis_source"] == ("unavailable" if failed else "groq")
        assert (await service.explain_emergency(session.id, "owner")) == reason
        assert (await service.get(session.id, "owner")) == reason
        analyst.explain_emergency.assert_awaited_once_with(["RF_CHEST_PAIN"])
        with pytest.raises(HTTPException) as error:
            await service.explain_emergency(session.id, "other")
        assert error.value.status_code == 403
    asyncio.run(scenario())


def test_explanation_cannot_be_requested_before_an_emergency():
    async def scenario():
        analyst = AsyncMock()
        service = SessionService(analyst=analyst)
        session = await service.create("owner")
        with pytest.raises(HTTPException) as error:
            await service.explain_emergency(session.id, "owner")
        assert error.value.status_code == 409
        analyst.explain_emergency.assert_not_called()
    asyncio.run(scenario())


def test_every_emergency_code_has_a_named_fallback_reason():
    from app.services.safety import _RULE_FIELDS
    for code in set(_RULE_FIELDS.values()) | {"RF_CHILD_FEVER_39_5"}:
        assert "из-за отмеченных признаков:" in fallback_reason([code])
