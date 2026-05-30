"""Live sector population (occupancy) at a moment in time.

Counts how many flights are inside each sector at a given instant, split by
altitude band. A flight's horizontal position is interpolated along its route
by arc length; its altitude is modelled with a simple climb / cruise / descent
profile so it can be assigned to the LOW ([0, 35000) ft) or HIGH ([35000,
60000) ft) band. Sectors partition each band with no overlap, so a flight in a
band occupies exactly one sector — we stop at the first match.
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import datetime
from typing import Iterable

from flights import RoutesSnapshot
from sectors import Sector

BAND_CEIL_FT = 35000  # LOW below this, HIGH at/above it
_CLIMB = 0.15         # fraction of the flight spent climbing / descending


def altitude_at(cruise_ft: float, p: float) -> float:
    """Altitude (ft) at progress fraction ``p`` of a flight (0=takeoff,1=landing)."""
    if p <= 0 or p >= 1:
        return 0.0
    if p < _CLIMB:
        return cruise_ft * (p / _CLIMB)
    if p > 1 - _CLIMB:
        return cruise_ft * ((1 - p) / _CLIMB)
    return cruise_ft


def position_at(lons: list[float], lats: list[float], p: float) -> tuple[float, float]:
    """(lon, lat) at arc-length fraction ``p`` along the route polyline."""
    n = min(len(lons), len(lats))
    if n == 0:
        return 0.0, 0.0
    if n == 1:
        return lons[0], lats[0]
    cum = [0.0] * n
    for i in range(1, n):
        cum[i] = cum[i - 1] + math.hypot(lons[i] - lons[i - 1], lats[i] - lats[i - 1])
    total = cum[-1]
    if total <= 0:
        return lons[0], lats[0]
    target = p * total
    i = 1
    while i < n - 1 and cum[i] < target:
        i += 1
    seg = (cum[i] - cum[i - 1]) or 1e-9
    local = (target - cum[i - 1]) / seg
    return (
        lons[i - 1] + (lons[i] - lons[i - 1]) * local,
        lats[i - 1] + (lats[i] - lats[i - 1]) * local,
    )


def band_of(altitude_ft: float) -> str:
    return "LOW" if altitude_ft < BAND_CEIL_FT else "HIGH"


def sector_population(
    snapshot: RoutesSnapshot,
    sectors: Iterable[Sector],
    when: datetime,
    band: str,
) -> Counter:
    """Per-sector flight count at ``when`` for one altitude band.

    ``sectors`` should already be restricted to the requested band.
    """
    sectors = list(sectors)
    t = when.timestamp()
    counts: Counter = Counter()
    for fl in snapshot.flights:
        t0 = fl.take_off_time.timestamp()
        t1 = fl.scheduled_landing_time.timestamp()
        span = t1 - t0
        if span <= 0 or t < t0 or t > t1:
            continue
        p = (t - t0) / span
        if band_of(altitude_at(fl.cruise_altitude_ft, p)) != band:
            continue
        lon, lat = position_at(fl.lons, fl.lats, p)
        for s in sectors:
            if s.contains(lon, lat):
                counts[s.name] += 1
                break
    return counts
