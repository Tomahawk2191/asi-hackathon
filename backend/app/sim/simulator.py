"""Propagate flights along their planned polylines at constant cruise."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache

import numpy as np

from ..data.sectors import load_sectors
from ..data.snapshots import load_routes
from .geo import cum_distances_nm, interpolate_along


@dataclass(frozen=True)
class FlightStatic:
    flight_number: str
    origin: str
    destination: str
    take_off_time: datetime
    scheduled_landing_time: datetime
    cruise_altitude_ft: int
    cruise_speed_kt: float
    lats: list[float]
    lons: list[float]
    cum_nm: np.ndarray
    total_nm: float
    is_airborne: bool


def _parse(t: str) -> datetime:
    return datetime.fromisoformat(t)


@lru_cache(maxsize=4)
def load_flights(snapshot_name: str) -> list[FlightStatic]:
    payload = load_routes(snapshot_name)
    out: list[FlightStatic] = []
    for f in payload["flights"]:
        lats = f["lats"]
        lons = f["lons"]
        if len(lats) < 2:
            continue
        cum = cum_distances_nm(lats, lons)
        out.append(FlightStatic(
            flight_number=f["flight_number"],
            origin=f["origin_airport_icao"],
            destination=f["destination_airport_icao"],
            take_off_time=_parse(f["take_off_time"]),
            scheduled_landing_time=_parse(f["scheduled_landing_time"]),
            cruise_altitude_ft=f["cruise_altitude_ft"],
            cruise_speed_kt=f["cruise_speed_kt"],
            lats=lats,
            lons=lons,
            cum_nm=cum,
            total_nm=float(cum[-1]),
            is_airborne=f["is_airborne"],
        ))
    return out


@dataclass(frozen=True)
class FlightPosition:
    flight_number: str
    origin: str
    destination: str
    lat: float
    lon: float
    altitude_ft: int
    heading_deg: float
    progress: float  # 0..1
    status: str      # "pre", "enroute", "landed"


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def flight_position_at(f: FlightStatic, t: datetime) -> FlightPosition:
    if t <= f.take_off_time:
        lat, lon = f.lats[0], f.lons[0]
        status = "pre"
    elif t >= f.scheduled_landing_time:
        lat, lon = f.lats[-1], f.lons[-1]
        status = "landed"
    else:
        elapsed_h = (t - f.take_off_time).total_seconds() / 3600.0
        dist_nm = elapsed_h * f.cruise_speed_kt
        lat, lon = interpolate_along(f.lats, f.lons, f.cum_nm, dist_nm)
        status = "enroute"
    # heading: from current point toward next waypoint (or destination if landed).
    if status == "enroute":
        # Find current segment.
        # Use the same dist to find next waypoint.
        elapsed_h = (t - f.take_off_time).total_seconds() / 3600.0
        d = elapsed_h * f.cruise_speed_kt
        # next waypoint = first cum > d
        idx = int(np.searchsorted(f.cum_nm, d, side="right"))
        idx = min(idx, len(f.lats) - 1)
        hdg = _bearing_deg(lat, lon, f.lats[idx], f.lons[idx])
    else:
        hdg = _bearing_deg(f.lats[0], f.lons[0], f.lats[-1], f.lons[-1])
    progress = 0.0 if f.total_nm == 0 else min(1.0, max(0.0,
        (t - f.take_off_time).total_seconds() / 3600.0 * f.cruise_speed_kt / f.total_nm))
    return FlightPosition(
        flight_number=f.flight_number,
        origin=f.origin,
        destination=f.destination,
        lat=lat, lon=lon,
        altitude_ft=f.cruise_altitude_ft,
        heading_deg=hdg,
        progress=progress,
        status=status,
    )


def positions_at(snapshot_name: str, t: datetime) -> list[FlightPosition]:
    flights = load_flights(snapshot_name)
    out: list[FlightPosition] = []
    for f in flights:
        if t < f.take_off_time or t > f.scheduled_landing_time:
            continue
        out.append(flight_position_at(f, t))
    return out


def sector_loads_at(snapshot_name: str, t: datetime) -> dict[str, int]:
    """Return {sector_name: count_of_flights_currently_in_it}."""
    from shapely.geometry import Point
    idx = load_sectors()
    positions = positions_at(snapshot_name, t)
    counts: dict[str, int] = {s.name: 0 for s in idx.sectors}
    for p in positions:
        from ..config import HIGH_FLOOR_FT
        if p.altitude_ft >= HIGH_FLOOR_FT:
            tree, sectors = idx.tree_high, idx.sectors_high
        else:
            tree, sectors = idx.tree_low, idx.sectors_low
        pt = Point(p.lon, p.lat)
        for i in tree.query(pt):
            s = sectors[i]
            if s.geom.contains(pt):
                counts[s.name] += 1
                break
    return counts
