import asyncio
from datetime import UTC, date, datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
from time import monotonic
from typing import Annotated, Literal
from urllib.parse import parse_qs, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.db.clinic_addresses import address_query
from app.integrations.poliklinika45_html import (
    doctor_groups,
    organization_details,
    profiles,
    published_schedule,
    specialty_code,
)
from app.schemas.clinics import Phone, https_url

ORIGIN = "https://www.poliklinika45.ru"
PROFILES_URL = ORIGIN + "/service/schedule/profiles"
USER_AGENT = "MedVed-ClinicDirectory/1.0"
KURGAN_TIME = timezone(timedelta(hours=5))
PILOT_PROFILES = {"therapist", "pediatrician", "dermatologist", "cardiologist", "neurologist",
                  "otolaryngologist", "ophthalmologist", "gynecologist", "surgeon", "general_practitioner"}
ExternalId = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_-]{1,140}$")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
FieldName = Literal["name", "organization_name", "address", "phones", "official_website", "facility_kind",
                    "specialties", "schedule"]


class SourceUnavailable(ValueError):
    pass


def portal_url(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or parsed.netloc not in ("www.poliklinika45.ru", "poliklinika45.ru")
            or parsed.fragment or any(name.lower() in {"token", "auth", "session", "password"} for name in parse_qs(parsed.query))):
        raise ValueError("Expected a public Poliklinika45 URL")
    return value


class SnapshotModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PublishedSchedule(SnapshotModel):
    specialty: Name
    date: date
    starts_at: time
    ends_at: time

    @model_validator(mode="after")
    def ordered_times(self):
        if self.starts_at.tzinfo or self.ends_at.tzinfo or self.starts_at >= self.ends_at:
            raise ValueError("Expected ordered local schedule times")
        return self


class SourceRecord(SnapshotModel):
    external_id: ExternalId
    kind: Literal["organization", "branch"]
    url: str
    name: Name | None = None
    organization_external_id: ExternalId | None = None
    organization_name: Name | None = None
    address: Name | None = None
    phones: list[Phone] = Field(default_factory=list, max_length=20)
    official_website: str | None = None
    facility_kind: Literal["public", "private"] | None = None
    specialties: list[Name] = Field(default_factory=list, max_length=100)
    schedule: list[PublishedSchedule] = Field(default_factory=list, max_length=1000)
    schedule_as_of: date | None = None
    field_urls: dict[FieldName, str] = Field(default_factory=dict)
    specialty_urls: dict[Name, str] = Field(default_factory=dict)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value):
        return portal_url(value)

    @field_validator("official_website")
    @classmethod
    def validate_website(cls, value):
        return https_url(value)

    @model_validator(mode="after")
    def validate_evidence(self):
        for url in [*self.field_urls.values(), *self.specialty_urls.values()]:
            portal_url(url)
        if self.schedule and not self.schedule_as_of:
            raise ValueError("Published schedule needs an as-of date")
        return self

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.external_id}"


class SourcePage(SnapshotModel):
    url: str
    next_url: str | None = None
    records: list[SourceRecord] = Field(min_length=1)

    @field_validator("url", "next_url")
    @classmethod
    def validate_url(cls, value):
        return portal_url(value) if value else value


class SourceSnapshot(SnapshotModel):
    schema_version: Literal[1]
    source: Literal["poliklinika45"]
    complete: Literal[True]
    retrieved_at: AwareDatetime
    start_url: str
    pages: list[SourcePage] = Field(min_length=1, max_length=1000)
    empty_profiles: list[Name] = Field(default_factory=list)

    @field_validator("start_url")
    @classmethod
    def validate_start(cls, value):
        return portal_url(value)

    def records(self) -> list[SourceRecord]:
        pages = {page.url: page for page in self.pages}
        records = {}
        visited = set()
        url: str | None = portal_url(self.start_url)
        while url is not None:
            if url in visited or url not in pages:
                raise SourceUnavailable("Incomplete or cyclic pagination")
            visited.add(url)
            page = pages[url]
            for record in page.records:
                if record.key in records and records[record.key] != record:
                    raise SourceUnavailable(f"Conflicting duplicate source record {record.key}")
                records[record.key] = record
            url = page.next_url
        if len(visited) != len(self.pages) or not any(record.kind == "branch" for record in records.values()):
            raise SourceUnavailable("Incomplete or empty branch snapshot")
        return list(records.values())


def check_public_response(response: httpx.Response):
    text = response.text.casefold()
    if response.status_code in (401, 403) or any(marker in text for marker in ("captcha", "капча", "подтвердите, что вы не робот")):
        raise SourceUnavailable(f"Public access denied or CAPTCHA (HTTP {response.status_code})")
    if any(marker in text for marker in ("проведением технических работ", "сервис временно недоступен")):
        raise SourceUnavailable("Poliklinika45 is serving a maintenance page")
    if response.is_error:
        raise SourceUnavailable(f"Poliklinika45 returned HTTP {response.status_code}")


def retry_seconds(value: str | None) -> float:
    if value:
        try:
            return max(1, int(value))
        except ValueError:
            try:
                return max(1, (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())
            except (TypeError, ValueError):
                pass
    return 1


class Poliklinika45Adapter:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self.last_request: float | None = None
        self.pause = 1.0
        self.policy: RobotFileParser | None = None

    async def get(self, url: str) -> httpx.Response:
        portal_url(url)
        for attempt in range(3):
            if self.policy and not self.policy.can_fetch(USER_AGENT, url):
                raise SourceUnavailable("robots.txt disallows a public catalog page")
            if self.last_request is not None:
                await asyncio.sleep(max(0, self.last_request + self.pause - monotonic()))
            self.last_request = monotonic()
            try:
                response = await self.client.get(url, headers={"User-Agent": USER_AGENT}, follow_redirects=False)
            except httpx.RequestError:
                if attempt == 2:
                    raise SourceUnavailable("Poliklinika45 could not be reached") from None
                continue
            if response.is_redirect:
                location = response.headers.get("location")
                if not location or attempt == 2:
                    raise SourceUnavailable("Unexpected Poliklinika45 redirect")
                try:
                    url = portal_url(urljoin(url, location))
                except ValueError:
                    raise SourceUnavailable("Unexpected redirect outside Poliklinika45") from None
                continue
            if response.status_code in (429, 502, 503, 504) and attempt < 2:
                delay = retry_seconds(response.headers.get("retry-after"))
                if delay > 60:
                    raise SourceUnavailable("Poliklinika45 asked to retry later")
                await asyncio.sleep(delay)
                continue
            return response
        raise SourceUnavailable("Poliklinika45 could not be reached")

    async def collect(self) -> SourceSnapshot:
        robots_url = ORIGIN + "/robots.txt"
        robots = await self.get(robots_url)
        if robots.status_code != 404:
            check_public_response(robots)
            if "text/plain" not in robots.headers.get("content-type", ""):
                raise SourceUnavailable("Unexpected robots.txt response")
            policy = RobotFileParser(robots_url)
            policy.parse(robots.text.splitlines())
            if not policy.can_fetch(USER_AGENT, PROFILES_URL):
                raise SourceUnavailable("robots.txt disallows the public schedule")
            self.policy = policy
            self.pause = max(self.pause, policy.crawl_delay(USER_AGENT) or 0)
            rate = policy.request_rate(USER_AGENT)
            if rate and rate.requests:
                self.pause = max(self.pause, rate.seconds / rate.requests)
        async def html(url):
            response = await self.get(url)
            check_public_response(response)
            if "text/html" not in response.headers.get("content-type", ""):
                raise SourceUnavailable("Unexpected public HTML response")
            return response.text

        listed = [(label, url) for label, url in profiles(await html(PROFILES_URL), PROFILES_URL) if specialty_code(label)]
        if not PILOT_PROFILES.issubset({specialty_code(label) for label, _ in listed}):
            raise SourceUnavailable("Incomplete public specialty directory")
        organizations = {}
        branches = {}
        departments = {}
        timetable_sources = {}
        empty_profiles = []
        for label, first_page in listed:
            url = first_page
            visited = set()
            found = False
            while url:
                if url in visited or len(visited) >= 35:
                    raise SourceUnavailable("Incomplete or cyclic public doctor pagination")
                visited.add(url)
                try:
                    rows, next_url = doctor_groups(await html(url), url, len(visited))
                except ValueError as exc:
                    if isinstance(exc, SourceUnavailable):
                        raise
                    raise SourceUnavailable(f"{exc}: {url}") from None
                for row in rows:
                    matches = {name for name in row["specialties"] if specialty_code(name) == specialty_code(label)}
                    if not matches:
                        continue
                    found = True
                    org_id = row["organization_id"]
                    if org_id not in organizations:
                        org_url = row["organization_url"]
                        try:
                            organizations[org_id], departments[org_id] = organization_details(await html(org_url), org_url, org_id)
                        except ValueError as exc:
                            if isinstance(exc, SourceUnavailable):
                                raise
                            raise SourceUnavailable(f"{exc}: {org_url}") from None
                    record = organizations[org_id]
                    if address := row["address"]:
                        unit = row["unit_id"]
                        record = branches.setdefault(unit, {
                            "kind": "branch", "external_id": unit, "url": url, "name": row["name"], "address": address,
                            "organization_external_id": org_id, "organization_name": row["organization_name"],
                            "field_urls": {"name": url, "address": url},
                        })
                        if record["organization_external_id"] != org_id or address_query(record["address"]) != address_query(address):
                            raise SourceUnavailable(f"Inconsistent department {unit}")
                        if row["contact"] and address_query(row["contact"][0]) == address_query(address):
                            record["phones"] = sorted(set(record.get("phones", ())) | set(row["contact"][1]))
                            record["field_urls"]["phones"] = url
                        if row["timetable_url"]:
                            timetable_sources.setdefault(unit, (row["timetable_url"], label))
                    evidence = record.setdefault("specialty_urls", {})
                    for name in sorted(matches):
                        evidence.setdefault(name, url)
                url = next_url
            if not found:
                empty_profiles.append(label)

        as_of = datetime.now(KURGAN_TIME).date()
        for unit, record in branches.items():
            organization = organizations[record["organization_external_id"]]
            entries = departments[record["organization_external_id"]].get(record["name"].casefold(), [])
            confirmed = {phone for address, phones in entries if address_query(address) == address_query(record["address"])
                         for phone in phones}
            if confirmed and not record.get("phones"):
                record["phones"] = sorted(confirmed)
                record["field_urls"]["phones"] = organization["url"]
            if organization.get("official_website"):
                record["official_website"] = organization["official_website"]
                record["field_urls"]["official_website"] = organization["url"]
        # A small dated sample of published times is enough for provenance and avoids bulk slot requests.
        for unit, (url, label) in list(timetable_sources.items())[:10]:
            schedule = published_schedule(await html(url), as_of, label)
            if schedule:
                branches[unit].update(schedule=schedule, schedule_as_of=as_of)
                branches[unit]["field_urls"]["schedule"] = url

        records = [SourceRecord(**record, specialties=list(record.get("specialty_urls", {})))
                   for record in [*organizations.values(), *branches.values()]]
        snapshot = SourceSnapshot(
            schema_version=1, source="poliklinika45", complete=True, retrieved_at=datetime.now(UTC),
            start_url=PROFILES_URL, pages=[SourcePage(url=PROFILES_URL, records=records)], empty_profiles=empty_profiles,
        )
        snapshot.records()
        return snapshot
