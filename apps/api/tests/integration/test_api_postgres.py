import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from app.core.config import Settings
from app.core.encryption import (
    DataEncryptionError,
    JsonCipher,
    answer_context,
    message_context,
    state_context,
)
from app.core.security import issue_access_token
from app.db.models import (
    AnswerRecord,
    AuditEventRecord,
    MessageRecord,
    SessionRecord,
    TriageResultRecord,
)
from app.db.repository import (
    append_message,
    delete_expired_sessions,
    get_messages,
    list_sessions,
)
from app.db.results import decode_result
from app.main import create_app
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

pytestmark = [pytest.mark.postgres, pytest.mark.asyncio]
OWNER = "synthetic:api-owner"
OTHER = "synthetic:api-other"


@pytest_asyncio.fixture
async def api(engine, database_url):
    settings = replace(
        Settings.from_env(), database_url=database_url, demo_mode=True,
        session_signing_key="synthetic-integration-signing-key-48-characters-long",
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def connect(owner=OWNER, **overrides):
        current = replace(settings, **overrides)
        app = create_app(current)
        token = issue_access_token(owner, current.session_signing_key, 3600)
        async with app.router.lifespan_context(app), httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://testserver",
            headers={"Authorization": "Bearer " + token},
        ) as client:
            yield client

    try:
        yield connect, factory
    finally:
        async with factory.begin() as db:
            await db.execute(delete(SessionRecord).where(SessionRecord.owner_id.in_([OWNER, OTHER])))


async def create(client):
    response = await client.post("/api/v1/sessions", json={"accepted_disclaimer": True})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def payload(question="primary_complaint", value=None, key=None):
    return {
        "question_key": question,
        "value": value if value is not None else {"category": "skin", "text": "synthetic marker 4821"},
        "idempotency_key": key or str(uuid4()),
    }


async def test_restart_recovers_answers_and_idempotency_without_plaintext(api):
    connect, factory = api
    body = payload()
    async with connect() as client:
        sid = await create(client)
        path = f"/api/v1/sessions/{sid}"
        first = await client.post(path + "/answers", json=body)
        assert first.status_code == 200
    async with factory() as db:
        answer = await db.scalar(select(AnswerRecord).where(AnswerRecord.session_id == UUID(sid)))
        survey = await db.get(SessionRecord, UUID(sid))
        for sealed in (answer.value_jsonb, survey.state_jsonb):
            assert set(sealed) == {"v", "n", "c"}
            assert "synthetic marker" not in json.dumps(sealed)
        cipher = JsonCipher.from_file(Settings.from_env().data_encryption_key_file)
        assert cipher.decrypt(answer.value_jsonb, answer_context(UUID(sid), "primary_complaint")) == body["value"]
        assert body["idempotency_key"] in cipher.decrypt(survey.state_jsonb, state_context(UUID(sid)))["idempotency"]
    async with connect() as restarted:
        current = await restarted.get(path)
        assert current.json() == first.json()
        replay = await restarted.post(path + "/answers", json=body)
        assert replay.json() == first.json()
        conflict = await restarted.post(path + "/answers", json={**body, "value": {"category": "other"}})
        assert conflict.status_code == 409
        assert current.headers["Strict-Transport-Security"] == "max-age=31536000"
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(AnswerRecord)) == 1
        messages = await get_messages(db, UUID(sid), OWNER)
        assert [(row.role, row.kind) for row in messages] == [
            ("assistant", "question"), ("user", "answer"), ("assistant", "question"),
        ]
        assert cipher.decrypt(messages[1].content_jsonb, message_context(UUID(sid), messages[1].id)) == {
            "question_key": "primary_complaint", "value": body["value"],
        }
        assert "synthetic marker" not in json.dumps([row.content_jsonb for row in messages])


async def test_concurrent_idempotency_stores_exactly_one_answer(api):
    connect, factory = api
    async with connect() as client:
        sid = await create(client)
        body = payload()
        responses = await asyncio.gather(*[
            client.post(f"/api/v1/sessions/{sid}/answers", json=body) for _ in range(4)
        ])
        assert all(response.status_code == 200 for response in responses)
        assert all(response.json() == responses[0].json() for response in responses)
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(AnswerRecord)) == 1
        assert await db.scalar(select(func.count()).select_from(MessageRecord)) == 3
        assert await db.scalar(select(func.count()).select_from(AuditEventRecord).where(
            AuditEventRecord.kind == "answer_saved",
        )) == 1


async def test_completed_result_and_back_are_persistent(api):
    connect, factory = api
    bodies = [
        payload(value={"category": "skin"}),
        payload("patient_context", {"age_years": 30}),
        payload("symptom_details", {"severity_0_10": 2, "duration": "1 day"}),
        payload("red_flags", {
            "chest_pain": False, "dyspnea_rest": False, "loss_of_consciousness": False,
            "seizure": False, "bleeding": False, "facial_asymmetry": False,
            "arm_weakness": False, "speech_difficulty": False, "anaphylaxis": False,
            "acute_abdominal_pain": False, "head_injury_with_loc": False,
        }),
        payload("medical_history", {}),
    ]
    async with connect() as client:
        sid = await create(client)
        path = f"/api/v1/sessions/{sid}"
        for body in bodies:
            response = await client.post(path + "/answers", json=body)
            assert response.status_code == 200, response.text
        result = await client.post(path + "/triage")
        assert result.json()["urgency"] == "PLANNED"
    async with factory() as db:
        persisted = await db.scalar(select(TriageResultRecord).where(TriageResultRecord.session_id == UUID(sid)))
        cipher = JsonCipher.from_file(Settings.from_env().data_encryption_key_file)
        assert decode_result(persisted, cipher) == result.json()
        session = await db.get(SessionRecord, UUID(sid))
        assert "result" not in cipher.decrypt(session.state_jsonb, state_context(UUID(sid)))
        assert await db.scalar(select(func.count()).select_from(AuditEventRecord).where(
            AuditEventRecord.session_id == UUID(sid), AuditEventRecord.kind == "answer_saved",
        )) == 5
    async with connect() as client:
        current = (await client.get(path)).json()
        assert current["status"] == "COMPLETED"
        assert current["result"] == result.json()
        back = await client.post(path + "/back", json={"target_step": 0})
        assert back.json()["result"] is None
        assert back.json()["progress"]["answered"] == 0
        changed = await client.post(path + "/answers", json={
            **bodies[0], "value": {"category": "other"},
        })
        assert changed.status_code == 200
        assert changed.json()["result"] is None
    async with factory() as db:
        assert await db.scalar(select(TriageResultRecord).where(TriageResultRecord.session_id == UUID(sid))) is None
        assert await db.scalar(select(func.count()).select_from(AnswerRecord)) == 1
        history = await get_messages(db, UUID(sid), OWNER)
        cipher = JsonCipher.from_file(Settings.from_env().data_encryption_key_file)
        results = [cipher.decrypt(row.content_jsonb, message_context(UUID(sid), row.id))
                   for row in history if row.kind == "result"]
        assert results[0]["result"] == result.json()
        assert "medical_history" in results[0]["answers"]
        assert any(row.kind == "back" for row in history)


async def test_emergency_persists_across_restart(api):
    connect, _ = api
    async with connect() as client:
        sid = await create(client)
        path = f"/api/v1/sessions/{sid}"
        stopped = await client.post(path + "/answers", json=payload(value={
            "category": "pain", "text": "\u0431\u043e\u043b\u044c \u0432 \u0433\u0440\u0443\u0434\u0438",
        }))
        assert stopped.json()["status"] == "EMERGENCY_STOP"
    async with connect() as client:
        current = (await client.get(path)).json()
        assert current == stopped.json()
        assert current["result"]["urgency"] == "EMERGENCY"
        assert (await client.post(path + "/back", json={"target_step": 0})).status_code == 409


async def test_history_list_ownership_pagination_expiry_and_delete(api):
    connect, factory = api
    async with connect() as client:
        first = await create(client)
        second = await create(client)
        expired = await create(client)
        await client.post(f"/api/v1/sessions/{first}/answers", json=payload())
    now = datetime.now(UTC)
    async with factory.begin() as db:
        row = await db.get(SessionRecord, UUID(expired))
        row.created_at = now - timedelta(hours=2)
        row.expires_at = now - timedelta(hours=1)
    async with connect(OTHER) as other:
        other_id = await create(other)
        assert (await other.get(f"/api/v1/sessions/{first}")).status_code == 403
    async with factory() as db:
        assert await get_messages(db, UUID(first), OTHER) == []
        assert [row.id for row in await list_sessions(db, OTHER)] == [UUID(other_id)]
        assert [row.id for row in await list_sessions(db, OWNER, limit=1)] == [UUID(second)]
        assert [row.id for row in await list_sessions(db, OWNER, limit=1, offset=1)] == [UUID(first)]
        assert await get_messages(db, UUID(expired), OWNER) == []
        assert await get_messages(db, uuid4(), OWNER) == []
        with pytest.raises(ValueError):
            await list_sessions(db, OWNER, limit=101)
    async with connect() as client:
        assert (await client.get(f"/api/v1/sessions/{expired}")).status_code == 404
        assert (await client.delete(f"/api/v1/sessions/{first}")).status_code == 204
        assert (await client.get(f"/api/v1/sessions/{first}")).status_code == 404
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(AnswerRecord)) == 0
        assert await get_messages(db, UUID(first), OWNER) == []
        assert [row.id for row in await list_sessions(db, OWNER)] == [UUID(second)]
    async with factory.begin() as db:
        await delete_expired_sessions(db)
        assert await db.scalar(select(func.count()).select_from(MessageRecord).where(
            MessageRecord.session_id == UUID(expired),
        )) == 0


async def test_free_chat_storage_is_encrypted_and_owner_scoped(api):
    connect, factory = api
    async with connect() as client:
        sid = UUID(await create(client))
    async with factory.begin() as db:
        row = await append_message(db, sid, OWNER, "user", "text", {"text": "synthetic chat marker"})
        identifier = row.id
    async with factory() as db:
        history = await get_messages(db, sid, OWNER)
        assert history[-1].id == identifier
        cipher = JsonCipher.from_file(Settings.from_env().data_encryption_key_file)
        assert cipher.decrypt(history[-1].content_jsonb, message_context(sid, identifier)) == {
            "text": "synthetic chat marker",
        }
        assert "synthetic chat marker" not in json.dumps(history[-1].content_jsonb)
    async with factory.begin() as db:
        with pytest.raises(LookupError):
            await append_message(db, sid, OTHER, "user", "text", {"text": "forbidden"})


async def test_database_rejects_unencrypted_chat_content(api):
    from sqlalchemy.exc import IntegrityError

    connect, factory = api
    async with connect() as client:
        sid = UUID(await create(client))
    with pytest.raises(IntegrityError):
        async with factory.begin() as db:
            db.add(MessageRecord(
                session_id=sid, sequence_no=2, role="user", kind="text",
                content_jsonb={"text": "synthetic plaintext"},
            ))
            await db.flush()


async def test_corrupted_ciphertext_returns_sanitized_error(api):
    connect, factory = api
    async with connect() as client:
        sid = await create(client)
        await client.post(f"/api/v1/sessions/{sid}/answers", json=payload())
        async with factory.begin() as db:
            row = await db.scalar(select(AnswerRecord).where(AnswerRecord.session_id == UUID(sid)))
            row.value_jsonb = {**row.value_jsonb, "c": "YWJj"}
        response = await client.get(f"/api/v1/sessions/{sid}")
        assert response.status_code == 503
        assert response.json() == {"detail": "storage_unavailable"}


async def test_wrong_key_does_not_reset_or_reveal_session(api, tmp_path):
    import base64

    connect, _ = api
    async with connect() as client:
        sid = await create(client)
    key = tmp_path / "wrong-key"
    key.write_bytes(base64.urlsafe_b64encode(b"z" * 32))
    with pytest.raises(DataEncryptionError, match="authentication failed"):
        async with connect(data_encryption_key_file=str(key)):
            pytest.fail("API must not start with a key that cannot authenticate its rule catalog")
    async with connect() as client:
        assert (await client.get(f"/api/v1/sessions/{sid}")).status_code == 200


async def test_http_and_forwarded_proto_cannot_bypass_https(api):
    connect, _ = api
    async with connect() as client:
        response = await client.get("http://testserver/health", headers={"X-Forwarded-Proto": "https"})
        assert response.status_code == 426
        assert response.json() == {"detail": "https_required"}
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.headers["Strict-Transport-Security"]



async def test_corrupt_result_does_not_fall_back_to_session_or_message_cache(api):
    connect, factory = api
    async with connect() as client:
        sid = await create(client)
        response = await client.post(f"/api/v1/sessions/{sid}/triage")
        assert response.status_code == 200
        async with factory.begin() as db:
            row = await db.scalar(select(TriageResultRecord).where(TriageResultRecord.session_id == UUID(sid)))
            row.rationale = {**row.rationale, "c": "YWJj"}
        current = await client.get(f"/api/v1/sessions/{sid}")
        assert current.status_code == 503
        assert current.json() == {"detail": "storage_unavailable"}


async def test_audit_failure_rolls_back_answer_and_messages(api, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError

    connect, factory = api
    async with connect() as client:
        sid = await create(client)
        async def unavailable(*args, **kwargs):
            raise SQLAlchemyError("synthetic audit storage failure")
        monkeypatch.setattr("app.db.survey_store.record_audit", unavailable)
        response = await client.post(f"/api/v1/sessions/{sid}/answers", json=payload())
        assert response.status_code == 503
        assert (await client.get(f"/api/v1/sessions/{sid}")).json()["progress"]["answered"] == 0
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(AnswerRecord)) == 0
        assert await db.scalar(select(func.count()).select_from(MessageRecord)) == 1
