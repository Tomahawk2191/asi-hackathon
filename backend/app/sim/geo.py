"""Great-circle helpers."""
from __future__ import annotations

import math
from typing import Iterable

import numpy as np

R_NM = 3440.065  # Earth radius in nautical miles


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_NM * math.asin(math.sqrt(a))


def polyline_length_nm(lats: Iterable[float], lons: Iterable[float]) -> float:
    lats = list(lats)
    lons = list(lons)
    return sum(
        haversine_nm(lats[i], lons[i], lats[i + 1], lons[i + 1])
        for i in range(len(lats) - 1)
    )


def cum_distances_nm(lats: list[float], lons: list[float]) -> np.ndarray:
    out = np.zeros(len(lats), dtype=np.float64)
    for i in range(1, len(lats)):
        out[i] = out[i - 1] + haversine_nm(lats[i - 1], lons[i - 1], lats[i], lons[i])
    return out


def interpolate_along(lats: list[float], lons: list[float], cum: np.ndarray, dist_nm: float) -> tuple[float, float]:
    """Linear interpolation in lat/lon along a polyline at distance `dist_nm` from the start."""
    if dist_nm <= 0:
        return lats[0], lons[0]
    if dist_nm >= cum[-1]:
        return lats[-1], lons[-1]
    # Binary search.
    lo, hi = 0, len(cum) - 1
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if cum[mid] <= dist_nm:
            lo = mid
        else:
            hi = mid
    seg = cum[hi] - cum[lo]
    t = (dist_nm - cum[lo]) / seg if seg > 0 else 0.0
    return (lats[lo] + t * (lats[hi] - lats[lo]),
            lons[lo] + t * (lons[hi] - lons[lo]))
