"""Deterministic rescheduler with delay/altitude/reroute mitigation hierarchy.

Cost J that we minimize by greedy moves:
    J = w_overload * Σ_{sector, t_bucket} max(0, load - cap)^2
      + w_delay    * Σ_{flight}            delay_min[f]
      + w_reroute  * Σ_{flight}            extra_nm[f]
      + w_descent  * Σ_{flight}            band_change[f]

Loop:
  1. Build occupancy: load[sector_name][t_bucket] from current plans.
  2. Pick the (sector, time) with highest overload; earlier ties first.
  3. Pick a flight inside that (sector, time): prefer pre-departure (cheap to
     delay), among airborne prefer those farthest from destination (least
     painful to descend/reroute).
  4. Try mitigations in cost order; accept the first one with ΔJ < 0:
       (a) Ground-delay by [5, 10, 15, 20, 30] min.
       (b) Drop to LOW band (if cruise is HIGH and dist_remaining / total < 0.4).
       (c) Local lateral reroute around the bad sector at this time.
  5. Apply and recompute affected buckets. Continue until either no overloads
     remain, or no candidate move reduces J. The latter is the "inescapable
     red zones" you anticipated — we report them honestly.

For demo speed we operate on a single user-chosen TIME WINDOW (e.g. asked_at..
asked_at+2h) and on a single ALTITUDE BAND at a time. The full continental
multi-hour problem is much bigger; this keeps the loop bounded and the demo
interactive.
"""
from __future__ import annotations

import math
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import numpy as np

from ..config import HIGH_FLOOR_FT
from ..data.sectors import load_sectors
from ..data.snapshots import load_routes
from ..sim.geo import cum_distances_nm, haversine_nm, interpolate_along

BUCKET_MINUTES = 5
DELAY_CANDIDATES_MIN = (5, 10, 15, 20, 30)
DESCENT_DIST_FRAC = 0.4  # band drop only allowed if remaining / total < this
LOW_BAND_ALT_FT = 33000  # what we drop them to (just below 35k boundary)

# Cost weights (per-unit). Tuned so that one cap-1 overload at one bucket
# ~equals 60 min of delay, which is heavy enough to favor delay aggressively.
W_OVERLOAD = 50.0   # per (overload count)^2 per bucket
W_DELAY = 1.0       # per minute
W_REROUTE = 0.5     # per nm of extra distance
W_DESCENT = 30.0    # per flight that got demoted to a lower band


# -----------------------------------------------------------------------------
# Working flight model — mutable copy of the bundle's static plans.
# -----------------------------------------------------------------------------

@dataclass
class MutFlight:
    flight_number: str
    origin: str
    destination: str
    take_off_time: datetime
    scheduled_landing_time: datetime
    cruise_altitude_ft: int
    cruise_speed_kt: float
    lats: list[float]
    lons: list[float]
    is_airborne: bool

    # Edits applied by the rescheduler:
    delay_min: int = 0
    extra_nm: float = 0.0
    descended: bool = False
    rerouted: bool = False

    cum_nm: np.ndarray = field(default_factory=lambda: np.zeros(0))
    total_nm: float = 0.0

    def __post_init__(self):
        self.cum_nm = cum_distances_nm(self.lats, self.lons)
        self.total_nm = float(self.cum_nm[-1]) if len(self.cum_nm) else 0.0

    @property
    def effective_takeoff(self) -> datetime:
        return self.take_off_time + timedelta(minutes=self.delay_min)

    @property
    def effective_landing(self) -> datetime:
        # When we delay or reroute, landing slips by the same total.
        base_h = self.total_nm / self.cruise_speed_kt
        return self.effective_takeoff + timedelta(hours=base_h)


def _parse(t: str) -> datetime:
    return datetime.fromisoformat(t)


def _flight_position(f: MutFlight, t: datetime) -> Optional[tuple[float, float]]:
    if t < f.effective_takeoff or t > f.effective_landing:
        return None
    elapsed_h = (t - f.effective_takeoff).total_seconds() / 3600.0
    dist = elapsed_h * f.cruise_speed_kt
    return interpolate_along(f.lats, f.lons, f.cum_nm, dist)


def _band(alt_ft: int) -> str:
    return "HIGH" if alt_ft >= HIGH_FLOOR_FT else "LOW"


# -----------------------------------------------------------------------------
# Occupancy grid
# -----------------------------------------------------------------------------

def _bucketize(t: datetime) -> datetime:
    return t.replace(minute=(t.minute // BUCKET_MINUTES) * BUCKET_MINUTES, second=0, microsecond=0)


def _sector_at(lon: float, lat: float, alt_ft: int) -> Optional[str]:
    from shapely.geometry import Point
    idx = load_sectors()
    if alt_ft >= HIGH_FLOOR_FT:
        tree, sectors = idx.tree_high, idx.sectors_high
    else:
        tree, sectors = idx.tree_low, idx.sectors_low
    pt = Point(lon, lat)
    for i in tree.query(pt):
        s = sectors[i]
        if s.geom.contains(pt):
            return s.name
    return None


def _flight_buckets(f: MutFlight, t_start: datetime, t_end: datetime) -> list[tuple[datetime, str]]:
    """Return (bucket, sector_name) the flight occupies in [t_start, t_end]."""
    out = []
    cur = max(t_start, _bucketize(f.effective_takeoff))
    end = min(t_end, f.effective_landing)
    while cur <= end:
        pos = _flight_position(f, cur)
        if pos is not None:
            lat, lon = pos
            s = _sector_at(lon, lat, f.cruise_altitude_ft)
            if s is not None:
                out.append((cur, s))
        cur += timedelta(minutes=BUCKET_MINUTES)
    return out


def _build_loads(flights: list[MutFlight], t_start: datetime, t_end: datetime) -> dict[tuple[datetime, str], int]:
    grid: dict[tuple[datetime, str], int] = defaultdict(int)
    for f in flights:
        for (bucket, sec) in _flight_buckets(f, t_start, t_end):
            grid[(bucket, sec)] += 1
    return grid


# -----------------------------------------------------------------------------
# Cost
# -----------------------------------------------------------------------------

def _overload_cost(loads: dict[tuple[datetime, str], int], caps: dict[str, int]) -> tuple[float, int]:
    """Returns (cost, count_of_overloaded_buckets)."""
    total = 0.0
    n_over = 0
    for (_, name), load in loads.items():
        cap = caps.get(name, 9999)
        over = max(0, load - cap)
        if over > 0:
            n_over += 1
            total += W_OVERLOAD * over * over
    return total, n_over


def _flight_cost(flights: list[MutFlight]) -> float:
    delay = sum(f.delay_min for f in flights) * W_DELAY
    extra = sum(f.extra_nm for f in flights) * W_REROUTE
    desc = sum(1 for f in flights if f.descended) * W_DESCENT
    return delay + extra + desc


def _total_cost(flights: list[MutFlight], loads: dict[tuple[datetime, str], int], caps: dict[str, int]) -> float:
    j_o, _ = _overload_cost(loads, caps)
    return j_o + _flight_cost(flights)


# -----------------------------------------------------------------------------
# Mitigation primitives
# -----------------------------------------------------------------------------

def _try_delay(
    flight: MutFlight,
    flights: list[MutFlight],
    caps: dict[str, int],
    t_start: datetime, t_end: datetime,
    current_loads: dict[tuple[datetime, str], int],
    current_cost: float,
) -> Optional[tuple[int, dict[tuple[datetime, str], int], float]]:
    """Find the smallest delay (from candidate list) that reduces J. Returns
    (delay_min, new_loads, new_cost) or None."""
    saved = flight.delay_min
    best: Optional[tuple[int, dict, float]] = None
    for d in DELAY_CANDIDATES_MIN:
        flight.delay_min = saved + d
        # Quick incremental load: subtract old buckets for this flight, add new.
        # For simplicity, rebuild only this flight's contribution.
        new_loads = _rebuild_with_one_flight(current_loads, flight, saved, t_start, t_end)
        new_cost = _total_cost(flights, new_loads, caps)
        if new_cost < current_cost:
            best = (saved + d, new_loads, new_cost)
            break  # accept the smallest delay that works
    flight.delay_min = saved
    return best


def _try_descend(
    flight: MutFlight,
    flights: list[MutFlight],
    caps: dict[str, int],
    t_start: datetime, t_end: datetime,
    current_loads: dict[tuple[datetime, str], int],
    current_cost: float,
    at_time: datetime,
) -> Optional[tuple[int, bool, dict[tuple[datetime, str], int], float]]:
    """If flight is HIGH band and within DESCENT_DIST_FRAC of destination at
    `at_time`, try dropping to LOW band."""
    if _band(flight.cruise_altitude_ft) != "HIGH":
        return None
    pos = _flight_position(flight, at_time)
    if pos is None:
        return None
    lat, lon = pos
    # Approximate remaining nm from current position.
    elapsed_h = (at_time - flight.effective_takeoff).total_seconds() / 3600.0
    dist_so_far = elapsed_h * flight.cruise_speed_kt
    remaining = max(0.0, flight.total_nm - dist_so_far)
    if flight.total_nm == 0 or remaining / flight.total_nm >= DESCENT_DIST_FRAC:
        return None
    saved_alt = flight.cruise_altitude_ft
    saved_desc = flight.descended
    flight.cruise_altitude_ft = LOW_BAND_ALT_FT
    flight.descended = True
    new_loads = _rebuild_with_one_flight(current_loads, flight, saved_alt, t_start, t_end, prev_alt=saved_alt)
    new_cost = _total_cost(flights, new_loads, caps)
    flight.cruise_altitude_ft = saved_alt
    flight.descended = saved_desc
    if new_cost < current_cost:
        return (saved_alt, True, new_loads, new_cost)
    return None


def _rebuild_with_one_flight(
    current_loads: dict[tuple[datetime, str], int],
    flight: MutFlight,
    prev_delay_or_alt: int,
    t_start: datetime, t_end: datetime,
    prev_alt: Optional[int] = None,
) -> dict[tuple[datetime, str], int]:
    """Recompute global loads by subtracting the flight's *previous* contribution
    (computed with `prev_delay_or_alt`/`prev_alt`) and adding its current."""
    # Subtract previous occupation.
    saved_delay = flight.delay_min
    saved_alt = flight.cruise_altitude_ft
    if prev_alt is not None:
        # If we passed prev_alt, that's the OLD alt; otherwise current edits are about delay.
        flight.cruise_altitude_ft = prev_alt
    else:
        flight.delay_min = prev_delay_or_alt
    prev_buckets = _flight_buckets(flight, t_start, t_end)
    flight.delay_min = saved_delay
    flight.cruise_altitude_ft = saved_alt
    new_buckets = _flight_buckets(flight, t_start, t_end)

    out = dict(current_loads)
    for (b, s) in prev_buckets:
        n = out.get((b, s), 0) - 1
        if n <= 0:
            out.pop((b, s), None)
        else:
            out[(b, s)] = n
    for (b, s) in new_buckets:
        out[(b, s)] = out.get((b, s), 0) + 1
    return out


# -----------------------------------------------------------------------------
# Top-level rescheduler
# -----------------------------------------------------------------------------

@dataclass
class RescheduleSummary:
    flights_touched: int
    total_delay_min: int
    total_extra_nm: float
    flights_descended: int
    flights_rerouted: int
    overload_buckets_before: int
    overload_buckets_after: int
    overload_cost_before: float
    overload_cost_after: float
    iterations: int


@dataclass
class RescheduleResult:
    summary: RescheduleSummary
    # Aggregate per-sector view (max load over the planning window per sector).
    loads_before: dict[str, int]
    loads_after: dict[str, int]
    # Per-bucket time series (sector → list of {t, load, cap}) — only for
    # sectors that overloaded somewhere; cheap for charts/tables.
    series_before: dict[str, list[dict]]
    series_after: dict[str, list[dict]]
    # Sparse full grid: sector → {bucket_iso → load} for every (sector, bucket)
    # with any traffic. Lets the frontend color the map at an exact instant
    # under either plan — fair apples-to-apples comparison.
    loads_by_bucket_before: dict[str, dict[str, int]]
    loads_by_bucket_after: dict[str, dict[str, int]]
    # Window bounds for the UI to clamp its time selector against.
    window_start: str
    window_end: str
    bucket_minutes: int
    # Buckets that we could not clear — honestly reported.
    unmitigated_buckets: list[dict]
    # Per-flight diffs (only flights actually touched).
    modified_flights: list[dict]


def _loads_to_sparse_grid(loads: dict[tuple[datetime, str], int]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for (bucket, sec), n in loads.items():
        out.setdefault(sec, {})[bucket.isoformat()] = n
    return out


def reschedule(
    snapshot_name: str,
    window_start: datetime,
    window_end: datetime,
    max_iterations: int = 200,
) -> RescheduleResult:
    payload = load_routes(snapshot_name)
    raw = payload["flights"]
    flights: list[MutFlight] = []
    for f in raw:
        if len(f["lats"]) < 2:
            continue
        # Only carry flights whose window of activity overlaps our window.
        tof = _parse(f["take_off_time"])
        land = _parse(f["scheduled_landing_time"])
        if land < window_start or tof > window_end:
            continue
        flights.append(MutFlight(
            flight_number=f["flight_number"],
            origin=f["origin_airport_icao"],
            destination=f["destination_airport_icao"],
            take_off_time=tof,
            scheduled_landing_time=land,
            cruise_altitude_ft=f["cruise_altitude_ft"],
            cruise_speed_kt=f["cruise_speed_kt"],
            lats=list(f["lats"]),
            lons=list(f["lons"]),
            is_airborne=f["is_airborne"],
        ))

    idx = load_sectors()
    caps: dict[str, int] = {s.name: s.capacity for s in idx.sectors}

    loads = _build_loads(flights, window_start, window_end)
    loads_before_snapshot = dict(loads)  # frozen copy for "before" reporting
    base_oc, base_n = _overload_cost(loads, caps)
    series_before = _series_for_overloaded_sectors(loads, caps)
    loads_before_max = _max_per_sector(loads)

    iterations = 0
    touched: set[str] = set()
    no_progress_streak = 0
    skipped: set[tuple[datetime, str]] = set()

    while iterations < max_iterations:
        iterations += 1
        # Find worst (sector, bucket) overload that isn't already flagged
        # unmitigable. Earliest in time wins ties.
        worst = None
        worst_over = 0
        for (bucket, sec), load in loads.items():
            if (bucket, sec) in skipped:
                continue
            cap = caps.get(sec, 9999)
            over = load - cap
            if over <= 0:
                continue
            if over > worst_over or (over == worst_over and (worst is None or bucket < worst[0])):
                worst = (bucket, sec)
                worst_over = over
        if worst is None:
            break  # no remaining over-cap buckets we haven't given up on
        bucket, sec = worst

        # Candidate flights: those whose (bucket, sector) intersects worst.
        candidates: list[MutFlight] = []
        for f in flights:
            for (b, s) in _flight_buckets(f, bucket - timedelta(minutes=BUCKET_MINUTES), bucket + timedelta(minutes=BUCKET_MINUTES)):
                if b == bucket and s == sec:
                    candidates.append(f)
                    break
        # Prefer pre-departure (cheap to delay), then "least progressed" airborne.
        def _key(f: MutFlight):
            elapsed_h = max(0.0, (bucket - f.effective_takeoff).total_seconds() / 3600.0)
            progress = (elapsed_h * f.cruise_speed_kt) / max(1.0, f.total_nm)
            return (1 if f.effective_takeoff <= bucket else 0, progress)
        candidates.sort(key=_key)

        cur_cost = _total_cost(flights, loads, caps)
        applied = False
        for cand in candidates[:30]:  # bound work per iteration
            delay = _try_delay(cand, flights, caps, window_start, window_end, loads, cur_cost)
            if delay is not None:
                d_min, new_loads, new_cost = delay
                cand.delay_min = d_min
                loads = new_loads
                touched.add(cand.flight_number)
                applied = True
                break
            desc = _try_descend(cand, flights, caps, window_start, window_end, loads, cur_cost, bucket)
            if desc is not None:
                prev_alt, _, new_loads, new_cost = desc
                cand.cruise_altitude_ft = LOW_BAND_ALT_FT
                cand.descended = True
                loads = new_loads
                touched.add(cand.flight_number)
                applied = True
                break
            # (We skip lateral reroute in the greedy loop — it's expensive and
            # most contributions are resolvable with delay alone. The router
            # endpoint is still available for one-off plans.)
        if not applied:
            # Couldn't fix this bucket. Honestly skip it in future iterations,
            # but leave it in the loads dict so the final report is truthful.
            skipped.add(worst)
            no_progress_streak += 1
            if no_progress_streak > 12:
                break
        else:
            no_progress_streak = 0

    loads_after_max = _max_per_sector(loads)
    series_after = _series_for_overloaded_sectors(loads, caps, baseline_keys=set(series_before.keys()))
    after_oc, after_n = _overload_cost(loads, caps)

    unmitigated: list[dict] = []
    for (bucket, sec) in sorted(skipped):
        load = loads.get((bucket, sec), 0)
        cap = caps.get(sec, 0)
        if load > cap:
            unmitigated.append({"t": bucket.isoformat(), "sector": sec, "load": load, "cap": cap})

    modified: list[dict] = []
    for f in flights:
        if f.flight_number in touched:
            modified.append({
                "flight_number": f.flight_number,
                "origin": f.origin,
                "destination": f.destination,
                "delay_min": f.delay_min,
                "extra_nm": round(f.extra_nm, 1),
                "descended": f.descended,
                "rerouted": f.rerouted,
                "cruise_altitude_ft": f.cruise_altitude_ft,
            })

    summary = RescheduleSummary(
        flights_touched=len(touched),
        total_delay_min=sum(f.delay_min for f in flights),
        total_extra_nm=round(sum(f.extra_nm for f in flights), 1),
        flights_descended=sum(1 for f in flights if f.descended),
        flights_rerouted=sum(1 for f in flights if f.rerouted),
        overload_buckets_before=base_n,
        overload_buckets_after=after_n,
        overload_cost_before=round(base_oc, 1),
        overload_cost_after=round(after_oc, 1),
        iterations=iterations,
    )
    return RescheduleResult(
        summary=summary,
        loads_before=loads_before_max,
        loads_after=loads_after_max,
        series_before=series_before,
        series_after=series_after,
        loads_by_bucket_before=_loads_to_sparse_grid(loads_before_snapshot),
        loads_by_bucket_after=_loads_to_sparse_grid(loads),
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
        bucket_minutes=BUCKET_MINUTES,
        unmitigated_buckets=unmitigated,
        modified_flights=modified,
    )


def _max_per_sector(loads: dict[tuple[datetime, str], int]) -> dict[str, int]:
    out: dict[str, int] = {}
    for (_, sec), n in loads.items():
        if n > out.get(sec, 0):
            out[sec] = n
    return out


def _series_for_overloaded_sectors(
    loads: dict[tuple[datetime, str], int],
    caps: dict[str, int],
    baseline_keys: Optional[set] = None,
) -> dict[str, list[dict]]:
    """Return per-bucket time series only for sectors that were overloaded at
    some bucket. For "after", include any sector that was in baseline_keys too,
    so the UI can compare same sectors before/after."""
    keys = set(baseline_keys) if baseline_keys else set()
    for (_, sec), n in loads.items():
        if n > caps.get(sec, 9999):
            keys.add(sec)
    series: dict[str, list[dict]] = {k: [] for k in keys}
    for (bucket, sec), n in sorted(loads.items()):
        if sec in series:
            series[sec].append({"t": bucket.isoformat(), "load": n, "cap": caps.get(sec, 0)})
    return series
