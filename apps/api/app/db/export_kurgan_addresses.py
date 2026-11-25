"""Prepare an OpenStreetMap address snapshot from a Geofabrik PBF."""

import argparse
import gzip
import itertools
import json
from pathlib import Path

from app.db.clinic_catalog import within_pilot
from app.db.import_clinic_addresses import building_location

KURGAN_RELATION = 398427
ADDRESS_TAGS = ("addr:street", "addr:place", "addr:city", "addr:housenumber", "building")


def in_ring(lon, lat, ring):
    crossings = sum(
        lon < x1 + (x2 - x1) * (lat - y1) / (y2 - y1)
        for (x1, y1), (x2, y2) in itertools.pairwise(ring)
        if (y1 > lat) != (y2 > lat)
    )
    return crossings % 2 == 1


def export(path: Path, output: Path):
    import osmium

    with osmium.io.Reader(str(path)) as reader:
        timestamp = reader.header().get("osmosis_replication_timestamp")
    processor = (osmium.FileProcessor(str(path)).with_areas(osmium.filter.IdFilter([KURGAN_RELATION]))
                 .with_filter(osmium.filter.KeyFilter("addr:housenumber", "boundary")))
    boundary = None
    candidates = []
    for feature in processor:
        if isinstance(feature, osmium.osm.Area) and not feature.from_way() and feature.orig_id() == KURGAN_RELATION:
            boundary = json.loads(osmium.geom.GeoJSONFactory().create_multipolygon(feature))["coordinates"]
            continue
        tags = {key: feature.tags[key] for key in ADDRESS_TAGS if key in feature.tags}
        if not tags.get("addr:housenumber") or not (tags.get("addr:street") or tags.get("addr:place")):
            continue
        if isinstance(feature, osmium.osm.Node):
            point = feature.lat, feature.lon
            element = {"type": "node", "lat": point[0], "lon": point[1]}
        elif isinstance(feature, osmium.osm.Way) and tags.get("building") not in (None, "no"):
            if not feature.nodes or not feature.nodes[0].location.valid():
                continue
            if not within_pilot(feature.nodes[0].lat, feature.nodes[0].lon):
                continue
            geometry = [{"lat": node.lat, "lon": node.lon} for node in feature.nodes if node.location.valid()]
            point = building_location(geometry)
            element = {"type": "way", "geometry": geometry}
        else:
            continue
        if point and within_pilot(*point):
            candidates.append((point, element | {"id": feature.id, "tags": tags}))
    if not boundary:
        raise ValueError("The PBF does not contain the Kurgan municipal boundary")

    elements = [
        element for (lat, lon), element in candidates
        if any(in_ring(lon, lat, outer) and not any(in_ring(lon, lat, hole) for hole in holes)
               for outer, *holes in boundary)
    ]
    if not elements:
        raise ValueError("No addresses within the Kurgan boundary")
    snapshot = {
        "osm3s": {"timestamp_osm_base": timestamp},
        "source": "https://download.geofabrik.de/russia/ural-fed-district/",
        "boundary": f"https://www.openstreetmap.org/relation/{KURGAN_RELATION}",
        "attribution": "© OpenStreetMap contributors",
        "license": "ODbL-1.0",
        "elements": elements,
    }
    encoded = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode()
    output.write_bytes(gzip.compress(encoded, mtime=0) if output.suffix == ".gz" else encoded)
    print(f"Exported {len(elements)} OSM address objects ({timestamp})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pbf", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    export(args.pbf, args.output)
