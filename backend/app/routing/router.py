"""Great-circle baseline + local-detour router.

Old version was raw A* on a 0.5° CONUS grid: in clear sky it produced visually
ugly two-leg "stair-step" routes because A*'s 16-neighbor moves don't reproduce
a great circle.

New approach:
  1. Sample N waypoints along the true great circle from origin to destination.
  2. Walk that polyline. For each segment, ask "does this leg cross a cell we
     should avoid?" (high REFC below the echo top, OR an over-capacity sector
     at the ETA of the leg).
  3. If yes, find the next clear waypoint on the baseline and replace the bad
     run with a *bounded local* A* search between the last good waypoint and
     the next clear one. The local A* sees a finer grid in a bounded area so
     it produces a smooth-ish detour rather than a coast-to-coast stair.
  4. Densify the resulting polyline so no segment exceeds MAX_LEG_MINUTES.

Result: clear-sky LAX→JFK becomes a clean GC arc. Stormy days produce visible
detours around the cells, then snap back to the GC.
"""
from __future__ import annotations

import heapq
import math
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

# Baseline GC sampling: keep waypoints roughly every 50 nm.
BASELINE_WAYPOINT_NM = 50.0

# Densify the FINAL polyline so no leg > this many minutes (your "19 min" rule).
MAX_LEG_MINUTES = 19.0

# Local-detour A* bounded grid (in degrees, generous padding around the bad run).
LOCAL_GRID_STEP_DEG = 0.4
LOCAL_PADDING_DEG = 3.0

# 16-neighbor moves keep diagonals; smooth enough for local detours.
_DIRS = [(-1, -1), (-1, 0), (-1, 1),
         (0, -1),           (0, 1),
         (1, -1),  (1, 0),  (1, 1),
         (-2, -1), (-2, 1), (2, -1), (2, 1),
         (-1, -2), (-1, 2), (1, -2), (1, 2)]


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
    sectors_traversed: list[str]
    overloaded_sectors_hit: list[str]
    base_distance_nm: float
    detoured: bool  # True if any local detour was applied


# -----------------------------------------------------------------------------
# Great-circle math
# -----------------------------------------------------------------------------

def _gc_interpolate(lat1: float, lon1: float, lat2: float, lon2: float, f: float) -> tuple[float, float]:
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
    return math.degrees(math.atan2(z, math.sqrt(x * x + y * y))), math.degrees(math.atan2(y, x))


def _gc_polyline(lat1: float, lon1: float, lat2: float, lon2: float, waypoint_nm: float) -> tuple[list[float], list[float]]:
    total = haversine_nm(lat1, lon1, lat2, lon2)
    n = max(2, int(math.ceil(total / waypoint_nm)) + 1)
    lats = [0.0] * n
    lons = [0.0] * n
    for i in range(n):
        f = i / (n - 1)
        la, lo = _gc_interpolate(lat1, lon1, lat2, lon2, f)
        lats[i] = la
        lons[i] = lo
    return lats, lons


# -----------------------------------------------------------------------------
# Cell sampling helpers (REFC + sectors at a given time)
# -----------------------------------------------------------------------------

def _refc_max_in_box(refc: np.ndarray, lat: float, lon: float, box_pixels: int = 4) -> float:
    from ..config import LAT_MAX, LAT_MIN, LON_MAX, LON_MIN, ROWS, COLS
    if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
        return float("nan")
    row = int((LAT_MAX - lat) / (LAT_MAX - LAT_MIN) * ROWS)
    col = int((lon - LON_MIN) / (LON_MAX - LON_MIN) * COLS)
    r0 = max(0, row - box_pixels); r1 = min(ROWS, row + box_pixels + 1)
    c0 = max(0, col - box_pixels); c1 = min(COLS, col + box_pixels + 1)
    sub = refc[r0:r1, c0:c1]
    valid = sub[~np.isnan(sub)]
    return float(valid.max()) if valid.size else float("nan")


def _retop_at(retop: np.ndarray, lat: float, lon: float) -> float:
    from ..config import LAT_MAX, LAT_MIN, LON_MAX, LON_MIN, ROWS, COLS
    if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
        return float("nan")
    row = int((LAT_MAX - lat) / (LAT_MAX - LAT_MIN) * ROWS)
    col = int((lon - LON_MIN) / (LON_MAX - LON_MIN) * COLS)
    row = max(0, min(ROWS - 1, row))
    col = max(0, min(COLS - 1, col))
    return float(retop[row, col])


def _sector_for(lon: float, lat: float, alt_ft: float):
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


# -----------------------------------------------------------------------------
# "Is this point bad?" — used for both segment scanning and local A* costs.
# -----------------------------------------------------------------------------

class _CellEvaluator:
    """Lazily caches per-time-bucket REFC/RETOP/sector-load lookups."""
    def __init__(self, req: RouteRequest):
        self.req = req
        self._refc_cache: dict[datetime, Optional[np.ndarray]] = {}
        self._retop_cache: dict[datetime, Optional[np.ndarray]] = {}
        self._load_cache: dict[datetime, dict[str, int]] = {}

    def refc(self, at: datetime) -> Optional[np.ndarray]:
        s = pick_strip(self.req.snapshot, "refc", at)
        if s is None:
            return None
        if s.valid_from in self._refc_cache:
            return self._refc_cache[s.valid_from]
        m = mask_nodata("refc", load_strip_matrix(str(s.path)))
        self._refc_cache[s.valid_from] = m
        return m

    def retop(self, at: datetime) -> Optional[np.ndarray]:
        s = pick_strip(self.req.snapshot, "retop", at)
        if s is None:
            return None
        if s.valid_from in self._retop_cache:
            return self._retop_cache[s.valid_from]
        m = mask_nodata("retop", load_strip_matrix(str(s.path)))
        self._retop_cache[s.valid_from] = m
        return m

    def loads(self, at: datetime) -> dict[str, int]:
        bucket = at.replace(minute=(at.minute // 5) * 5, second=0, microsecond=0)
        if bucket in self._load_cache:
            return self._load_cache[bucket]
        d = sector_loads_at(self.req.snapshot, bucket)
        self._load_cache[bucket] = d
        return d

    def point_bad(self, lat: float, lon: float, eta: datetime) -> bool:
        """Is this (lat,lon) blocked at this time, at the request's cruise alt?"""
        if self.req.avoid_weather:
            r = self.refc(eta)
            t = self.retop(eta)
            if r is not None and t is not None:
                worst = _refc_max_in_box(r, lat, lon)
                if not math.isnan(worst) and worst >= 40.0:
                    top_ft = _retop_at(t, lat, lon)
                    if math.isnan(top_ft) or top_ft > self.req.cruise_altitude_ft:
                        return True
        if self.req.avoid_overloaded_sectors:
            s = _sector_for(lon, lat, self.req.cruise_altitude_ft)
            if s is not None:
                loads = self.loads(eta)
                if loads.get(s.name, 0) >= s.capacity:
                    return True
        return False


# -----------------------------------------------------------------------------
# Local A* (bounded) for detours
# -----------------------------------------------------------------------------

def _local_detour(
    req: RouteRequest,
    eval_: _CellEvaluator,
    start_lat: float, start_lon: float,
    end_lat: float, end_lon: float,
    depart_at: datetime,
) -> tuple[list[float], list[float]]:
    """A* on a bounded fine grid from start → end avoiding bad cells."""
    lat_min = min(start_lat, end_lat) - LOCAL_PADDING_DEG
    lat_max = max(start_lat, end_lat) + LOCAL_PADDING_DEG
    lon_min = min(start_lon, end_lon) - LOCAL_PADDING_DEG
    lon_max = max(start_lon, end_lon) + LOCAL_PADDING_DEG
    step = LOCAL_GRID_STEP_DEG

    def node_to_ll(i: int, j: int) -> tuple[float, float]:
        return lat_min + i * step, lon_min + j * step

    def ll_to_node(la: float, lo: float) -> tuple[int, int]:
        return (round((la - lat_min) / step), round((lo - lon_min) / step))

    n_lat = int(round((lat_max - lat_min) / step)) + 1
    n_lon = int(round((lon_max - lon_min) / step)) + 1
    start_node = ll_to_node(start_lat, start_lon)
    goal_node = ll_to_node(end_lat, end_lon)

    glat, glon = node_to_ll(*goal_node)

    def h(i: int, j: int) -> float:
        la, lo = node_to_ll(i, j)
        return haversine_nm(la, lo, glat, glon)

    PENALTY_NM = 600.0
    g_score = {start_node: 0.0}
    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    open_heap = [(h(*start_node), start_node)]
    closed: set[tuple[int, int]] = set()

    while open_heap:
        _, cur = heapq.heappop(open_heap)
        if cur == goal_node:
            break
        if cur in closed:
            continue
        closed.add(cur)
        clat, clon = node_to_ll(*cur)
        for di, dj in _DIRS:
            ni, nj = cur[0] + di, cur[1] + dj
            if not (0 <= ni < n_lat and 0 <= nj < n_lon):
                continue
            if (ni, nj) in closed:
                continue
            nlat, nlon = node_to_ll(ni, nj)
            leg = haversine_nm(clat, clon, nlat, nlon)
            so_far = g_score[cur]
            eta = depart_at + timedelta(hours=(so_far + leg) / req.cruise_speed_kt)
            cost = leg
            mlat, mlon = (clat + nlat) / 2, (clon + nlon) / 2
            if eval_.point_bad(mlat, mlon, eta) or eval_.point_bad(nlat, nlon, eta):
                cost += PENALTY_NM
            tentative = so_far + cost
            if tentative < g_score.get((ni, nj), float("inf")):
                came_from[(ni, nj)] = cur
                g_score[(ni, nj)] = tentative
                heapq.heappush(open_heap, (tentative + h(ni, nj), (ni, nj)))

    # Reconstruct
    if goal_node not in came_from and start_node != goal_node:
        # Fall back to straight GC if A* couldn't reach (very rare with padding).
        return [start_lat, end_lat], [start_lon, end_lon]
    path = [goal_node]
    cur = goal_node
    while cur != start_node:
        cur = came_from[cur]
        path.append(cur)
    path.reverse()
    lats = [start_lat] + [node_to_ll(i, j)[0] for (i, j) in path[1:-1]] + [end_lat]
    lons = [start_lon] + [node_to_ll(i, j)[1] for (i, j) in path[1:-1]] + [end_lon]
    return lats, lons


# -----------------------------------------------------------------------------
# Densify output
# -----------------------------------------------------------------------------

def _densify(lats: list[float], lons: list[float], speed_kt: float, max_minutes: float) -> tuple[list[float], list[float]]:
    if len(lats) < 2:
        return lats, lons
    out_lats = [lats[0]]; out_lons = [lons[0]]
    max_nm = speed_kt * (max_minutes / 60.0)
    for i in range(1, len(lats)):
        leg = haversine_nm(lats[i - 1], lons[i - 1], lats[i], lons[i])
        n_extra = max(0, int(math.ceil(leg / max_nm)) - 1)
        for k in range(1, n_extra + 1):
            f = k / (n_extra + 1)
            la, lo = _gc_interpolate(lats[i - 1], lons[i - 1], lats[i], lons[i], f)
            out_lats.append(la); out_lons.append(lo)
        out_lats.append(lats[i]); out_lons.append(lons[i])
    return out_lats, out_lons


# -----------------------------------------------------------------------------
# Plan
# -----------------------------------------------------------------------------

def plan(req: RouteRequest) -> RouteResult:
    eval_ = _CellEvaluator(req)

    # 1. GC baseline.
    base_lats, base_lons = _gc_polyline(
        req.origin_lat, req.origin_lon,
        req.dest_lat, req.dest_lon,
        BASELINE_WAYPOINT_NM,
    )

    # 2. Walk baseline, detect bad segments, splice in detours.
    out_lats: list[float] = [base_lats[0]]
    out_lons: list[float] = [base_lons[0]]
    detoured = False
    cum_nm = 0.0

    def eta_at(nm: float) -> datetime:
        return req.depart_at + timedelta(hours=nm / req.cruise_speed_kt)

    i = 1
    n = len(base_lats)
    while i < n:
        # Distance to current baseline waypoint, time we'd be there.
        seg_nm = haversine_nm(out_lats[-1], out_lons[-1], base_lats[i], base_lons[i])
        eta = eta_at(cum_nm + seg_nm)
        # Sample midpoint of the segment too.
        mlat = (out_lats[-1] + base_lats[i]) / 2.0
        mlon = (out_lons[-1] + base_lons[i]) / 2.0
        is_bad = (
            eval_.point_bad(base_lats[i], base_lons[i], eta)
            or eval_.point_bad(mlat, mlon, eta)
        )
        if not is_bad:
            out_lats.append(base_lats[i]); out_lons.append(base_lons[i])
            cum_nm += seg_nm
            i += 1
            continue

        # Bad: find the next clear waypoint along the baseline (skip the bad run).
        j = i + 1
        while j < n - 1:
            # The ETA at j is approximate (uses GC distance up to here).
            approx_eta = eta_at(cum_nm + haversine_nm(out_lats[-1], out_lons[-1], base_lats[j], base_lons[j]))
            if not eval_.point_bad(base_lats[j], base_lons[j], approx_eta):
                break
            j += 1
        target_lat = base_lats[j]
        target_lon = base_lons[j]
        # Detour from current position to target.
        d_lats, d_lons = _local_detour(
            req, eval_,
            out_lats[-1], out_lons[-1],
            target_lat, target_lon,
            eta_at(cum_nm),
        )
        # Skip the starting point (already in out), append the rest.
        for k in range(1, len(d_lats)):
            seg = haversine_nm(out_lats[-1], out_lons[-1], d_lats[k], d_lons[k])
            out_lats.append(d_lats[k]); out_lons.append(d_lons[k])
            cum_nm += seg
        detoured = True
        i = j + 1
        # Continue baseline walk from j+1 onward (already at base[j]).

    # Ensure exact destination, deduped.
    if abs(out_lats[-1] - req.dest_lat) > 1e-9 or abs(out_lons[-1] - req.dest_lon) > 1e-9:
        out_lats.append(req.dest_lat); out_lons.append(req.dest_lon)

    # 3. Densify so no leg exceeds 19 min.
    out_lats, out_lons = _densify(out_lats, out_lons, req.cruise_speed_kt, MAX_LEG_MINUTES)
    # Final cleanup: drop any consecutive duplicates introduced by densify.
    deduped_lats: list[float] = [out_lats[0]]
    deduped_lons: list[float] = [out_lons[0]]
    for k in range(1, len(out_lats)):
        if abs(out_lats[k] - deduped_lats[-1]) > 1e-7 or abs(out_lons[k] - deduped_lons[-1]) > 1e-7:
            deduped_lats.append(out_lats[k]); deduped_lons.append(out_lons[k])
    out_lats, out_lons = deduped_lats, deduped_lons

    # 4. Totals.
    total_nm = sum(
        haversine_nm(out_lats[i - 1], out_lons[i - 1], out_lats[i], out_lons[i])
        for i in range(1, len(out_lats))
    )
    base_nm = haversine_nm(req.origin_lat, req.origin_lon, req.dest_lat, req.dest_lon)
    eta_h = total_nm / req.cruise_speed_kt

    # Sector traversal & overload hit summary.
    sectors_traversed: list[str] = []
    seen: set[str] = set()
    overload_hit: set[str] = set()
    running_nm = 0.0
    for k in range(len(out_lats)):
        if k > 0:
            running_nm += haversine_nm(out_lats[k - 1], out_lons[k - 1], out_lats[k], out_lons[k])
        eta = eta_at(running_nm)
        s = _sector_for(out_lons[k], out_lats[k], req.cruise_altitude_ft)
        if s and s.name not in seen:
            sectors_traversed.append(s.name); seen.add(s.name)
        if s:
            loads = eval_.loads(eta)
            if loads.get(s.name, 0) >= s.capacity:
                overload_hit.add(s.name)

    return RouteResult(
        lats=out_lats, lons=out_lons,
        total_nm=total_nm, eta_hours=eta_h,
        sectors_traversed=sectors_traversed,
        overloaded_sectors_hit=sorted(overload_hit),
        base_distance_nm=base_nm,
        detoured=detoured,
    )
