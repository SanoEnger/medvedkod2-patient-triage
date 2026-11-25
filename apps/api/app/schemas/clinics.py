from datetime import date, datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

Payment = Literal["oms", "dms", "paid"]
PatientGroup = Literal["child", "adult"]
Code = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$")]
Phone = Annotated[str, StringConstraints(pattern=r"^(?:\+[1-9][0-9]{6,14}|122)$")]


def https_url(value: str | None) -> str | None:
    if value is not None:
        url = urlsplit(value)
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("Expected a public HTTPS URL")
    return value


class Coordinates(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class GeocodeRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    address: str = Field(min_length=3, max_length=240)


class AddressCandidate(Coordinates):
    label: str
    city: str


class GeocodeResponse(BaseModel):
    candidates: list[AddressCandidate]


class ClinicSearch(Coordinates):
    model_config = ConfigDict(extra="forbid")

    radius_km: float = Field(default=5, gt=0, le=30)
    specialty_code: Code | None = None
    payment_method: Payment | None = None
    insurer_id: Code | None = None
    patient_group: PatientGroup | None = None

    @model_validator(mode="after")
    def insurer_requires_dms(self):
        if self.insurer_id and self.payment_method != "dms":
            raise ValueError("insurer_id requires DMS")
        return self


class Insurer(BaseModel):
    id: Code
    name: str


class ClinicPayment(BaseModel):
    method: Payment
    specialty_code: Code
    insurer: Insurer | None = None
    program: str | None = None


class ClinicSourceInfo(BaseModel):
    name: str
    url: str
    updated_at: datetime | None = None


class ClinicBranch(Coordinates):
    id: Code
    name: str
    address: str
    kind: Literal["public", "private"]
    phones: list[Phone] = Field(min_length=1)
    website: str | None = None
    booking_url: str | None = None
    poliklinika45_url: str | None = None
    gosuslugi_url: str | None = None
    gosuslugi_select_branch: bool = False
    demo: bool
    payments: list[ClinicPayment]
    oms_needs_confirmation: bool = False
    specialties: list[Code] = Field(default_factory=list)
    sources: list[ClinicSourceInfo] = Field(default_factory=list)
    distance_km: float


class ClinicSearchResponse(BaseModel):
    items: list[ClinicBranch]
    insurers: list[Insurer]


class CatalogPayment(ClinicPayment):
    source: str = Field(min_length=1)
    checked_on: date
    confirmed: bool

    @model_validator(mode="after")
    def only_dms_has_insurance(self):
        if (self.insurer or self.program) and self.method != "dms":
            raise ValueError("Insurance details require DMS")
        if self.program and not self.insurer:
            raise ValueError("Insurance program requires an insurer")
        return self


class CatalogOrganization(BaseModel):
    id: Code
    name: str = Field(min_length=1)
    kind: Literal["public", "private"]


class CatalogBranch(Coordinates):
    id: Code
    organization_id: Code
    address: str = Field(min_length=1)
    phones: list[Phone] = Field(min_length=1)
    source: str = Field(min_length=1)
    audience: Literal["child", "adult", "all"] | None = None
    website: str | None = None
    booking_url: str | None = None
    gosuslugi_confirmed: bool = False
    gosuslugi_direct_url: str | None = None
    payments: list[CatalogPayment] = Field(default_factory=list)

    @field_validator("website", "booking_url", "gosuslugi_direct_url")
    @classmethod
    def validate_url(cls, value: str | None):
        return https_url(value)

    @model_validator(mode="after")
    def validate_gosuslugi(self):
        if self.gosuslugi_direct_url:
            host = urlsplit(self.gosuslugi_direct_url).hostname or ""
            if not self.gosuslugi_confirmed or not (host == "gosuslugi.ru" or host.endswith(".gosuslugi.ru")):
                raise ValueError("Direct booking requires verified Gosuslugi data")
        return self


class ClinicCatalog(BaseModel):
    demo: bool
    organizations: list[CatalogOrganization]
    branches: list[CatalogBranch]

    @model_validator(mode="after")
    def validate_ids(self):
        organizations = {org.id for org in self.organizations}
        branches = {branch.id for branch in self.branches}
        if len(organizations) != len(self.organizations) or len(branches) != len(self.branches):
            raise ValueError("Duplicate catalog ID")
        if any(identifier.startswith("demo-") != self.demo for identifier in organizations | branches):
            raise ValueError("The demo- prefix is reserved for demonstration data")
        if any(branch.organization_id not in organizations for branch in self.branches):
            raise ValueError("Missing branch organization")
        return self
