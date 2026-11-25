import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.db.clinic_addresses import address_query, addresses, find_addresses
from app.db.clinic_catalog import branches, import_catalog, search_clinics
from app.db.clinic_sources import clinic_sources, oms_participants
from app.db.import_clinic_addresses import address_rows, replace_addresses
from app.db.import_poliklinika45 import apply_snapshot
from app.integrations.poliklinika45 import PROFILES_URL, SourceSnapshot
from app.main import create_app
from app.schemas.clinics import ClinicCatalog, ClinicSearch
from app.services.sessions import SessionService

ADDRESS_SAMPLE = Path(__file__).resolve().parents[2] / "clinic_catalog" / "kurgan-osm-sample.json"
SOURCE = "https://example.invalid/clinic"


def local_catalog(records, *, demo=False):
    organizations = []
    entries = []
    for branch_id, name, kind, fields in records:
        organizations.append({"id": branch_id, "name": name, "kind": kind})
        entries.append({
            "id": branch_id, "organization_id": branch_id, "address": "Курган, улица Гоголя, 5",
            "lat": 55.44, "lon": 65.34, "phones": ["+12025550101"], "source": SOURCE, **fields,
        })
    return ClinicCatalog.model_validate({"demo": demo, "organizations": organizations, "branches": entries})


def confirmed_offer(method, specialty_code, **fields):
    return {"method": method, "specialty_code": specialty_code, "source": SOURCE,
            "checked_on": "2026-11-25", "confirmed": True, **fields}


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_clinic_catalog_reimport_and_demo_visibility(db):
    real = local_catalog([
        ("adult", "Взрослая поликлиника", "public", {"audience": "adult", "payments": [
            confirmed_offer("oms", "gynecologist"), confirmed_offer("oms", "preventive_care")]}),
        ("child", "Детская поликлиника", "public", {"audience": "child", "payments": [
            confirmed_offer("oms", "gynecologist")]}),
        ("private", "Частная поликлиника", "private", {"payments": [
            confirmed_offer("paid", "dermatologist")]}),
    ])
    demo = local_catalog([
        ("demo-branch", "Демонстрационный филиал", "private", {"payments": [
            confirmed_offer("dms", "therapist", insurer={"id": "demo-insurer", "name": "Демонстрационная страховая"})]}),
    ], demo=True)
    for catalog in (real, demo):
        await import_catalog(db, catalog)
        await import_catalog(db, catalog)
    assert await db.scalar(select(func.count()).select_from(branches)) == 4
    point = ClinicSearch(lat=55.445, lon=65.34, radius_km=10, patient_group="adult")
    live = await search_clinics(db, point, demo_mode=False)
    assert {branch.id for branch in live.items} == {"adult", "private"}
    assert all(not branch.demo for branch in live.items)
    [public] = [branch for branch in live.items if branch.kind == "public"]
    assert {offer.specialty_code for offer in public.payments} == {"gynecologist", "preventive_care"}
    assert len(public.payments) == 2
    paid = point.model_copy(update={"payment_method": "paid", "specialty_code": "dermatologist"})
    result = await search_clinics(db, paid, demo_mode=False)
    assert [branch.id for branch in result.items] == ["private"]
    assert all(offer.method == "paid" and offer.specialty_code == "dermatologist"
               for branch in result.items for offer in branch.payments)
    gynecology = point.model_copy(update={"payment_method": "oms", "specialty_code": "gynecologist"})
    adults = await search_clinics(db, gynecology, demo_mode=False)
    assert [branch.id for branch in adults.items] == ["adult"]
    children = await search_clinics(db, gynecology.model_copy(update={"patient_group": "child"}), demo_mode=False)
    assert [branch.id for branch in children.items] == ["child"]
    available = await search_clinics(db, point.model_copy(update={"payment_method": "dms"}), demo_mode=True)
    assert [branch.id for branch in available.items] == ["demo-branch"]
    assert available.items[0].payments[0].program is None


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_local_address_suggestions_and_exact_house_parts(db):
    rows = address_rows({"elements": [
        {"type": "node", "id": index, "lat": 55.44, "lon": 65.34,
         "tags": {"addr:street": "улица Тимофея Невежина", "addr:housenumber": house}}
        for index, house in enumerate(["5", "5к1", "5с2", "50", "5"], start=1)
    ]})
    await replace_addresses(db, rows)
    await replace_addresses(db, rows)
    assert await db.scalar(select(func.count()).select_from(addresses)) == 5

    async def houses(value):
        return [item.label.split(", ")[-1] for item in await find_addresses(db, *address_query(value))]

    assert await houses("Невежина") == ["5", "50", "5к1", "5с2"]
    assert await houses("ул. Невёжина 5") == ["5", "5к1", "5с2"]
    assert await houses("Курган, Невежина, д. 5 корпус 1") == ["5к1"]
    assert await houses("Курган, Невежина, 5 строение 2") == ["5с2"]
    assert await houses("Невежина 999") == []


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_address_api_searches_the_bundled_osm_sample_without_a_provider(db):
    rows = address_rows(json.loads(ADDRESS_SAMPLE.read_bytes()))
    await replace_addresses(db, rows)
    assert len(rows) == 44

    @asynccontextmanager
    async def session():
        yield db

    settings = Settings(demo_mode=True, session_signing_key="t" * 48)
    app = create_app(settings, session_service=SessionService(settings.survey_ttl_seconds))
    app.state.clinic_db = session
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
        token = (await client.post("/api/v1/auth/launch", json={"mode": "demo"})).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        response = await client.post(
            "/api/v1/clinics/geocode", headers=headers,
            json={"address": "640000, Россия, Курганская обл., г Курган, ул. Кравченко, д. 53, кв. 21"},
        )
        assert response.status_code == 200
        [candidate] = response.json()["candidates"]
        assert candidate["city"] == "Курган"
        assert candidate["lat"] == pytest.approx(55.4435653)
        assert candidate["lon"] == pytest.approx(65.3630374)
        reverse = await client.post(
            "/api/v1/clinics/reverse-geocode", headers=headers,
            json={"lat": candidate["lat"] + 0.00002, "lon": candidate["lon"]},
        )
        assert reverse.status_code == 200
        assert reverse.json()["candidates"] == [candidate]
        distant = await client.post(
            "/api/v1/clinics/reverse-geocode", headers=headers, json={"lat": 55.335, "lon": 65.53},
        )
        assert distant.status_code == 200
        assert distant.json()["candidates"] == []


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_portal_merge_is_idempotent_and_keeps_confirmed_base_values(db):
    catalog = local_catalog([
        ("original-branch", "Синтетическая поликлиника", "public", {
            "address": "Курган, улица Кравченко, 53", "phones": ["+12025550108"],
        }),
    ])
    await import_catalog(db, catalog)
    await replace_addresses(db, address_rows(json.loads(ADDRESS_SAMPLE.read_bytes())))
    records = [
        {"kind": "organization", "external_id": "synthetic-org-1", "name": "Синтетическая поликлиника",
         "specialties": ["Хирург"]},
        {"kind": "branch", "external_id": "synthetic-branch-1", "organization_external_id": "synthetic-org-1",
         "address": "г.Курган, ул. Кравченко, 53", "phones": ["+12025550109"], "specialties": ["Врач-невролог"]},
        {"kind": "organization", "external_id": "synthetic-org-2", "name": "Синтетический центр", "facility_kind": "private"},
        {"kind": "branch", "external_id": "synthetic-branch-2", "organization_external_id": "synthetic-org-2",
         "address": "Курган, ул. Коли Мяготина, 53", "phones": ["+12025550110"], "specialties": ["Дерматовенеролог"]},
        {"kind": "branch", "external_id": "synthetic-branch-3", "organization_external_id": "synthetic-org-2",
         "address": "Курган, ул. Коли Мяготина, 999", "phones": ["+12025550110"]},
    ]
    institution_url = "https://www.poliklinika45.ru/service/hospitals/view/99001"
    payload = {
        "schema_version": 1, "source": "poliklinika45", "complete": True,
        "retrieved_at": "2026-11-25T05:00:00Z", "start_url": PROFILES_URL,
        "pages": [{"url": PROFILES_URL, "records": [
            record | {"url": institution_url if record["external_id"] == "synthetic-org-1" else PROFILES_URL}
            for record in records
        ]}],
    }
    snapshot = SourceSnapshot.model_validate(payload)
    first = await apply_snapshot(db, snapshot, snapshot.records())
    assert first["matched"] == first["created"] == 1
    assert first["needs_review"][0]["reason"] == "address_not_exact_or_ambiguous"
    assert first["conflicts"][0]["field"] == "phones"
    second = await apply_snapshot(db, snapshot, snapshot.records())
    assert second["matched"] == 2 and second["created"] == 0
    assert await db.scalar(select(func.count()).select_from(clinic_sources)) == 5
    assert await db.scalar(select(func.count()).select_from(branches)) == 2

    query = ClinicSearch(lat=55.44, lon=65.34, specialty_code="neurologist")
    result = await search_clinics(db, query, demo_mode=False)
    [item] = result.items
    assert item.id == "original-branch"
    assert item.phones == ["+12025550108"]
    assert item.payments == []
    assert item.sources[-1].name == "Поликлиника45"
    assert item.sources[-1].updated_at == snapshot.retrieved_at
    oms_query = query.model_copy(update={"payment_method": "oms"})
    assert (await search_clinics(db, oms_query, demo_mode=False)).items == []
    assert (await search_clinics(db, query.model_copy(update={"specialty_code": "surgeon"}), demo_mode=False)).items == []
    await db.execute(oms_participants.insert().values(poliklinika45_id="synthetic-org-1", evidence_url=SOURCE))
    [candidate] = (await search_clinics(db, oms_query, demo_mode=False)).items
    assert candidate.id == item.id
    assert candidate.oms_needs_confirmation
    assert candidate.payments == []
    for filters in ({"specialty_code": "surgeon"}, {"patient_group": "child"}, {"payment_method": "paid"}):
        result = await search_clinics(db, oms_query.model_copy(update=filters), demo_mode=False)
        assert result.items == []

    changed = SourceSnapshot.model_validate(payload | {"retrieved_at": "2026-11-26T05:00:00Z"})
    changed.pages[0].records[1].address = "Курган, ул. Кравченко, 54"
    changed.pages[0].records[1].specialties = ["Педиатр"]
    third = await apply_snapshot(db, changed, changed.records())
    assert third["conflicts"][0]["field"] == "address"
    assert (await search_clinics(db, query, demo_mode=False)).items[0].sources[-1].updated_at == snapshot.retrieved_at
