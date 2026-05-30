from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

from shapely.geometry import shape
from shapely.strtree import STRtree

from ..config import HIGH_FLOOR_FT, LOW_FLOOR_FT, SECTORS_PATH


@dataclass(frozen=True)
class Sector:
    name: str
    band: str  # "HIGH" or "LOW"
    altitude_from_ft: int
    altitude_to_ft: int
    capacity: int
    geom: object  # shapely geometry


@dataclass(frozen=True)
class SectorIndex:
    sectors: list[Sector]
    by_name: dict[str, Sector]
    tree_high: STRtree
    tree_low: STRtree
    geoms_high: list
    geoms_low: list
    sectors_high: list[Sector]
    sectors_low: list[Sector]


@lru_cache(maxsize=1)
def load_sectors() -> SectorIndex:
    with open(SECTORS_PATH) as f:
        gj = json.load(f)
    sectors: list[Sector] = []
    for feat in gj["features"]:
        p = feat["properties"]
        name = p["name"]
        band = "HIGH" if name.startswith("HIGH_") else "LOW"
        sectors.append(
            Sector(
                name=name,
                band=band,
                altitude_from_ft=p["altitude_from_ft"],
                altitude_to_ft=p["altitude_to_ft"],
                capacity=p["capacity"],
                geom=shape(feat["geometry"]),
            )
        )
    by_name = {s.name: s for s in sectors}
    sectors_high = [s for s in sectors if s.band == "HIGH"]
    sectors_low = [s for s in sectors if s.band == "LOW"]
    geoms_high = [s.geom for s in sectors_high]
    geoms_low = [s.geom for s in sectors_low]
    return SectorIndex(
        sectors=sectors,
        by_name=by_name,
        tree_high=STRtree(geoms_high),
        tree_low=STRtree(geoms_low),
        geoms_high=geoms_high,
        geoms_low=geoms_low,
        sectors_high=sectors_high,
        sectors_low=sectors_low,
    )


def sector_for(lon: float, lat: float, alt_ft: float) -> Sector | None:
    """Return the sector containing (lon, lat) in the appropriate altitude band."""
    from shapely.geometry import Point
    idx = load_sectors()
    if alt_ft >= HIGH_FLOOR_FT:
        tree, sectors = idx.tree_high, idx.sectors_high
    else:
        tree, sectors = idx.tree_low, idx.sectors_low
    pt = Point(lon, lat)
    cands = tree.query(pt)
    for i in cands:
        s = sectors[i]
        if s.geom.contains(pt) and s.altitude_from_ft <= alt_ft < s.altitude_to_ft:
            return s
    return None


def sectors_as_geojson(band: str | None = None) -> dict:
    idx = load_sectors()
    feats = []
    for s in idx.sectors:
        if band and s.band != band:
            continue
        feats.append({
            "type": "Feature",
            "properties": {
                "name": s.name,
                "band": s.band,
                "altitude_from_ft": s.altitude_from_ft,
                "altitude_to_ft": s.altitude_to_ft,
                "capacity": s.capacity,
            },
            "geometry": s.geom.__geo_interface__,
        })
    return {"type": "FeatureCollection", "features": feats}
