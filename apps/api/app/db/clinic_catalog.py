from math import asin, cos, radians, sin, sqrt
from re import fullmatch, search
from urllib.parse import urlsplit

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, insert

from app.db.clinic_sources import (
    CATALOG_IMPORT_LOCK,
    POLIKLINIKA45,
    clinic_sources,
    oms_participants,
)
from app.db.models import Base
from app.schemas.clinics import (
    ClinicBranch,
    ClinicCatalog,
    ClinicPayment,
    ClinicSearch,
    ClinicSearchResponse,
    ClinicSourceInfo,
)

organizations = sa.Table(
    "clinic_organizations", Base.metadata,
    sa.Column("id", sa.String(80), primary_key=True),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("kind", sa.String(7), nullable=False),
    sa.CheckConstraint("kind IN ('public', 'private')", name="ck_clinic_organization_kind"),
)
branches = sa.Table(
    "clinic_branches", Base.metadata,
    sa.Column("id", sa.String(80), primary_key=True),
    sa.Column("organization_id", sa.String(80), sa.ForeignKey("clinic_organizations.id"), nullable=False),
    sa.Column("address", sa.Text, nullable=False),
    sa.Column("lat", sa.Float, nullable=False),
    sa.Column("lon", sa.Float, nullable=False),
    sa.Column("phones", JSONB, nullable=False),
    sa.Column("source", sa.Text, nullable=False),
    sa.Column("audience", sa.String(5)),
    sa.Column("website", sa.Text),
    sa.Column("booking_url", sa.Text),
    sa.Column("gosuslugi_confirmed", sa.Boolean, nullable=False),
    sa.Column("gosuslugi_direct_url", sa.Text),
    sa.Column("demo", sa.Boolean, nullable=False),
    sa.CheckConstraint("lat BETWEEN -90 AND 90 AND lon BETWEEN -180 AND 180", name="ck_clinic_branch_coordinates"),
    sa.CheckConstraint("audience IN ('child', 'adult', 'all')", name="ck_clinic_branch_audience"),
)
payments = sa.Table(
    "clinic_payments", Base.metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("branch_id", sa.String(80), sa.ForeignKey("clinic_branches.id", ondelete="CASCADE"), nullable=False),
    sa.Column("specialty_code", sa.String(80), nullable=False),
    sa.Column("method", sa.String(4), nullable=False),
    sa.Column("insurer", JSONB),
    sa.Column("program", sa.Text),
    sa.Column("source", sa.Text, nullable=False),
    sa.Column("checked_on", sa.Date, nullable=False),
    sa.Column("confirmed", sa.Boolean, nullable=False),
    sa.CheckConstraint("method IN ('oms', 'dms', 'paid')", name="ck_clinic_payment_method"),
    sa.Index("ix_clinic_payments_branch_id", "branch_id"),
)

GOSUSLUGI_BOOKING = "https://www.gosuslugi.ru/10700"


def child_specialty(code: str) -> bool:
    return code == "pediatrician" or code.startswith("pediatric_")


def portal_institution_page(value: str | None) -> str | None:
    if value:
        url = urlsplit(value)
        if (url.scheme == "https" and url.netloc in ("www.poliklinika45.ru", "poliklinika45.ru")
                and not url.query and not url.fragment and fullmatch(r"/service/hospitals/view/[0-9]+/?", url.path)):
            return value
    return None


async def import_catalog(db, catalog: ClinicCatalog):
    await db.execute(sa.select(sa.func.pg_advisory_xact_lock(CATALOG_IMPORT_LOCK)))
    for organization in sorted(catalog.organizations, key=lambda entry: entry.id):
        values = organization.model_dump()
        await db.execute(insert(organizations).values(**values).on_conflict_do_update(
            index_elements=[organizations.c.id], set_=values,
        ))
    for branch in sorted(catalog.branches, key=lambda entry: entry.id):
        values = branch.model_dump(exclude={"payments"}) | {"demo": catalog.demo}
        await db.execute(insert(branches).values(**values).on_conflict_do_update(
            index_elements=[branches.c.id], set_=values,
        ))
        await db.execute(payments.delete().where(payments.c.branch_id == branch.id))
        if branch.payments:
            await db.execute(payments.insert(), [
                payment.model_dump() | {"branch_id": branch.id} for payment in branch.payments
            ])


def distance_km(query: ClinicSearch, lat: float, lon: float) -> float:
    latitude, target_latitude = radians(query.lat), radians(lat)
    value = (sin((target_latitude - latitude) / 2) ** 2
             + cos(latitude) * cos(target_latitude) * sin(radians(lon - query.lon) / 2) ** 2)
    return 6371.0088 * 2 * asin(sqrt(min(1, max(0, value))))


def within_pilot(lat: float, lon: float) -> bool:
    # Approximate service area for GPS; explicit addresses are checked by locality.
    return 55.33 <= lat <= 55.56 and 65.12 <= lon <= 65.56


def rank_clinics(rows, query: ClinicSearch, source_rows=()) -> ClinicSearchResponse:
    nearby = {}
    insurers = {}
    sources_by_branch = {}
    portal_pages = {}
    oms_organizations = set()
    for source in source_rows:
        if source["branch_id"]:
            sources_by_branch.setdefault(source["branch_id"], []).append(source)
        elif (source["kind"] == "organization" and source["organization_id"]
              and (page := portal_institution_page(source["url"]))):
            portal_pages.setdefault(source["organization_id"], set()).add(page)
            if source.get("oms_evidence_url"):
                oms_organizations.add(source["organization_id"])
    for row in rows:
        identifier = row["id"]
        if identifier not in nearby:
            distance = distance_km(query, row["lat"], row["lon"])
            if distance > query.radius_km:
                continue
            nearby[identifier] = (row, distance, [])
        if row["method"]:
            nearby[identifier][2].append(ClinicPayment(
                method=row["method"], specialty_code=row["specialty_code"],
                insurer=row["insurer"], program=row["program"],
            ))

    items = []
    for branch, distance, offers in nearby.values():
        source_records = sources_by_branch.get(branch["id"], ())
        audience = branch.get("audience")
        if audience is None:
            names = [source["fields"].get("name", {}).get("value", "") for source in source_records]
            if search(r"\bдетск[а-яё]*\b", branch["name"].lower()) or (
                names and all(search(r"\bдетск[а-яё]*\b", name.lower()) for name in names)
            ):
                audience = "child"
        if audience == "child" and query.patient_group != "child":
            continue
        if query.patient_group == "child" and (audience == "adult" or (
            audience is None and branch["kind"] == "public"
        )):
            continue
        sourced_specialties = {code for source in source_records for code in source["specialty_codes"]}
        if query.patient_group == "adult":
            sourced_specialties = {code for code in sourced_specialties if not child_specialty(code)}
            offers = [offer for offer in offers if not child_specialty(offer.specialty_code)]
        specialty_offers = [offer for offer in offers
                            if not query.specialty_code or offer.specialty_code == query.specialty_code]
        if query.specialty_code and not specialty_offers and query.specialty_code not in sourced_specialties:
            continue
        matching = [offer for offer in specialty_offers if not query.payment_method or offer.method == query.payment_method]
        if query.payment_method == "dms":
            for offer in matching:
                if offer.insurer:
                    insurers[offer.insurer.id] = offer.insurer
        if query.insurer_id:
            matching = [offer for offer in matching if offer.insurer and offer.insurer.id == query.insurer_id]
        oms_needs_confirmation = (
            query.payment_method == "oms" and not matching and branch["kind"] == "public"
            and branch.get("organization_id") in oms_organizations
            and (query.specialty_code is None or query.specialty_code in sourced_specialties)
        )
        if query.payment_method and not matching and not oms_needs_confirmation:
            continue
        paid_only = any(offer.method == "paid" for offer in matching) and not any(
            offer.method == "oms" for offer in matching
        )
        phone_only = branch["kind"] == "private" or query.payment_method == "paid" or paid_only
        pages = portal_pages.get(branch.get("organization_id"), ())
        portal_page = None
        if not phone_only:
            portal_page = portal_institution_page(branch["booking_url"])
            if portal_page is None and len(pages) == 1:
                portal_page = next(iter(pages))
        direct = branch["gosuslugi_direct_url"] if branch["gosuslugi_confirmed"] else None
        gosuslugi_page = None
        if not phone_only and (branch["gosuslugi_confirmed"] or portal_page):
            gosuslugi_page = direct or GOSUSLUGI_BOOKING
        sources = [ClinicSourceInfo(name="Основной справочник", url=url.strip())
                   for url in branch.get("source", "").split(";") if url.strip().startswith("https://")]
        sources += [ClinicSourceInfo(name="Поликлиника45", url=source["url"], updated_at=source["retrieved_at"])
                    for source in source_records if source["source"] == POLIKLINIKA45]
        deduplicated = {source.url: source for source in sources}
        source_websites = (source["fields"].get("official_website", {}).get("value") for source in source_records)
        website = branch["website"] or next((url for url in source_websites if url
                                           and urlsplit(url).hostname not in ("poliklinika45.ru", "www.poliklinika45.ru")), None)
        items.append(ClinicBranch(
            **{key: branch[key] for key in ("id", "name", "address", "lat", "lon", "kind", "phones",
                                           "booking_url", "demo")},
            website=website, distance_km=distance, payments=matching, specialties=sorted(sourced_specialties),
            oms_needs_confirmation=oms_needs_confirmation,
            sources=list(deduplicated.values()),
            poliklinika45_url=portal_page,
            gosuslugi_url=gosuslugi_page,
            gosuslugi_select_branch=gosuslugi_page == GOSUSLUGI_BOOKING,
        ))
    items.sort(key=lambda item: (item.distance_km, item.id))
    return ClinicSearchResponse(items=items[:50], insurers=sorted(insurers.values(), key=lambda entry: (entry.name, entry.id)))


async def search_clinics(db, query: ClinicSearch, demo_mode: bool) -> ClinicSearchResponse:
    statement = sa.select(
        branches, organizations.c.name, organizations.c.kind,
        payments.c.method, payments.c.specialty_code, payments.c.insurer, payments.c.program,
    ).select_from(
        branches.join(organizations).outerjoin(payments, sa.and_(
            payments.c.branch_id == branches.c.id, payments.c.confirmed.is_(True),
        )),
    ).order_by(branches.c.id, payments.c.id)
    if not demo_mode:
        statement = statement.where(branches.c.demo.is_(False))
    rows = (await db.execute(statement)).mappings()
    sources = await db.execute(sa.select(
        clinic_sources, oms_participants.c.evidence_url.label("oms_evidence_url"),
    ).outerjoin(oms_participants, sa.and_(
        clinic_sources.c.kind == "organization",
        clinic_sources.c.external_id == oms_participants.c.poliklinika45_id,
    )).where(
        clinic_sources.c.source == POLIKLINIKA45,
        clinic_sources.c.verification_status == "verified",
    ).order_by(clinic_sources.c.external_id))
    return rank_clinics(rows, query, sources.mappings())
