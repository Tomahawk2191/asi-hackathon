"""A* router over a coarse lat/lon grid with weather + sector penalties.

The router plans for a single new flight from (origin) to (destination) at a
given cruise altitude and speed, departing at a given time. Costs:

- base = great-circle leg distance (NM)
- weather penalty: if the cell the leg ends in has REFC >= 40 dBZ at the time
  the flight would be there, *and* the flight's altitude is below RETOP, add a
  large penalty (effectively prefer rerouting).
- sector penalty: if the sector the leg ends in is already at or above capacity
  at the time the flight would be there, add a moderate penalty.

The result is a polyline of waypoints. We snap origin and destination onto the
grid for search, then prepend the exact origin and append the exact destination.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
from shapely.geometry import Point

from ..config import HIGH_FLOOR_FT
from ..data.sectors import load_sectors
from ..data.weather import load_strip_matrix, mask_nodata, pick_strip
from ..sim.geo import haversine_nm
from ..sim.simulator import sector_loads_at

# Grid: bounded to CONUS-ish region, fine enough that storm cells (~13 km
# REFC pixels) and routing decisions don't get steamrolled by coarse nodes.
GRID_LAT_MIN, GRID_LAT_MAX = 24.0, 50.0
GRID_LON_MIN, GRID_LON_MAX = -125.0, -66.0
GRID_STEP_DEG = 0.5  # ~30 nm; A* visits ~4× the nodes of the old 1° grid

# 16 neighbors: cardinals/diagonals + knight-moves to keep turn smoothness.
_DIRS = [(-1, -1), (-1, 0), (-1, 1),
         (0, -1),           (0, 1),
         (1, -1),  (1, 0),  (1, 1),
         (-2, -1), (-2, 1), (2, -1), (2, 1),
         (-1, -2), (-1, 2), (1, -2), (1, 2)]

# Densify output: ensure no leg exceeds this many minutes of flight time.
MAX_LEG_MINUTES = 19.0


@dataclass
class RouteRequest:
    origin_lat: float
    origin_lon: float
    dest_lat: float
    dest_lon: float
    cruise_altitude_ft: int
    cruise_speed_kt: float
    depart_at: datetime
    snapshot: str
    avoid_weather: bool = True
    avoid_overloaded_sectors: bool = True


@dataclass
class RouteResult:
    lats: list[float]
    lons: list[float]
    total_nm: float
    eta_hours: float
    waypoints_avoided_weather: int
    sectors_traversed: list[str]
    overloaded_sectors_hit: list[str]
    base_distance_nm: float  # great-circle origin→dest


def _grid_dims() -> tuple[int, int]:
    n_lat = int(round((GRID_LAT_MAX - GRID_LAT_MIN) / GRID_STEP_DEG)) + 1
    n_lon = int(round((GRID_LON_MAX - GRID_LON_MIN) / GRID_STEP_DEG)) + 1
    return n_lat, n_lon


def _node_to_latlon(i: int, j: int) -> tuple[float, float]:
    return (GRID_LAT_MIN + i * GRID_STEP_DEG,
            GRID_LON_MIN + j * GRID_STEP_DEG)


def _latlon_to_node(lat: float, lon: float) -> tuple[int, int]:
    n_lat, n_lon = _grid_dims()
    i = round((lat - GRID_LAT_MIN) / GRID_STEP_DEG)
    j = round((lon - GRID_LON_MIN) / GRID_STEP_DEG)
    i = max(0, min(n_lat - 1, i))
    j = max(0, min(n_lon - 1, j))
    return i, j


def _refc_at_cell(refc_matrix: np.ndarray, lat: float, lon: float, box_pixels: int = 4) -> float:
    """Max REFC within a small box around the sample point.

    The bundle's REFC grid is ~13km per pixel, so a 4-pixel half-window is ~50km
    — comparable to the router's 1° leg length. Without this, narrow storm
    cells fall *between* router grid nodes and are never sampled.
    """
    from ..config import LAT_MAX, LAT_MIN, LON_MAX, LON_MIN, ROWS, COLS
    if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
        return np.nan
    row = int((LAT_MAX - lat) / (LAT_MAX - LAT_MIN) * ROWS)
    col = int((lon - LON_MIN) / (LON_MAX - LON_MIN) * COLS)
    r0 = max(0, row - box_pixels); r1 = min(ROWS, row + box_pixels + 1)
    c0 = max(0, col - box_pixels); c1 = min(COLS, col + box_pixels + 1)
    sub = refc_matrix[r0:r1, c0:c1]
    if sub.size == 0:
        return np.nan
    valid = sub[~np.isnan(sub)]
    return float(valid.max()) if valid.size else np.nan


def _retop_at_cell(retop_matrix: np.ndarray, lat: float, lon: float) -> float:
    from ..config import LAT_MAX, LAT_MIN, LON_MAX, LON_MIN, ROWS, COLS
    if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
        return np.nan
    row = int((LAT_MAX - lat) / (LAT_MAX - LAT_MIN) * ROWS)
    col = int((lon - LON_MIN) / (LON_MAX - LON_MIN) * COLS)
    row = max(0, min(ROWS - 1, row))
    col = max(0, min(COLS - 1, col))
    return float(retop_matrix[row, col])


def _gc_interpolate(lat1: float, lon1: float, lat2: float, lon2: float, f: float) -> tuple[float, float]:
    """Slerp along the great circle between (lat1,lon1) and (lat2,lon2); 0 <= f <= 1."""
    import math
    p1, p2 = math.radians(lat1), math.radians(lat2)
    l1, l2 = math.radians(lon1), math.radians(lon2)
    d = 2 * math.asin(math.sqrt(
        math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin((l2 - l1) / 2) ** 2
    ))
    if d < 1e-9:
        return lat1, lon1
    A = math.sin((1 - f) * d) / math.sin(d)
    B = math.sin(f * d) / math.sin(d)
    x = A * math.cos(p1) * math.cos(l1) + B * math.cos(p2) * math.cos(l2)
    y = A * math.cos(p1) * math.sin(l1) + B * math.cos(p2) * math.sin(l2)
    z = A * math.sin(p1) + B * math.sin(p2)
    lat = math.atan2(z, math.sqrt(x * x + y * y))
    lon = math.atan2(y, x)
    return math.degrees(lat), math.degrees(lon)


def _densify(lats: list[float], lons: list[float], speed_kt: float, max_minutes: float) -> tuple[list[float], list[float]]:
    """Insert intermediate great-circle waypoints so no leg exceeds max_minutes."""
    if len(lats) < 2:
        return lats, lons
    out_lats: list[float] = [lats[0]]
    out_lons: list[float] = [lons[0]]
    max_nm = speed_kt * (max_minutes / 60.0)
    for i in range(1, len(lats)):
        leg_nm = haversine_nm(lats[i - 1], lons[i - 1], lats[i], lons[i])
        n_extra = max(0, int(np.ceil(leg_nm / max_nm)) - 1)
        for k in range(1, n_extra + 1):
            f = k / (n_extra + 1)
            la, lo = _gc_interpolate(lats[i - 1], lons[i - 1], lats[i], lons[i], f)
            out_lats.append(la)
            out_lons.append(lo)
        out_lats.append(lats[i])
        out_lons.append(lons[i])
    return out_lats, out_lons


def _sector_for_route(lon: float, lat: float, alt_ft: float):
    """Same logic as data.sectors.sector_for but inlined for speed."""
    idx = load_sectors()
    if alt_ft >= HIGH_FLOOR_FT:
        tree, sectors = idx.tree_high, idx.sectors_high
    else:
        tree, sectors = idx.tree_low, idx.sectors_low
    pt = Point(lon, lat)
    for i in tree.query(pt):
        s = sectors[i]
        if s.geom.contains(pt) and s.altitude_from_ft <= alt_ft < s.altitude_to_ft:
            return s
    return None


def plan(req: RouteRequest) -> RouteResult:
    n_lat, n_lon = _grid_dims()
    start = _latlon_to_node(req.origin_lat, req.origin_lon)
    goal = _latlon_to_node(req.dest_lat, req.dest_lon)

    # Pre-fetch weather strips by time bucket — keyed by 15-min boundary that
    # contains the ETA at each candidate cell. We cache strip arrays lazily.
    refc_strips: dict[datetime, np.ndarray] = {}
    retop_strips: dict[datetime, np.ndarray] = {}

    def get_refc(at: datetime) -> Optional[np.ndarray]:
        s = pick_strip(req.snapshot, "refc", at)
        if s is None:
            return None
        if s.valid_from in refc_strips:
            return refc_strips[s.valid_from]
        m = mask_nodata("refc", load_strip_matrix(str(s.path)))
        refc_strips[s.valid_from] = m
        return m

    def get_retop(at: datetime) -> Optional[np.ndarray]:
        s = pick_strip(req.snapshot, "retop", at)
        if s is None:
            return None
        if s.valid_from in retop_strips:
            return retop_strips[s.valid_from]
        m = mask_nodata("retop", load_strip_matrix(str(s.path)))
        retop_strips[s.valid_from] = m
        return m

    # Sector load cache, keyed by the 5-min bucket that contains the ETA.
    sector_load_cache: dict[datetime, dict[str, int]] = {}

    def get_loads(at: datetime) -> dict[str, int]:
        bucket = at.replace(minute=(at.minute // 5) * 5, second=0, microsecond=0)
        if bucket not in sector_load_cache:
            sector_load_cache[bucket] = sector_loads_at(req.snapshot, bucket)
        return sector_load_cache[bucket]

    # A*.
    def h(i: int, j: int) -> float:
        lat, lon = _node_to_latlon(i, j)
        glat, glon = _node_to_latlon(goal[0], goal[1])
        return haversine_nm(lat, lon, glat, glon)

    g_score: dict[tuple[int, int], float] = {start: 0.0}
    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    open_heap: list[tuple[float, tuple[int, int]]] = [(h(*start), start)]
    closed: set[tuple[int, int]] = set()

    WEATHER_PENALTY_NM = 800.0
    OVERLOAD_PENALTY_NM = 250.0

    overloaded_hit: set[str] = set()
    weather_avoided = 0

    while open_heap:
        _, cur = heapq.heappop(open_heap)
        if cur == goal:
            break
        if cur in closed:
            continue
        closed.add(cur)
        clat, clon = _node_to_latlon(*cur)
        for di, dj in _DIRS:
            ni, nj = cur[0] + di, cur[1] + dj
            if not (0 <= ni < n_lat and 0 <= nj < n_lon):
                continue
            if (ni, nj) in closed:
                continue
            nlat, nlon = _node_to_latlon(ni, nj)
            leg_nm = haversine_nm(clat, clon, nlat, nlon)
            # ETA at end of this leg.
            so_far = g_score[cur]
            eta = req.depart_at + timedelta(hours=(so_far + leg_nm) / req.cruise_speed_kt)
            cost = leg_nm
            # Weather check: sample at endpoint AND midpoint of the leg.
            if req.avoid_weather:
                refc = get_refc(eta)
                retop = get_retop(eta)
                if refc is not None and retop is not None:
                    mlat = (clat + nlat) / 2.0
                    mlon = (clon + nlon) / 2.0
                    samples = [(nlat, nlon), (mlat, mlon)]
                    worst_refc = -1e9
                    tall_enough = False
                    for sla, slo in samples:
                        r = _refc_at_cell(refc, sla, slo)
                        if not np.isnan(r) and r > worst_refc:
                            worst_refc = r
                            t_top = _retop_at_cell(retop, sla, slo)
                            tall_enough = np.isnan(t_top) or t_top > req.cruise_altitude_ft
                    if worst_refc >= 40.0 and tall_enough:
                        cost += WEATHER_PENALTY_NM
            # Sector overload check.
            if req.avoid_overloaded_sectors:
                sec = _sector_for_route(nlon, nlat, req.cruise_altitude_ft)
                if sec is not None:
                    loads = get_loads(eta)
                    if loads.get(sec.name, 0) >= sec.capacity:
                        cost += OVERLOAD_PENALTY_NM
            tentative = g_score[cur] + cost
            if tentative < g_score.get((ni, nj), float("inf")):
                came_from[(ni, nj)] = cur
                g_score[(ni, nj)] = tentative
                f = tentative + h(ni, nj)
                heapq.heappush(open_heap, (f, (ni, nj)))

    # Reconstruct path.
    if goal not in came_from and start != goal:
        # No path → fall back to great-circle straight line.
        lats = [req.origin_lat, req.dest_lat]
        lons = [req.origin_lon, req.dest_lon]
    else:
        path: list[tuple[int, int]] = [goal]
        cur = goal
        while cur != start:
            cur = came_from[cur]
            path.append(cur)
        path.reverse()
        lats = [req.origin_lat] + [_node_to_latlon(i, j)[0] for (i, j) in path] + [req.dest_lat]
        lons = [req.origin_lon] + [_node_to_latlon(i, j)[1] for (i, j) in path] + [req.dest_lon]

    # Densify: subdivide any leg that takes more than MAX_LEG_MINUTES of flight
    # time. New points are interpolated along the great-circle of the leg.
    lats, lons = _densify(lats, lons, req.cruise_speed_kt, MAX_LEG_MINUTES)

    # Compute totals.
    total_nm = 0.0
    for i in range(len(lats) - 1):
        total_nm += haversine_nm(lats[i], lons[i], lats[i + 1], lons[i + 1])
    eta_h = total_nm / req.cruise_speed_kt
    base_nm = haversine_nm(req.origin_lat, req.origin_lon, req.dest_lat, req.dest_lon)

    # Sector traversal summary along chosen path.
    sectors_traversed: list[str] = []
    seen: set[str] = set()
    for la, lo in zip(lats, lons):
        s = _sector_for_route(lo, la, req.cruise_altitude_ft)
        if s and s.name not in seen:
            sectors_traversed.append(s.name)
            seen.add(s.name)

    # Overloaded sectors check at the times we'd be in them.
    cum_nm = 0.0
    for i in range(1, len(lats)):
        cum_nm += haversine_nm(lats[i - 1], lons[i - 1], lats[i], lons[i])
        eta = req.depart_at + timedelta(hours=cum_nm / req.cruise_speed_kt)
        s = _sector_for_route(lons[i], lats[i], req.cruise_altitude_ft)
        if s:
            loads = get_loads(eta)
            if loads.get(s.name, 0) >= s.capacity:
                overloaded_hit.add(s.name)

    return RouteResult(
        lats=lats, lons=lons,
        total_nm=total_nm,
        eta_hours=eta_h,
        waypoints_avoided_weather=weather_avoided,
        sectors_traversed=sectors_traversed,
        overloaded_sectors_hit=sorted(overloaded_hit),
        base_distance_nm=base_nm,
    )
