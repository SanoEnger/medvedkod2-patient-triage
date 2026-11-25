import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.db.clinic_addresses import address_query, addresses, find_addresses
from app.db.clinic_catalog import branches, import_catalog, search_clinics
from app.db.clinic_sources import clinic_sources
from app.db.import_clinic_addresses import address_rows, replace_addresses
from app.db.import_poliklinika45 import apply_snapshot
from app.integrations.poliklinika45 import PROFILES_URL, SourceSnapshot
from app.main import create_app
from app.schemas.clinics import ClinicCatalog, ClinicSearch
from app.services.sessions import SessionService

CATALOG = Path(__file__).resolve().parents[2] / "clinic_catalog"


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_clinic_catalog_reimport_and_demo_visibility(db):
    real_ids = set()
    total = 0
    for name in ("kurgan.json", "kurgan-demo.json"):
        catalog = ClinicCatalog.model_validate_json((CATALOG / name).read_bytes())
        await import_catalog(db, catalog)
        await import_catalog(db, catalog)
        total += len(catalog.branches)
        if not catalog.demo:
            real_ids.update(branch.id for branch in catalog.branches if branch.audience != "child")
    assert await db.scalar(select(func.count()).select_from(branches)) == total
    point = ClinicSearch(lat=55.445, lon=65.34, radius_km=10, patient_group="adult")
    live = await search_clinics(db, point, demo_mode=False)
    assert {branch.id for branch in live.items} == real_ids
    assert all(not branch.demo for branch in live.items)
    public = [branch for branch in live.items if branch.id in {
        "kurgan-polyclinic-1-nevezhina-5", "kurgan-polyclinic-2-kravchenko-53",
    }]
    assert len(public) == 2
    assert all("preventive_care" in {offer.specialty_code for offer in branch.payments} for branch in public)
    assert sum(len(branch.payments) for branch in public) == 4
    paid = point.model_copy(update={"payment_method": "paid", "specialty_code": "dermatologist"})
    result = await search_clinics(db, paid, demo_mode=False)
    assert {branch.id for branch in result.items} == {"kurgan-alfamed-tomina-61", "kurgan-dnk-sovetskaya-119"}
    assert all(offer.method == "paid" and offer.specialty_code == "dermatologist"
               for branch in result.items for offer in branch.payments)
    gynecology = point.model_copy(update={"payment_method": "oms", "specialty_code": "gynecologist"})
    adults = await search_clinics(db, gynecology, demo_mode=False)
    assert len(adults.items) == 3
    children = await search_clinics(db, gynecology.model_copy(update={"patient_group": "child"}), demo_mode=False)
    assert len(children.items) == 3
    assert not {item.id for item in adults.items} & {item.id for item in children.items}
    available = await search_clinics(db, point.model_copy(update={"payment_method": "dms"}), demo_mode=True)
    assert [branch.id for branch in available.items] == ["demo-kurgan-west"]
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
    rows = address_rows(json.loads((CATALOG / "kurgan-osm-sample.json").read_bytes()))
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


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_portal_merge_is_idempotent_and_keeps_confirmed_base_values(db):
    catalog = ClinicCatalog.model_validate_json((CATALOG / "kurgan.json").read_bytes())
    public_organizations = [org for org in catalog.organizations if org.id in {"kurgan-polyclinic-1", "kurgan-polyclinic-2"}]
    public_ids = {org.id for org in public_organizations}
    catalog = catalog.model_copy(update={
        "organizations": public_organizations,
        "branches": [branch for branch in catalog.branches if branch.id in {
            "kurgan-polyclinic-1-nevezhina-5", "kurgan-polyclinic-2-kravchenko-53",
        } and branch.organization_id in public_ids],
    })
    await import_catalog(db, catalog)
    await replace_addresses(db, address_rows(json.loads((CATALOG / "kurgan-osm-sample.json").read_bytes())))
    records = [
        {"kind": "organization", "external_id": "synthetic-org-1", "name": "Курганская поликлиника № 2",
         "specialties": ["Хирург"]},
        {"kind": "branch", "external_id": "synthetic-branch-1", "organization_external_id": "synthetic-org-1",
         "address": "г.Курган, ул. Кравченко, 53", "phones": ["+12025550109"], "specialties": ["Врач-невролог"]},
        {"kind": "organization", "external_id": "synthetic-org-2", "name": "Синтетический центр", "facility_kind": "private"},
        {"kind": "branch", "external_id": "synthetic-branch-2", "organization_external_id": "synthetic-org-2",
         "address": "Курган, ул. Коли Мяготина, 53", "phones": ["+12025550110"], "specialties": ["Дерматовенеролог"]},
        {"kind": "branch", "external_id": "synthetic-branch-3", "organization_external_id": "synthetic-org-2",
         "address": "Курган, ул. Коли Мяготина, 999", "phones": ["+12025550110"]},
    ]
    payload = {
        "schema_version": 1, "source": "poliklinika45", "complete": True,
        "retrieved_at": "2026-11-25T05:00:00Z", "start_url": PROFILES_URL,
        "pages": [{"url": PROFILES_URL, "records": [record | {"url": PROFILES_URL} for record in records]}],
    }
    snapshot = SourceSnapshot.model_validate(payload)
    first = await apply_snapshot(db, snapshot, snapshot.records())
    assert first["matched"] == first["created"] == 1
    assert first["needs_review"][0]["reason"] == "address_not_exact_or_ambiguous"
    assert first["conflicts"][0]["field"] == "phones"
    second = await apply_snapshot(db, snapshot, snapshot.records())
    assert second["matched"] == 2 and second["created"] == 0
    assert await db.scalar(select(func.count()).select_from(clinic_sources)) == 5
    assert await db.scalar(select(func.count()).select_from(branches)) == 3

    query = ClinicSearch(lat=55.44, lon=65.34, specialty_code="neurologist")
    result = await search_clinics(db, query, demo_mode=False)
    [item] = result.items
    assert item.id == "kurgan-polyclinic-2-kravchenko-53"
    assert item.phones == ["+73522241541"]
    assert item.payments == []
    assert item.sources[-1].name == "Поликлиника45"
    assert item.sources[-1].updated_at == snapshot.retrieved_at
    assert (await search_clinics(db, query.model_copy(update={"payment_method": "oms"}), demo_mode=False)).items == []
    assert (await search_clinics(db, query.model_copy(update={"specialty_code": "surgeon"}), demo_mode=False)).items == []

    changed = SourceSnapshot.model_validate(payload | {"retrieved_at": "2026-11-26T05:00:00Z"})
    changed.pages[0].records[1].address = "Курган, ул. Кравченко, 54"
    changed.pages[0].records[1].specialties = ["Педиатр"]
    third = await apply_snapshot(db, changed, changed.records())
    assert third["conflicts"][0]["field"] == "address"
    assert (await search_clinics(db, query, demo_mode=False)).items[0].sources[-1].updated_at == snapshot.retrieved_at
