"""Synthetic convective weather polygons for a scenario.

The hackathon bundle ships no weather data, so we generate plausible
convective-cell polygons deterministically from the scenario date: the same
date always yields the same cells, and summer dates get more / more severe
cells than winter ones. These are boundary polygons only (think convective
SIGMET areas), not a radar reflectivity field.

Coordinates are [lon, lat], WGS84, GeoJSON order.
"""

from __future__ import annotations

import hashlib
import math
import random

# Region the cells are scattered over: the NYC metro plus its approach
# corridors (lon west->east, lat south->north).
_LON_MIN, _LON_MAX = -77.0, -71.0
_LAT_MIN, _LAT_MAX = 39.6, 42.8

_LEVELS = ["LIGHT", "MODERATE", "SEVERE"]


def _seed(scenario: str) -> int:
    return int(hashlib.md5(scenario.encode()).hexdigest(), 16) % (2**32)


def _season(scenario: str) -> tuple[int, int]:
    """(cell_count, max_severity) for the scenario's month."""
    try:
        month = int(scenario[5:7])
    except (ValueError, IndexError):
        month = 6
    if month in (6, 7, 8, 9):       # summer convective season
        return 5, 3
    if month in (3, 4, 5, 10):      # shoulder seasons
        return 3, 3
    return 2, 2                     # winter — fewer, weaker cells


def _blob(rng: random.Random, clon: float, clat: float, base_r: float, n: int = 24) -> list[list[float]]:
    """An irregular, smoothed blob polygon centred on (clon, clat)."""
    radii = [base_r * (0.70 + 0.55 * rng.random()) for _ in range(n)]
    for _ in range(2):  # smooth so the outline is lumpy, not spiky
        radii = [(radii[i - 1] + radii[i] + radii[(i + 1) % n]) / 3 for i in range(n)]
    coslat = math.cos(math.radians(clat)) or 1e-6
    ring: list[list[float]] = []
    for i in range(n):
        ang = 2 * math.pi * i / n
        lon = clon + radii[i] * math.cos(ang) / coslat
        lat = clat + radii[i] * math.sin(ang)
        ring.append([round(lon, 4), round(lat, 4)])
    ring.append(ring[0])  # close the ring
    return ring


def generate_weather(scenario: str) -> dict:
    """A GeoJSON FeatureCollection of convective cells for the scenario."""
    rng = random.Random(_seed(scenario))
    count, max_sev = _season(scenario)
    features = []
    for i in range(count):
        clon = rng.uniform(_LON_MIN, _LON_MAX)
        clat = rng.uniform(_LAT_MIN, _LAT_MAX)
        severity = rng.randint(1, max_sev)
        base_r = rng.uniform(0.25, 0.7) * (0.65 + 0.18 * severity)
        ring = _blob(rng, clon, clat, base_r)
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "id": f"WX{i + 1}",
                    "severity": severity,
                    "level": _LEVELS[severity - 1],
                },
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            }
        )
    return {"type": "FeatureCollection", "features": features}
