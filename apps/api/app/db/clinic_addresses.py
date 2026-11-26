import re
from math import cos, radians

import sqlalchemy as sa

from app.db.models import Base
from app.schemas.clinics import AddressCandidate, Coordinates

addresses = sa.Table(
    "clinic_addresses", Base.metadata,
    sa.Column("osm_id", sa.String(32), primary_key=True),
    sa.Column("label", sa.Text, nullable=False),
    sa.Column("street_key", sa.Text, nullable=False),
    sa.Column("street_type", sa.Text, nullable=False),
    sa.Column("house_key", sa.Text, nullable=False, index=True),
    sa.Column("lat", sa.Float, nullable=False),
    sa.Column("lon", sa.Float, nullable=False),
)

CITY = "Курган"
STREET_TYPES = {
    "улица": ("ул",), "проспект": ("пр-кт", "просп"), "переулок": ("пер",),
    "бульвар": ("бул", "б-р"), "шоссе": (), "набережная": ("наб",),
    "проезд": ("пр-д",), "площадь": ("пл",),
}
STREET_ALIASES = {alias: name for name, aliases in STREET_TYPES.items() for alias in (name, *aliases)}
STREET_TYPE = r"(?:{})".format("|".join(STREET_ALIASES))
HOUSE_MARKER = r"(?:дом|д)\.?\s*"
HOUSE = r"\d+[а-яa-z]?(?:\s*[/\-]\s*\d+[а-яa-z]?)?(?:[,\s]*(?:корпус|корп|строение|стр|к|с)\.?\s*\d+[а-яa-z]?)*"
CITY_MARKER = r"(?:город\s+|г(?:\.\s*|\s+))"


def normalize(value: str) -> str:
    return " ".join(value.lower().replace("ё", "е").split())


def street_key(street: str) -> str:
    value = normalize(street)
    value = re.sub(rf"(?<!\w){STREET_TYPE}(?!\w)", " ", value)
    value = re.sub(r"(?<!\w)(?:мкр-н|мкр|микрорайон)(?!\w)", " микрорайон ", value)
    return " ".join(re.sub(r"[^0-9a-zа-я-]+", " ", value).split())


def street_type(street: str) -> str:
    match = re.search(rf"(?<!\w){STREET_TYPE}(?!\w)", normalize(street))
    return STREET_ALIASES[match[0]] if match else ""


def house_key(house: str) -> str:
    value = re.sub(r"[.,\s]", "", normalize(house))
    return value.replace("корпус", "к").replace("корп", "к").replace("строение", "с").replace("стр", "с")


def address_query(address: str) -> tuple[str, str, str]:
    value = normalize(address)
    value = re.sub(r"(?:,\s*|\s+)(?:кв(?:артира)?\.?|подъезд|этаж)\s*№?\s*\d.*$", "", value)
    value = re.sub(r"^(?:\d{6}\s*,\s*)?(?:россия\s*,\s*)?(?:курганская обл(?:асть)?\.?\s*,\s*)?", "", value)
    city = re.match(rf"^{CITY_MARKER}", value)
    kurgan = re.match(rf"^(?:{CITY_MARKER})?курган(?=\s|,|$)[,\s]*", value)
    if kurgan:
        value = value[kurgan.end():]
    elif city:
        raise ValueError("clinic_outside_pilot")
    else:
        first, separator, rest = value.partition(",")
        # A comma before a street name separates the locality, unlike a comma before a house.
        if (separator and not re.search(rf"\b{STREET_TYPE}\b", first)
                and re.match(r"[а-яa-z]", rest.strip())
                and not re.fullmatch(rf"{HOUSE_MARKER}{HOUSE}", rest.strip())):
            raise ValueError("clinic_outside_pilot")
        if re.match(rf"^[а-яa-z-]+\s+{STREET_TYPE}\.?\s+[а-яa-z]", value):
            raise ValueError("clinic_outside_pilot")

    match = re.search(rf"(?<=[ ,])(?:{HOUSE_MARKER})?({HOUSE})\s*$", value)
    street = value[:match.start()] if match else value
    return street_key(street), house_key(match[1]) if match else "", street_type(street)


async def find_addresses(db, street: str, house: str, kind: str) -> list[AddressCandidate]:
    if not street:
        return []
    statement = sa.select(addresses).where(addresses.c.street_key.like("%" + "%".join(street.split()) + "%"))
    if kind:
        statement = statement.where(addresses.c.street_type.in_((kind, "")))
    if house:
        matches = addresses.c.house_key == house
        if re.fullmatch(r"\d+", house):
            matches = sa.or_(matches, addresses.c.house_key.like(house + "к%"), addresses.c.house_key.like(house + "с%"))
        statement = statement.where(matches)
    unique = (statement.distinct(addresses.c.street_key, addresses.c.street_type, addresses.c.house_key)
              .order_by(addresses.c.street_key, addresses.c.street_type, addresses.c.house_key, addresses.c.osm_id).subquery())
    ranked = (sa.select(unique)
              .order_by((unique.c.street_key == street).desc(), (unique.c.house_key == house).desc(),
                        unique.c.street_key, (unique.c.street_type == kind).desc(), sa.func.length(unique.c.house_key),
                        unique.c.house_key, unique.c.osm_id)
              .limit(8))
    return [AddressCandidate(label=row.label, city=CITY, lat=row.lat, lon=row.lon) for row in (await db.execute(ranked))]


async def nearest_address(db, point: Coordinates) -> AddressCandidate | None:
    metres_per_degree = 111_200
    north = (addresses.c.lat - point.lat) * metres_per_degree
    east = (addresses.c.lon - point.lon) * (metres_per_degree * cos(radians(point.lat)))
    distance_squared = north * north + east * east
    nearest = (sa.select(addresses.c.label, addresses.c.lat, addresses.c.lon)
               .where(distance_squared <= 250 ** 2)
               .order_by(distance_squared, addresses.c.osm_id)
               .limit(1))
    row = (await db.execute(nearest)).one_or_none()
    return AddressCandidate(label=row.label, city=CITY, lat=row.lat, lon=row.lon) if row else None
