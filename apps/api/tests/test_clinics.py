from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.clinic_addresses import address_query
from app.db.clinic_catalog import rank_clinics
from app.db.import_clinic_addresses import address_rows
from app.main import create_app
from app.schemas.clinics import ClinicSearch
from app.services.sessions import SessionService


def row(branch_id, lat=55.45, *, specialty="therapist", method="oms", insurer=None, confirmed=False):
    return {
        "id": branch_id, "name": branch_id, "kind": "public", "address": "Курган", "phones": ["+12025550101"],
        "lat": lat, "lon": 65.34, "website": None, "booking_url": None, "demo": False, "gosuslugi_confirmed": confirmed,
        "gosuslugi_direct_url": None, "specialty_code": specialty, "method": method, "insurer": insurer, "program": None,
    }


def test_search_uses_the_same_branch_offer_and_sorts_by_distance_then_id():
    rows = [
        row("b"), row("paid-elsewhere", specialty="dermatologist", method="paid"),
        row("paid-elsewhere"), row("a"), row("c", 55.46), row("d", 55.53),
    ]
    query = ClinicSearch(lat=55.45, lon=65.34, specialty_code="therapist", payment_method="oms")
    assert [branch.id for branch in rank_clinics(rows, query).items] == ["a", "b", "paid-elsewhere", "c"]
    assert rank_clinics(rows, query.model_copy(update={"payment_method": "paid"})).items == []
    assert len(rank_clinics([row(f"a{i}") for i in range(80)], query).items) == 50


def test_oms_search_filters_age_before_ranking_branch_distances():
    rows = [
        row("adult-nearer", 55.4501, specialty="gynecologist") | {"audience": "adult"},
        row("child-farther", 55.457, specialty="gynecologist") | {"audience": "child"},
        row("child-nearer", 55.452, specialty="gynecologist") | {"name": "Курганская детская поликлиника"},
        row("unclassified", 55.4502, specialty="gynecologist"),
        row("all-ages", 55.454, specialty="gynecologist") | {"audience": "all"},
        row("paid", 55.45, specialty="gynecologist", method="paid") | {"audience": "all"},
    ]
    query = ClinicSearch(lat=55.45, lon=65.34, specialty_code="gynecologist", payment_method="oms")
    children = rank_clinics(rows, query.model_copy(update={"patient_group": "child"})).items
    assert [branch.id for branch in children] == ["child-nearer", "all-ages", "child-farther"]
    adults = rank_clinics(rows, query.model_copy(update={"patient_group": "adult"})).items
    assert [branch.id for branch in adults] == ["adult-nearer", "unclassified", "all-ages"]
    assert [branch.id for branch in rank_clinics(rows, query).items] == [branch.id for branch in adults]


def test_dms_offer_can_lack_a_program_and_unverified_booking_is_omitted():
    insurer = {"id": "example", "name": "Тестовая страховая"}
    rows = [row("a", method="dms"), row("b", method="dms", insurer=insurer, confirmed=True)]
    query = ClinicSearch(lat=55.45, lon=65.34, payment_method="dms")
    result = rank_clinics(rows, query)
    assert [entry.model_dump() for entry in result.insurers] == [insurer]
    assert result.items[0].payments[0].program is None
    assert result.items[0].gosuslugi_url is None
    assert result.items[1].gosuslugi_url == "https://www.gosuslugi.ru/10700"
    assert result.items[1].gosuslugi_select_branch
    assert [item.id for item in rank_clinics(rows, query.model_copy(update={"insurer_id": "example"})).items] == ["b"]


def test_booking_links_use_the_mapped_institution_page_and_are_hidden_for_paid_visits():
    portal = {"kind": "organization", "branch_id": None, "organization_id": "org",
              "url": "https://www.poliklinika45.ru/service/hospitals/view/1143538"}
    listing = portal | {"url": "https://www.poliklinika45.ru/service/schedule/profiles"}
    public = row("a") | {"organization_id": "org"}
    private = row("b") | {"organization_id": "org", "kind": "private"}
    query = ClinicSearch(lat=55.45, lon=65.34)
    first, second = rank_clinics([public, private], query, [portal, listing]).items
    assert first.poliklinika45_url == portal["url"]
    assert first.gosuslugi_url == "https://www.gosuslugi.ru/10700"
    assert first.gosuslugi_select_branch
    assert second.poliklinika45_url is second.gosuslugi_url is None
    [paid] = rank_clinics([public | {"method": "paid"}], query.model_copy(update={"payment_method": "paid"}), [portal]).items
    assert paid.poliklinika45_url is paid.gosuslugi_url is None
    assert not paid.gosuslugi_select_branch
    [unfiltered_paid] = rank_clinics([public | {"method": "paid"}], query, [portal]).items
    assert unfiltered_paid.poliklinika45_url is unfiltered_paid.gosuslugi_url is None
    direct = public | {"gosuslugi_confirmed": True, "gosuslugi_direct_url": "https://www.gosuslugi.ru/example"}
    [confirmed] = rank_clinics([direct], query, [portal]).items
    assert confirmed.gosuslugi_url == direct["gosuslugi_direct_url"]
    assert not confirmed.gosuslugi_select_branch


@pytest.mark.parametrize(("address", "expected"), [
    ("г.Курган, УЛ. Тимофея Невёжина, д. 5, корп. 1", ("тимофея невежина", "5к1", "улица")),
    ("Кравченко, 53", ("кравченко", "53", "")),
    ("Курган бул. Солнечный дом 9 строение 3", ("солнечный", "9с3", "бульвар")),
    ("1-й мкр-н 39", ("1-й микрорайон", "39", "")),
])
def test_address_normalization(address, expected):
    assert address_query(address) == expected


@pytest.mark.parametrize("address", ["Екатеринбург, ул. Ленина, 1", "Тюмень, Ленина 5", "г.Шадринск"])
def test_explicit_foreign_city_is_rejected(address):
    with pytest.raises(ValueError, match="clinic_outside_pilot"):
        address_query(address)


def test_osm_import_handles_nodes_and_building_geometry():
    tags = {"addr:street": "ул. Гоголя", "addr:housenumber": "5", "building": "yes"}
    points = [(55.44, 65.34), (55.44, 65.35), (55.45, 65.35), (55.45, 65.34), (55.44, 65.34)]
    node = {"type": "node", "id": 14, "lat": 55.445, "lon": 65.34, "tags": tags}
    imported = address_rows({"elements": [
        node,
        node | {"id": 15, "tags": tags | {"addr:city": "Шадринск"}},
        {"type": "way", "id": 14, "tags": tags, "geometry": [{"lat": lat, "lon": lon} for lat, lon in points]},
    ]})
    assert [item["osm_id"] for item in imported] == ["node/14", "way/14"]
    assert imported[1]["lat"] == pytest.approx(55.445)
    assert imported[1]["lon"] == pytest.approx(65.345)
    assert imported[1]["label"] == "Курган, ул. Гоголя, 5"


def test_clinic_routes_require_auth_validate_input_and_report_storage_errors():
    settings = replace(Settings(), demo_mode=True, session_signing_key="t" * 48)
    app = create_app(settings, session_service=SessionService(settings.survey_ttl_seconds))
    with TestClient(app, base_url="https://testserver") as client:
        assert client.post("/api/v1/clinics/geocode", json={"address": "Гоголя"}).status_code == 401
        assert client.post("/api/v1/clinics/search", json={"lat": 55.45, "lon": 65.34}).status_code == 401
        token = client.post("/api/v1/auth/launch", json={"mode": "demo"}).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert client.post("/api/v1/clinics/geocode", headers=headers, json={"address": "Гоголя"}).json() == {
            "detail": "clinic_addresses_unavailable",
        }
        assert client.post("/api/v1/clinics/search", headers=headers, json={"lat": 100, "lon": 65}).status_code == 422
        assert client.post("/api/v1/clinics/search", headers=headers, json={"lat": 55, "lon": 73}).json() == {
            "detail": "clinic_outside_pilot",
        }
