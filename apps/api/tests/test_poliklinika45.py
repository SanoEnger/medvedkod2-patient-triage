from datetime import date, time
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.db import import_poliklinika45
from app.integrations.poliklinika45 import (
    ORIGIN,
    PROFILES_URL,
    Poliklinika45Adapter,
    SourceSnapshot,
    SourceUnavailable,
)
from app.integrations.poliklinika45_html import (
    doctor_groups,
    organization_details,
    published_schedule,
)

MAINTENANCE = Path(__file__).parent / "fixtures/poliklinika45_maintenance.txt"


def test_parses_observed_doctor_pagination_and_keeps_missing_department_address_unresolved():
    source = MAINTENANCE.with_name("poliklinika45_doctors_excerpt.html").read_text(encoding="utf-8")
    url = ORIGIN + "/service/schedule/0/450101000000028/doctors?terr_id=450101000000025"
    groups, next_url = doctor_groups(source, url, 1)
    assert next_url.endswith("per_page=20&page=2&terr_id=450101000000025")
    assert groups[0]["organization_id"] == "1155017"
    assert groups[0]["unit_id"] == "450101000004114"
    assert groups[0]["specialties"] == ["Терапевт"]
    assert groups[0]["address"] == "Курган, ДЗЕРЖИНСКОГО, 41, корп. б"
    assert groups[1]["address"] is None
    with pytest.raises(ValueError, match="page number"):
        doctor_groups(source, next_url, 2)


def test_organization_contacts_keep_department_phones_separate():
    source = MAINTENANCE.with_name("poliklinika45_org_excerpt.html").read_text(encoding="utf-8")
    url = ORIGIN + "/service/hospitals/view/1155017"
    organization, divisions = organization_details(source, url, "1155017")
    assert organization["phones"] == ["+73522470910"]
    assert organization["official_website"] is None
    assert divisions["отделение медицинской профилактики (невежина)"] == [
        ("Курган, ТИМОФЕЯ НЕВЕЖИНА УЛ, д. 5", ["+73522443205"]),
    ]
    assert "терапевтический кабинет" not in divisions


def test_schedule_uses_dated_public_times_without_slot_status():
    times = '<table class="timeTable"><tr><td class="busy" rel="27 ноября, пятница 09:00"></td></tr>'
    times += '<tr><td class="free" rel="27 ноября, пятница 12:00"></td></tr></table>'
    assert published_schedule(times, date(2026, 11, 25), "Терапевт") == [
        {"specialty": "Терапевт", "date": date(2026, 11, 27), "starts_at": time(9), "ends_at": time(12)},
    ]


@pytest.fixture
def portal_snapshot_data():
    return {
        "schema_version": 1, "source": "poliklinika45", "complete": True,
        "retrieved_at": "2026-11-25T05:00:00Z", "start_url": PROFILES_URL,
        "pages": [
            {"url": PROFILES_URL, "next_url": PROFILES_URL + "?page=2", "records": [
                {"kind": "organization", "external_id": "synthetic-org-1", "url": PROFILES_URL,
                 "name": "ГБУ «Курганская поликлиника № 2»", "facility_kind": "public", "specialties": ["Хирург"]},
                {"kind": "branch", "external_id": "synthetic-branch-1", "url": PROFILES_URL,
                 "organization_external_id": "synthetic-org-1", "address": "Курган, ул. Кравченко, 53",
                 "phones": ["+12025550109"], "specialties": ["Врач-невролог", "Условный профиль"]},
            ]},
            {"url": PROFILES_URL + "?page=2", "records": [
                {"kind": "organization", "external_id": "synthetic-org-2", "url": PROFILES_URL,
                 "name": "Синтетический медицинский центр", "facility_kind": "private"},
                {"kind": "branch", "external_id": "synthetic-branch-2", "url": PROFILES_URL + "?page=2",
                 "organization_external_id": "synthetic-org-2", "address": "Курган, ул. Коли Мяготина, 53",
                 "phones": ["+12025550110"], "specialties": ["Дерматовенеролог"]},
                {"kind": "branch", "external_id": "synthetic-branch-3", "url": PROFILES_URL + "?page=2",
                 "organization_external_id": "synthetic-org-2", "address": "Курган, ул. Коли Мяготина, 999",
                 "phones": ["+12025550110"]},
            ]},
        ],
    }


def test_snapshot_follows_pagination_and_permits_missing_optional_fields(portal_snapshot_data):
    snapshot = SourceSnapshot.model_validate(portal_snapshot_data)
    records = snapshot.records()
    assert [record.external_id for record in records if record.kind == "branch"] == [
        "synthetic-branch-1", "synthetic-branch-2", "synthetic-branch-3",
    ]
    assert records[-1].official_website is None
    assert records[-1].specialties == []
    assert import_poliklinika45.specialty_code("Врач-невролог") == "neurologist"
    snapshot.pages.pop()
    with pytest.raises(SourceUnavailable, match="pagination"):
        snapshot.records()


def test_snapshot_rejects_partial_and_schedule_without_date(portal_snapshot_data):
    with pytest.raises(ValidationError):
        SourceSnapshot.model_validate(portal_snapshot_data | {"complete": False})
    portal_snapshot_data["pages"][0]["records"][1]["schedule"] = [
        {"specialty": "Терапевт", "date": "2026-11-27", "starts_at": "08:00", "ends_at": "12:00"},
    ]
    with pytest.raises(ValidationError, match="as-of date"):
        SourceSnapshot.model_validate(portal_snapshot_data)


@pytest.mark.asyncio
async def test_live_maintenance_or_denial_never_open_database(monkeypatch):
    requests = []

    def handle(request):
        requests.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /", headers={"content-type": "text/plain"})
        return httpx.Response(200, text=MAINTENANCE.read_text(encoding="utf-8"))

    original_client = httpx.AsyncClient
    monkeypatch.setattr(import_poliklinika45.httpx, "AsyncClient", lambda **kwargs:
                        original_client(transport=httpx.MockTransport(handle), **kwargs))
    monkeypatch.setattr(import_poliklinika45, "create_engine", lambda: pytest.fail("Database opened during failed collection"))
    with pytest.raises(SourceUnavailable, match="maintenance"):
        await import_poliklinika45.run(None)
    assert requests == [ORIGIN + "/robots.txt", PROFILES_URL]


@pytest.mark.asyncio
@pytest.mark.parametrize("robots", [
    httpx.Response(403),
    httpx.Response(200, text="User-agent: *\nDisallow: /service/", headers={"content-type": "text/plain"}),
])
async def test_adapter_honors_robots_and_does_not_retry_forbidden(robots):
    paths = []

    def handle(request):
        paths.append(request.url.path)
        return robots

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(SourceUnavailable, match="denied|disallows"):
            await Poliklinika45Adapter(client).collect()
    assert paths == ["/robots.txt"]
