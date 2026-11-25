import argparse
import asyncio
import json
import re
from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

import httpx
import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.clinic_addresses import address_query, addresses, normalize
from app.db.clinic_catalog import branches, organizations
from app.db.clinic_sources import CATALOG_IMPORT_LOCK, POLIKLINIKA45, clinic_sources
from app.db.engine import create_engine
from app.integrations.poliklinika45 import (
    Poliklinika45Adapter,
    SourceRecord,
    SourceSnapshot,
    SourceUnavailable,
)
from app.integrations.poliklinika45_html import specialty_code

SOURCE_FIELDS = ("name", "organization_name", "organization_external_id", "address", "phones",
                 "official_website", "facility_kind", "specialties", "schedule")



def organization_key(name: str | None) -> str:
    value = normalize(name or "")
    value = re.sub(r"^(?:гбу|гау|чуз|ооо|ао|государственн(?:ое|ой) бюджетное учреждение)\s+", "", value)
    return " ".join(re.findall(r"[а-яa-z0-9]+", value))


def normalized_address(value: str | None):
    try:
        identity = address_query(value or "")
    except ValueError:
        return None
    return identity if identity[0] and identity[1] else None


def same_address(one, two) -> bool:
    return bool(one and two and one[:2] == two[:2] and (not one[2] or not two[2] or one[2] == two[2]))


async def exact_point(db, address):
    street, house, kind = address
    query = sa.select(addresses.c.lat, addresses.c.lon, addresses.c.street_type).where(
        addresses.c.street_key == street, addresses.c.house_key == house,
    ).order_by(addresses.c.osm_id)
    if kind:
        query = query.where(addresses.c.street_type.in_((kind, "")))
    points = (await db.execute(query)).all()
    if not points:
        return None
    point = points[0]
    if any(abs(other.lat - point.lat) > 0.0005 or abs(other.lon - point.lon) > 0.0007 for other in points):
        return None
    if len({other.street_type for other in points if other.street_type}) > 1:
        return None
    return {"lat": point.lat, "lon": point.lon}


def stable_id(prefix: str, identifier: str) -> str:
    return prefix + sha256(identifier.encode()).hexdigest()[:24]


def verified_website(record: SourceRecord) -> str | None:
    url = record.official_website
    if url and (urlsplit(url).hostname or "").removeprefix("www.") != "poliklinika45.ru":
        return url
    return None


async def apply_snapshot(db, snapshot: SourceSnapshot, records: list[SourceRecord]) -> dict:
    if not await db.scalar(sa.select(sa.func.pg_try_advisory_xact_lock(CATALOG_IMPORT_LOCK))):
        raise SourceUnavailable("Another clinic catalog import is running")
    prior = (await db.execute(sa.select(clinic_sources).where(clinic_sources.c.source == POLIKLINIKA45))).mappings().all()
    previous = {f"{row['kind']}:{row['external_id']}": row for row in prior}
    if any(row["retrieved_at"] > snapshot.retrieved_at for row in prior):
        raise SourceUnavailable("The snapshot is older than the last import")
    existing = (await db.execute(sa.select(branches, organizations.c.name).select_from(
        branches.join(organizations),
    ).where(branches.c.demo.is_(False)))).mappings().all()
    branch_by_id = {branch["id"]: branch for branch in existing}
    by_address = [(branch, normalized_address(branch["address"])) for branch in existing]
    external_organizations = defaultdict(set)
    for row in prior:
        if row["kind"] == "organization" and row["organization_id"]:
            external_organizations[row["external_id"]].add(row["organization_id"])
    organization_records = {record.external_id: record for record in records if record.kind == "organization"}
    report = {
        "source": POLIKLINIKA45, "retrieved_at": snapshot.retrieved_at.isoformat(),
        "organizations": len(organization_records), "branches": len(records) - len(organization_records),
        "matched": 0, "created": 0, "needs_review": [], "conflicts": [], "fields": {},
        "empty_profiles": snapshot.empty_profiles,
    }
    coverage = Counter()
    seen_branches = {}

    async def save(record, old, organization_id=None, branch_id=None):
        fields = dict(old["fields"]) if old else {}
        data = record.model_dump(mode="json")
        for field in SOURCE_FIELDS:
            if data[field]:
                coverage[field] += 1
                if field == "schedule" and old and old["schedule_as_of"] and record.schedule_as_of < old["schedule_as_of"]:
                    report["conflicts"].append({"external_id": record.key, "field": "schedule", "reason": "older_schedule"})
                    continue
                fields[field] = {"value": data[field], "url": record.field_urls.get(field, record.url),
                                 "retrieved_at": snapshot.retrieved_at.isoformat()}
                if field == "specialties" and record.specialty_urls:
                    fields[field]["evidence"] = record.specialty_urls
        codes = {code for label in record.specialties if (code := specialty_code(label))}
        unknown = sorted({label for label in record.specialties if not specialty_code(label)})
        if unknown:
            report["needs_review"].append({"external_id": record.key, "unmapped_specialties": unknown})
        prior_codes = set(old["specialty_codes"]) if old else set()
        if record.specialties and prior_codes - codes:
            report["conflicts"].append({"external_id": record.key, "field": "specialties",
                                        "previous": sorted(prior_codes), "reported": sorted(codes)})
        schedule_date = max(filter(None, (record.schedule_as_of, old["schedule_as_of"] if old else None)), default=None)
        values = {"source": POLIKLINIKA45, "external_id": record.external_id, "kind": record.kind, "url": record.url,
                      "retrieved_at": snapshot.retrieved_at, "verification_status": "verified" if organization_id else "needs_review",
                      "organization_id": organization_id, "branch_id": branch_id, "fields": fields,
                      "specialty_codes": sorted(codes | prior_codes), "schedule_as_of": schedule_date}
        await db.execute(insert(clinic_sources).values(**values).on_conflict_do_update(
            index_elements=[clinic_sources.c.source, clinic_sources.c.external_id, clinic_sources.c.kind], set_=values,
        ))

    for record in records:
        if record.kind != "branch":
            continue
        old = previous.get(record.key)
        linked = branch_by_id.get(old["branch_id"]) if old else None
        identity = normalized_address(record.address)
        org_record = organization_records.get(record.organization_external_id)
        org_name = record.organization_name or (org_record.name if org_record else None)
        org_keys = {organization_key(org_name), organization_key(org_record.name if org_record else None)} - {""}
        linked_orgs = external_organizations.get(record.organization_external_id, set())
        at_address = [branch for branch, address in by_address if same_address(address, identity)]
        matches = [branch for branch in at_address if (
            branch["organization_id"] in linked_orgs
            or organization_key(branch["name"]) in org_keys
        )]
        prior_org = old["fields"].get("organization_external_id", {}).get("value") if old else None
        if linked and prior_org and record.organization_external_id and prior_org != record.organization_external_id:
            report["conflicts"].append({"external_id": record.key, "field": "organization_external_id",
                                        "existing": prior_org, "reported": record.organization_external_id})
            continue
        if linked and record.address and not same_address(identity, normalized_address(linked["address"])):
            report["conflicts"].append({"external_id": record.key, "field": "address",
                                        "existing": linked["address"], "reported": record.address})
            continue
        branch = linked or (matches[0] if len(matches) == 1 else None)
        if not branch:
            facility_kind = record.facility_kind or (org_record.facility_kind if org_record else None)
            reason = None
            coordinates = None
            required = {"address": identity, "organization_name": org_name,
                        "organization_external_id": record.organization_external_id,
                        "phones": record.phones, "facility_kind": facility_kind}
            missing = [name for name, value in required.items() if not value]
            if at_address or len(linked_orgs) > 1:
                reason = "ambiguous_catalog_match"
            elif missing:
                reason = "incomplete_branch"
            else:
                coordinates = await exact_point(db, identity)
                if not coordinates:
                    reason = "address_not_exact_or_ambiguous"
            if reason:
                issue = {"external_id": record.key, "reason": reason, "address": record.address}
                if missing:
                    issue["missing_fields"] = missing
                report["needs_review"].append(issue)
                await save(record, old)
                continue
            org_id = next(iter(linked_orgs), stable_id("p45-org-", record.organization_external_id))
            await db.execute(insert(organizations).values(id=org_id, name=org_name, kind=facility_kind).on_conflict_do_nothing())
            branch = dict(id=stable_id("p45-branch-", record.external_id), organization_id=org_id,
                          address=record.address, phones=record.phones, source=record.url, website=verified_website(record),
                          booking_url=None, gosuslugi_confirmed=False, gosuslugi_direct_url=None, demo=False, **coordinates)
            await db.execute(insert(branches).values(**branch).on_conflict_do_nothing())
            branch["name"] = org_name
            by_address.append((branch, identity))
            report["created"] += 1
        else:
            report["matched"] += 1
            if record.phones and set(record.phones) != set(branch["phones"]):
                report["conflicts"].append({"external_id": record.key, "field": "phones",
                                            "existing": branch["phones"], "reported": record.phones})
            if branch["website"] and (website := verified_website(record)) and website != branch["website"]:
                report["conflicts"].append({"external_id": record.key, "field": "official_website",
                                            "existing": branch["website"], "reported": website})
        if branch["id"] in seen_branches:
            report["needs_review"].append({"external_id": record.key, "reason": "multiple_external_ids",
                                           "other": seen_branches[branch["id"]]})
        seen_branches[branch["id"]] = record.key
        await save(record, old, branch["organization_id"], branch["id"])
        if record.organization_external_id:
            external_organizations[record.organization_external_id].add(branch["organization_id"])

    for record in organization_records.values():
        linked = external_organizations[record.external_id]
        if len(linked) != 1:
            report["needs_review"].append({"external_id": record.key, "reason": "organization_unmatched_or_ambiguous"})
        await save(record, previous.get(record.key), next(iter(linked)) if len(linked) == 1 else None)
    report["fields"] = dict(coverage)
    return report


async def run(snapshot_path: Path | None, snapshot_out: Path | None = None, collect_only: bool = False) -> dict:
    if snapshot_path is None:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12, connect=6)) as client:
            collected = await Poliklinika45Adapter(client).collect()
        with TemporaryDirectory() as directory:
            saved = snapshot_out or Path(directory) / "poliklinika45.json"
            saved.write_text(collected.model_dump_json(indent=2) + "\n", encoding="utf-8")
            if collect_only:
                records = SourceSnapshot.model_validate_json(saved.read_bytes()).records()
                return {"source": POLIKLINIKA45, "retrieved_at": collected.retrieved_at.isoformat(),
                        "organizations": sum(record.kind == "organization" for record in records),
                        "branches": sum(record.kind == "branch" for record in records), "empty_profiles": collected.empty_profiles}
            return await run(saved)
    snapshot = SourceSnapshot.model_validate_json(snapshot_path.read_bytes())
    records = snapshot.records()
    engine = create_engine()
    try:
        async with async_sessionmaker(engine).begin() as db:
            return await apply_snapshot(db, snapshot, records)
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="Import public Poliklinika45 directory data")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--snapshot", type=Path)
    mode.add_argument("--live", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--snapshot-out", type=Path)
    parser.add_argument("--collect-only", action="store_true")
    args = parser.parse_args()
    if (args.snapshot_out and not args.live) or (args.collect_only and not args.snapshot_out):
        parser.error("--snapshot-out requires --live; --collect-only also requires --snapshot-out")
    try:
        report = asyncio.run(run(args.snapshot, args.snapshot_out, args.collect_only)) | {
            "status": "collected" if args.collect_only else "applied",
        }
    except (ValueError, OSError, SQLAlchemyError) as exc:
        reason = str(exc) if isinstance(exc, SourceUnavailable) else (
            "Invalid public data or saved snapshot" if isinstance(exc, (ValidationError, ValueError)) else type(exc).__name__
        )
        report = {"status": "aborted", "source": POLIKLINIKA45, "reason": reason}
    result = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.write_text(result + "\n", encoding="utf-8")
    print(result)
    return 1 if report["status"] == "aborted" else 0


if __name__ == "__main__":
    raise SystemExit(main())
