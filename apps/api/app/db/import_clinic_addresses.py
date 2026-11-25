import argparse
import asyncio
import gzip
import itertools
import json
from pathlib import Path
from xml.etree import ElementTree

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.clinic_addresses import (
    CITY,
    addresses,
    house_key,
    normalize,
    street_key,
    street_type,
)
from app.db.clinic_catalog import within_pilot
from app.db.engine import create_engine


def osm_xml_snapshot(path: Path):
    root = ElementTree.parse(path).getroot()
    nodes = {node.attrib["id"]: {"lat": float(node.attrib["lat"]), "lon": float(node.attrib["lon"])}
             for node in root.findall("node")}
    elements = []
    for feature in root:
        kind = feature.tag
        if kind not in ("node", "way"):
            continue
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in feature.findall("tag")
                if tag.attrib["k"] in ("addr:street", "addr:place", "addr:city", "addr:housenumber", "building")}
        if not tags.get("addr:housenumber"):
            continue
        identifier = feature.attrib["id"]
        item = {"type": kind, "id": int(identifier), "tags": tags}
        if kind == "node":
            item.update(nodes[identifier])
        else:
            references = [ref.attrib["ref"] for ref in feature.findall("nd")]
            if not all(ref in nodes for ref in references):
                continue
            item["geometry"] = [nodes[ref] for ref in references]
        elements.append(item)
    return {"elements": elements}


def building_location(geometry):
    points = [(point["lat"], point["lon"]) for point in geometry]
    if len(points) < 4 or points[0] != points[-1]:
        return None
    # Take the midpoint of the widest interior segment on a scanline through the building.
    latitudes = sorted({lat for lat, _ in points})
    if len(latitudes) < 2:
        return None
    middle = len(latitudes) // 2
    lat = (latitudes[middle - 1] + latitudes[middle]) / 2
    intersections = sorted(
        lon_a + (lon_b - lon_a) * (lat - lat_a) / (lat_b - lat_a)
        for (lat_a, lon_a), (lat_b, lon_b) in itertools.pairwise(points)
        if min(lat_a, lat_b) < lat < max(lat_a, lat_b)
    )
    spans = list(zip(intersections[::2], intersections[1::2]))
    if spans:
        left, right = max(spans, key=lambda span: span[1] - span[0])
        return lat, (left + right) / 2
    return None


def address_rows(snapshot):
    rows = {}
    for feature in snapshot["elements"]:
        kind = feature["type"]
        tags = feature.get("tags", {})
        street = tags.get("addr:street") or tags.get("addr:place")
        house = tags.get("addr:housenumber")
        if not street or not house or normalize(tags.get("addr:city", CITY)) != normalize(CITY):
            continue
        if kind == "node":
            point = feature["lat"], feature["lon"]
        elif kind == "way" and tags.get("building") not in (None, "no"):
            point = building_location(feature.get("geometry", []))
        else:
            continue
        if not point or not within_pilot(*point):
            continue
        identifier = f"{kind}/{feature['id']}"
        rows[identifier] = {
            "osm_id": identifier, "label": f"{CITY}, {street.strip()}, {house.strip()}",
            "street_key": street_key(street), "street_type": street_type(street), "house_key": house_key(house),
            "lat": point[0], "lon": point[1],
        }
    return list(rows.values())


async def replace_addresses(db, rows):
    if not rows:
        raise ValueError("No Kurgan addresses in the extract")
    await db.execute(sa.text("LOCK TABLE clinic_addresses IN SHARE ROW EXCLUSIVE MODE"))
    await db.execute(addresses.delete())
    await db.execute(addresses.insert(), rows)


async def run(path: Path):
    if path.suffix == ".osm":
        snapshot = osm_xml_snapshot(path)
    else:
        encoded = path.read_bytes()
        snapshot = json.loads(gzip.decompress(encoded) if path.suffix == ".gz" else encoded)
    if snapshot.get("remark"):
        raise ValueError("The Overpass extract is incomplete")
    rows = address_rows(snapshot)
    engine = create_engine()
    try:
        async with async_sessionmaker(engine).begin() as db:
            await replace_addresses(db, rows)
    finally:
        await engine.dispose()
    print(f"Imported {len(rows)} addresses from OpenStreetMap ({snapshot.get('osm3s', {}).get('timestamp_osm_base', 'date unavailable')})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import the Kurgan OpenStreetMap address extract (Overpass JSON or OSM XML)")
    parser.add_argument("path", type=Path)
    asyncio.run(run(parser.parse_args().path))
