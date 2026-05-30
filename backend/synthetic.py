"""Generate synthetic RoutesSnapshot flight data from BTS arrival-demand records.

When a day has BTS arrival counts but no ASI routes file (e.g. Christmas 2025),
this module synthesises plausible flight tracks so the frontend can animate them.
Each generated flight follows a great-circle path from a pool of major US origins,
with its departure time back-calculated from the landing time and haversine distance.

The generation is deterministic (seeded by day string) so repeated calls for the
same day always produce the same flights.
"""

from __future__ import annotations

import math
import random
import sqlite3
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Airport geometry
# ---------------------------------------------------------------------------

# Destination airports: the 22 airports seeded by seed_bts.py.
_DEST: dict[str, tuple[float, float]] = {
    "KJFK": (40.6413, -73.7781),
    "KLGA": (40.7773, -73.8726),
    "KEWR": (40.6895, -74.1745),
    "KLAX": (33.9425, -118.4081),
    "KBUR": (34.2007, -118.3585),
    "KLGB": (33.8177, -118.1516),
    "KONT": (34.0560, -117.6012),
    "KSNA": (33.6757, -117.8683),
    "KSFO": (37.6213, -122.3790),
    "KOAK": (37.7213, -122.2208),
    "KSJC": (37.3626, -121.9292),
    "KORD": (41.9742, -87.9073),
    "KMDW": (41.7868, -87.7524),
    "KDFW": (32.8998, -97.0403),
    "KDAL": (32.8471, -96.8518),
    "KMIA": (25.7959, -80.2870),
    "KFLL": (26.0726, -80.1527),
    "KATL": (33.6407, -84.4277),
    "KDEN": (39.8561, -104.6737),
    "KBOS": (42.3656, -71.0096),
    "KPHX": (33.4373, -112.0078),
    "KSEA": (47.4502, -122.3088),
}

# Extra airports used as origins only (not seeded destinations).
_EXTRA: dict[str, tuple[float, float]] = {
    "KPHL": (39.8719, -75.2411),
    "KDCA": (38.8512, -77.0402),
    "KIAD": (38.9531, -77.4565),
    "KTPA": (27.9755, -82.5332),
    "KMCO": (28.4294, -81.3089),
    "KCLT": (35.2140, -80.9431),
    "KDTW": (42.2162, -83.3554),
    "KSTL": (38.7487, -90.3700),
    "KMSP": (44.8848, -93.2223),
    "KHOU": (29.6454, -95.2789),
    "KIAH": (29.9902, -95.3368),
    "KLAS": (36.0840, -115.1537),
    "KSLC": (40.7884, -111.9778),
    "KPDX": (45.5887, -122.5975),
    "KSAN": (32.7341, -117.1896),
    "KABQ": (35.0402, -106.6090),
    "KRDU": (35.8776, -78.7875),
    "KMEM": (35.0424, -89.9767),
    "KPIT": (40.4915, -80.2329),
}

ALL_AIRPORTS: dict[str, tuple[float, float]] = {**_DEST, **_EXTRA}

# Airports that share a metro — used to exclude same-metro origins.
_METRO_GROUPS: list[frozenset[str]] = [
    frozenset({"KJFK", "KLGA", "KEWR"}),
    frozenset({"KLAX", "KBUR", "KLGB", "KONT", "KSNA"}),
    frozenset({"KSFO", "KOAK", "KSJC"}),
    frozenset({"KORD", "KMDW"}),
    frozenset({"KDFW", "KDAL"}),
    frozenset({"KMIA", "KFLL"}),
]
_SAME_METRO: dict[str, frozenset[str]] = {}
for _g in _METRO_GROUPS:
    for _ap in _g:
        _SAME_METRO[_ap] = _g


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in nautical miles."""
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lon2 - lon1)
    a = math.sin(dφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ / 2) ** 2
    return 2 * math.asin(math.sqrt(max(0.0, a))) * 3440.1


def _great_circle(
    lat1: float, lon1: float, lat2: float, lon2: float, n: int = 18
) -> list[list[float]]:
    """Return n+1 [lat, lon] waypoints along the great-circle arc."""
    φ1, λ1 = math.radians(lat1), math.radians(lon1)
    φ2, λ2 = math.radians(lat2), math.radians(lon2)
    dφ, dλ = φ2 - φ1, λ2 - λ1
    a = math.sin(dφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ / 2) ** 2
    d = 2 * math.asin(math.sqrt(max(0.0, a)))
    if d < 1e-8:
        return [[lat2, lon2]] * (n + 1)
    pts = []
    for i in range(n + 1):
        f = i / n
        A = math.sin((1 - f) * d) / math.sin(d)
        B = math.sin(f * d) / math.sin(d)
        x = A * math.cos(φ1) * math.cos(λ1) + B * math.cos(φ2) * math.cos(λ2)
        y = A * math.cos(φ1) * math.sin(λ1) + B * math.cos(φ2) * math.sin(λ2)
        z = A * math.sin(φ1) + B * math.sin(φ2)
        pts.append([
            math.degrees(math.atan2(z, math.sqrt(x ** 2 + y ** 2))),
            math.degrees(math.atan2(y, x)),
        ])
    return pts


def _duration_min(origin: str, dest: str) -> int:
    """Estimate flight duration in minutes (450 kt cruise + 40 min overhead)."""
    o = ALL_AIRPORTS.get(origin)
    d = _DEST.get(dest)
    if not o or not d:
        return 120
    nm = _haversine_nm(o[0], o[1], d[0], d[1])
    return max(40, round(nm / 450 * 60) + 40)


# ---------------------------------------------------------------------------
# Snapshot synthesis
# ---------------------------------------------------------------------------

def synthesize_snapshot(day: str, conn: sqlite3.Connection) -> dict:
    """Build a RoutesSnapshot-compatible dict from BTS arrival demand for *day*.

    Returns an empty dict (falsy) if no demand data is available.
    """
    import db as _db  # avoid circular import at module level

    rows = _db.read_day(conn, day, "arrival")
    if not rows:
        return {}

    buckets = [datetime.fromisoformat(r["bucket_start"]) for r in rows]
    window_start = min(buckets)
    window_end = max(buckets) + timedelta(minutes=5)

    rng = random.Random(hash(day))  # deterministic per day

    flights: list[dict] = []
    idx = 0

    by_airport: dict[str, list[dict]] = {}
    for r in rows:
        by_airport.setdefault(r["airport"], []).append(r)

    for dest_icao, dest_rows in by_airport.items():
        dest_pos = _DEST.get(dest_icao)
        if not dest_pos:
            continue
        excluded = _SAME_METRO.get(dest_icao, frozenset())
        pool = [k for k in ALL_AIRPORTS if k != dest_icao and k not in excluded]
        if not pool:
            continue

        for row in dest_rows:
            count = int(row["flight_count"])
            if count <= 0:
                continue
            bucket_dt = datetime.fromisoformat(row["bucket_start"])

            for _ in range(count):
                origin_icao = rng.choice(pool)
                origin_pos = ALL_AIRPORTS[origin_icao]

                # Random landing time within the 5-min bucket
                land_dt = bucket_dt + timedelta(seconds=rng.randint(0, 299))
                dur = _duration_min(origin_icao, dest_icao)
                depart_dt = land_dt - timedelta(minutes=dur)

                wpts = _great_circle(
                    origin_pos[0], origin_pos[1],
                    dest_pos[0], dest_pos[1],
                )

                idx += 1
                flights.append({
                    "flight_number": f"SYN{idx:05d}",
                    "take_off_time": depart_dt.isoformat(),
                    "scheduled_landing_time": land_dt.isoformat(),
                    "origin_airport_icao": origin_icao,
                    "destination_airport_icao": dest_icao,
                    "cruise_altitude_ft": 35000,
                    "cruise_speed_kt": 450,
                    "lats": [w[0] for w in wpts],
                    "lons": [w[1] for w in wpts],
                    "is_airborne": depart_dt < window_start,
                })

    return {
        "asked_at": day,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "nyc_filter": None,
        "flights": flights,
    }
