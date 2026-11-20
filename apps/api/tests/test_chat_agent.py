import asyncio
import json

import httpx
import pytest

from app.integrations.chat_agent import ChatAgent
from app.integrations.chat_agent import MockChatAgent
from app.integrations.groq.client import GroqClient, GroqSettings
from app.integrations.groq.exceptions import GroqError


def test_mock_chat_is_offline_and_does_not_echo_context():
    reply = asyncio.run(MockChatAgent().reply(
        [{"role": "user", "content": "synthetic-private-marker"}],
        {"answers": {"text": "synthetic-private-marker"}},
    ))
    assert not reply.emergency
    assert "synthetic-private-marker" not in reply.text
    assert "не назначаю лечение" in reply.text


def test_chat_agent_sends_history_and_context_as_data():
    async def handler(request):
        body = json.loads(request.content)
        assert body["messages"][0]["role"] == "system"
        assert json.loads(body["messages"][1]["content"])["questionnaire_context"]["result"]["urgency"] == "UNKNOWN"
        assert body["messages"][-1] == {"role": "user", "content": "Что уточнить?"}
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps({"text": "Уточните длительность симптомов.", "emergency": False}),
        }}]})
    client = GroqClient(GroqSettings(api_key="synthetic-key", model="test-model"), transport=httpx.MockTransport(handler))
    result = asyncio.run(ChatAgent(client).reply([{"role": "user", "content": "Что уточнить?"}], {"result": {"urgency": "UNKNOWN"}}))
    assert result.text == "Уточните длительность симптомов."


@pytest.mark.parametrize("content", ["not-json", '{"text":"x","emergency":"no"}', '{"text":"x","emergency":false,"extra":1}'])
def test_chat_agent_rejects_invalid_json_without_exposing_provider_input(content):
    async def handler(request):
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": content}}]})
    client = GroqClient(GroqSettings(api_key="synthetic-key", model="test-model"), transport=httpx.MockTransport(handler))
    with pytest.raises(GroqError):
        asyncio.run(ChatAgent(client).reply([{"role": "user", "content": "private marker"}], {}))
