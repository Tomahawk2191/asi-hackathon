"""FastAPI backend for the ASI hackathon air-traffic tools.

Exposes the sector landing-count helper over HTTP: given a set of sectors and
a scenario snapshot, return how many flights land in that region, grouped by
arrival airport.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional

import capacity
import db
import nyc
import population as population_mod
import uvicorn
import weather as weather_mod
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from flights import RoutesSnapshot
from loaders import load_routes
from pydantic import BaseModel, Field
from sectors import Sector, flights_landing_per_airport, load_sectors

ROOT = Path(__file__).resolve().parent.parent
SECTORS_PATH = ROOT / "data" / "sectors.geojson"
BUNDLE = ROOT / "data" / "nyc_dataset"
DB_PATH = Path(os.environ.get("ARRIVALS_DB") or db.DEFAULT_DB_PATH)

app = FastAPI(title="ASI Hackathon API")

app.add_middleware(
    CORSMiddleware,
    # Allow the Vite dev server on any localhost port (it falls back to 5174+
    # when 5173 is taken), plus 127.0.0.1.
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- cached data access ------------------------------------------------------


@lru_cache(maxsize=1)
def get_sectors() -> dict[str, Sector]:
    """Load the shared sectors file once, indexed by name."""
    return {s.name: s for s in load_sectors(SECTORS_PATH)}


def _scenario_name(path: Path) -> str:
    """Scenario id for a snapshot file: the ``<date>`` in ``nyc_<date>.json``.

    Strips the ``nyc_`` prefix and the ``.json`` / ``.json.gz`` suffix, so
    ``nyc_2025-08-21.json`` -> ``2025-08-21``.
    """
    name = path.name
    for suffix in (".json.gz", ".json"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name[len("nyc_"):] if name.startswith("nyc_") else name


def _scenario_files() -> dict[str, Path]:
    """Map scenario id -> snapshot file for every ``nyc_<date>`` file present.

    Recognizes both plain ``.json`` and gzipped ``.json.gz`` snapshots.
    """
    if not BUNDLE.exists():
        return {}
    files: dict[str, Path] = {}
    for path in BUNDLE.iterdir():
        name = path.name
        if path.is_file() and name.startswith("nyc_") and (
            name.endswith(".json") or name.endswith(".json.gz")
        ):
            files[_scenario_name(path)] = path
    return files


def list_scenarios() -> list[str]:
    """Available scenario ids -- the ``<date>`` of each ``nyc_<date>`` snapshot."""
    return sorted(_scenario_files())


def default_scenario() -> Optional[str]:
    scenarios = list_scenarios()
    return scenarios[0] if scenarios else None


def _routes_path(scenario: str) -> Path:
    """Locate a scenario's snapshot file (plain or gzipped)."""
    files = _scenario_files()
    if scenario not in files:
        raise FileNotFoundError(f"No routes file found for scenario {scenario!r}")
    return files[scenario]


@lru_cache(maxsize=None)
def get_snapshot(scenario: str) -> RoutesSnapshot:
    """Load and cache a scenario's routes snapshot."""
    return load_routes(_routes_path(scenario))


# --- request / response models ----------------------------------------------


class LandingsRequest(BaseModel):
    sector_names: list[str] = Field(
        description="Sectors defining the region, e.g. ['LOW_295'].",
        min_length=1,
    )
    scenario: Optional[str] = Field(
        default=None,
        description="Scenario id, a YYYY-MM-DD date (see GET /scenarios). "
        "Defaults to the earliest available scenario.",
    )


class LandingsResponse(BaseModel):
    scenario: str = Field(description="Scenario the counts were computed against.")
    sector_names: list[str] = Field(description="Sectors that were queried.")
    total_flights: int = Field(
        description="Total flights landing anywhere in the sector set."
    )
    per_airport: dict[str, int] = Field(
        description="Arrival airport ICAO -> landing count, sorted high to low."
    )


# --- core --------------------------------------------------------------------


def compute_landings(
    sector_names: list[str], scenario: Optional[str]
) -> LandingsResponse:
    """Resolve inputs, run the helper, and shape the response.

    Raises HTTPException(400/404) for empty/unknown sectors or scenarios.
    """
    if not sector_names:
        raise HTTPException(status_code=400, detail="Provide at least one sector name.")

    scenario = scenario or default_scenario()
    if scenario is None:
        raise HTTPException(
            status_code=400,
            detail="No scenario given and none found in the data bundle.",
        )
    available = list_scenarios()
    if scenario not in available:
        raise HTTPException(
            status_code=404,
            detail={"error": f"Unknown scenario {scenario!r}.", "available": available},
        )

    index = get_sectors()
    unknown = [name for name in sector_names if name not in index]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail={"error": "Unknown sector name(s).", "unknown": unknown},
        )
    chosen = [index[name] for name in sector_names]

    counts = flights_landing_per_airport(chosen, get_snapshot(scenario))
    ordered = dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
    return LandingsResponse(
        scenario=scenario,
        sector_names=sector_names,
        total_flights=sum(ordered.values()),
        per_airport=ordered,
    )


# --- endpoints ---------------------------------------------------------------


@app.get("/")
def root():
    return {"message": "Hello from FastAPI"}


@app.get("/scenarios")
def scenarios():
    """List the available scenario snapshots."""
    return {"scenarios": list_scenarios(), "default": default_scenario()}


@app.get("/scenarios/{scenario}/routes", response_model=RoutesSnapshot)
def scenario_routes(scenario: str):
    """Full routes snapshot for a scenario: every flight with its planned path.

    This is the per-flight geometry (waypoint ``lats`` / ``lons``, times,
    origin/destination, altitude) the frontend animates on the map. Served
    straight from the cached snapshot for the given scenario id (a YYYY-MM-DD
    date from GET /scenarios).
    """
    available = list_scenarios()
    if scenario not in available:
        raise HTTPException(
            status_code=404,
            detail={"error": f"Unknown scenario {scenario!r}.", "available": available},
        )
    return get_snapshot(scenario)


@app.get("/sectors")
def sectors_summary():
    """Summarize the sectors (name, band, capacity) for picking names."""
    index = get_sectors()
    return {
        "count": len(index),
        "sectors": [
            {
                "name": s.name,
                "altitude_from_ft": s.altitude_from_ft,
                "altitude_to_ft": s.altitude_to_ft,
                "capacity": s.capacity,
            }
            for s in index.values()
        ],
    }


@lru_cache(maxsize=1)
def _sectors_geojson() -> dict:
    """The raw sectors GeoJSON FeatureCollection, loaded once."""
    return json.loads(SECTORS_PATH.read_text())


@app.get("/sectors/geojson")
def sectors_geojson(band: Optional[str] = Query(default=None, description="LOW or HIGH")):
    """Sector polygons as GeoJSON, optionally filtered to one band (LOW/HIGH).

    The map needs the actual geometry, which GET /sectors omits. The frontend
    uses ``?band=LOW`` since landings happen at ground level.
    """
    gj = _sectors_geojson()
    features = gj.get("features", [])
    if band:
        prefix = band.upper()
        features = [
            f for f in features
            if str(f.get("properties", {}).get("name", "")).startswith(prefix)
        ]
    return {"type": "FeatureCollection", "features": features}


# --- weather polygons --------------------------------------------------------


@app.get("/weather")
def weather(scenario: Optional[str] = Query(default=None)):
    """Convective weather cells (boundary polygons) for a scenario, as GeoJSON.

    Synthetic but deterministic per scenario date — no radar field, just the
    cell outlines with a ``severity`` (1-3) / ``level`` property.
    """
    scenario = scenario or default_scenario()
    if scenario is None:
        raise HTTPException(status_code=400, detail="No scenario available.")
    available = list_scenarios()
    if scenario not in available:
        raise HTTPException(
            status_code=404,
            detail={"error": f"Unknown scenario {scenario!r}.", "available": available},
        )
    return weather_mod.generate_weather(scenario)


# --- sector population (live occupancy) -------------------------------------


def _band_sectors(band: str) -> list[Sector]:
    """Sectors in one altitude band: LOW = [0, 35000), HIGH = [35000, 60000)."""
    is_low = band == "LOW"
    return [
        s for s in get_sectors().values()
        if (s.altitude_from_ft < population_mod.BAND_CEIL_FT) == is_low
    ]


@app.get("/sectors/population")
def sectors_population(
    time: str = Query(description="ISO-8601 instant, e.g. 2025-08-21T18:03:00Z."),
    scenario: Optional[str] = Query(default=None),
    band: str = Query(default="LOW", description="Altitude band: LOW or HIGH."),
):
    """How many flights occupy each sector at ``time``, for one altitude band.

    Horizontal position is interpolated along each flight's route; altitude is
    modelled (climb/cruise/descent) to pick the band. Returns only occupied
    sectors with their capacity, busiest first.
    """
    band = band.upper()
    if band not in ("LOW", "HIGH"):
        raise HTTPException(status_code=400, detail="band must be LOW or HIGH.")

    scenario = scenario or default_scenario()
    if scenario is None:
        raise HTTPException(status_code=400, detail="No scenario available.")
    available = list_scenarios()
    if scenario not in available:
        raise HTTPException(
            status_code=404,
            detail={"error": f"Unknown scenario {scenario!r}.", "available": available},
        )

    when = _parse_time(time)
    band_sectors = _band_sectors(band)
    counts = population_mod.sector_population(get_snapshot(scenario), band_sectors, when, band)

    index = get_sectors()
    rows = [
        {
            "name": name,
            "count": count,
            "capacity": index[name].capacity,
            "ratio": round(count / index[name].capacity, 3) if index[name].capacity else 0.0,
        }
        for name, count in counts.most_common()
    ]
    return {
        "scenario": scenario,
        "time": when.isoformat(),
        "band": band,
        "total": sum(counts.values()),
        "occupied": len(rows),
        "sectors": rows,
    }


@app.post("/landings", response_model=LandingsResponse)
def landings(req: LandingsRequest):
    """Flights landing in a set of sectors, grouped by arrival airport."""
    return compute_landings(req.sector_names, req.scenario)


@app.get("/landings", response_model=LandingsResponse)
def landings_get(
    sectors: list[str] = Query(
        default=[],
        description="Repeat to pass several, e.g. ?sectors=LOW_295&sectors=LOW_296",
    ),
    scenario: Optional[str] = Query(default=None),
):
    """Convenience GET form of POST /landings for quick manual testing."""
    return compute_landings(sectors, scenario)


# --- NYC arrival-frequency refresh ------------------------------------------


class RefreshRequest(BaseModel):
    day: Optional[str] = Field(
        default=None,
        description="Day to refresh as YYYY-MM-DD (see GET /scenarios or the "
        "nyc_dataset). Omit to refresh every available NYC day.",
    )


def _refresh(day: Optional[str]) -> dict:
    """Compute NYC arrival & departure frequency from local files into SQLite."""
    available = nyc.available_days()
    if not available:
        raise HTTPException(status_code=500, detail="No NYC dataset files found.")
    if day is not None and day not in available:
        raise HTTPException(
            status_code=404,
            detail={"error": f"Unknown day {day!r}.", "available": available},
        )
    days = [day] if day is not None else available

    sector_list = list(get_sectors().values())
    conn = db.connect(DB_PATH)
    try:
        refreshed = []
        for d in days:
            snapshot = load_routes(nyc.day_file(d))
            entry: dict = {"day": d}
            for direction in nyc.DIRECTIONS.values():
                rows = nyc.flight_frequency(snapshot, sector_list, direction)
                written = db.write_day(conn, d, direction.name, rows)
                entry[f"{direction.name}s"] = {
                    "rows": written,
                    "flights": sum(r["flight_count"] for r in rows),
                }
            refreshed.append(entry)
    finally:
        conn.close()
    return {
        "db_path": str(DB_PATH),
        "refreshed": refreshed,
        "total_flights": sum(
            v["flights"] for e in refreshed for k, v in e.items() if k != "day"
        ),
    }


@app.post("/refresh")
def refresh(req: RefreshRequest):
    """Build the 5-min NYC arrival & departure frequency for a day (or all days).

    Reads only local bundle files and writes the result to the SQLite DB.
    """
    return _refresh(req.day)


@app.get("/refresh")
def refresh_get(day: Optional[str] = Query(default=None)):
    """Convenience GET form of POST /refresh."""
    return _refresh(day)


def _read_frequency(day: str, direction: str, sector: Optional[str]) -> dict:
    """Read back stored frequency rows for one (day, direction)."""
    conn = db.connect(DB_PATH)
    try:
        rows = db.read_day(conn, day, direction, sector)
    finally:
        conn.close()
    return {
        "day": day,
        "direction": direction,
        "sector": sector,
        "count": len(rows),
        "rows": rows,
    }


@app.get("/arrivals")
def arrivals(
    day: str = Query(description="Day to read, YYYY-MM-DD (must be refreshed first)."),
    sector: Optional[str] = Query(default=None, description="Optional sector filter."),
):
    """Read back stored arrival frequency for a day (optionally one sector)."""
    return _read_frequency(day, "arrival", sector)


@app.get("/departures")
def departures(
    day: str = Query(description="Day to read, YYYY-MM-DD (must be refreshed first)."),
    sector: Optional[str] = Query(default=None, description="Optional sector filter."),
):
    """Read back stored departure frequency for a day (optionally one sector)."""
    return _read_frequency(day, "departure", sector)


# --- flight counts at the closest stored time (inbound / departure) ---------


class FlightsInboundRequest(BaseModel):
    airports: list[str] = Field(
        description="Airport ICAO codes, e.g. ['KJFK', 'KLGA'].", min_length=1
    )
    time: str = Field(description="ISO-8601 timestamp, e.g. 2025-08-21T18:03:00Z.")
    day: Optional[str] = Field(
        default=None,
        description="Optional YYYY-MM-DD to restrict the search to one day.",
    )


class AirportInbound(BaseModel):
    airport: str
    sector: Optional[str] = Field(description="LOW sector the airport sits in.")
    flight_count: Optional[int] = Field(
        description="Flights (inbound or departure, per the endpoint) in the "
        "matched 5-minute window; 0 if none that window, null if no stored data."
    )
    has_data: bool = Field(
        description="Whether any stored data exists for the airport."
    )


class FlightsInboundResponse(BaseModel):
    requested_time: str
    matched_time: str = Field(description="Closest stored 5-min bucket to the request.")
    offset_seconds: int = Field(
        description="matched_time - requested_time, in seconds."
    )
    day: str = Field(description="Day the matched bucket belongs to.")
    airports: list[AirportInbound]


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Could not parse time {value!r}; use ISO-8601 (e.g. 2025-08-21T18:03:00Z).",
        )
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def compute_flight_counts(
    direction: str, airports: list[str], time: str, day: Optional[str]
) -> FlightsInboundResponse:
    """Flight count per airport at the stored time closest to ``time``.

    ``direction`` is ``'arrival'`` or ``'departure'`` and selects which stored
    series to read; the closest-time logic is identical for both.
    """
    airports = [a.upper() for a in airports]
    if not airports:
        raise HTTPException(status_code=400, detail="Provide at least one airport.")
    requested = _parse_time(time)

    conn = db.connect(DB_PATH)
    try:
        rows = db.read_airport_rows(conn, direction, airports, day)
    finally:
        conn.close()
    if not rows:
        raise HTTPException(
            status_code=404,
            detail={
                "error": f"No stored {direction} data for these airports.",
                "hint": "Call /refresh first.",
                "airports": airports,
            },
        )

    # Closest stored 5-minute bucket to the requested time.
    bucket_times = {
        r["bucket_start"]: datetime.fromisoformat(r["bucket_start"]) for r in rows
    }
    matched = min(
        bucket_times, key=lambda b: abs((bucket_times[b] - requested).total_seconds())
    )

    have_data = {r["airport"] for r in rows}
    sector_by_airport = {r["airport"]: r["sector"] for r in rows}
    at_matched = {r["airport"]: r for r in rows if r["bucket_start"] == matched}

    per_airport = []
    for airport in airports:
        if airport not in have_data:
            per_airport.append(
                AirportInbound(
                    airport=airport, sector=None, flight_count=None, has_data=False
                )
            )
        elif airport in at_matched:
            row = at_matched[airport]
            per_airport.append(
                AirportInbound(
                    airport=airport,
                    sector=row["sector"],
                    flight_count=row["flight_count"],
                    has_data=True,
                )
            )
        else:
            per_airport.append(
                AirportInbound(
                    airport=airport,
                    sector=sector_by_airport[airport],
                    flight_count=0,
                    has_data=True,
                )
            )

    return FlightsInboundResponse(
        requested_time=requested.isoformat(),
        matched_time=matched,
        offset_seconds=int((bucket_times[matched] - requested).total_seconds()),
        day=next(iter(at_matched.values()))["day"],
        airports=per_airport,
    )


@app.post("/flights-inbound", response_model=FlightsInboundResponse)
def flights_inbound(req: FlightsInboundRequest):
    """Inbound (arrival) flight count for airports at the closest stored time."""
    return compute_flight_counts("arrival", req.airports, req.time, req.day)


@app.get("/flights-inbound", response_model=FlightsInboundResponse)
def flights_inbound_get(
    airports: list[str] = Query(default=[], description="Repeat per airport."),
    time: str = Query(description="ISO-8601 timestamp, e.g. 2025-08-21T18:03:00Z."),
    day: Optional[str] = Query(default=None),
):
    """Convenience GET form of POST /flights-inbound."""
    return compute_flight_counts("arrival", airports, time, day)


@app.post("/departure-capacity", response_model=FlightsInboundResponse)
def departure_capacity(req: FlightsInboundRequest):
    """Departure flight count for a set of airports at the closest stored time."""
    return compute_flight_counts("departure", req.airports, req.time, req.day)


@app.get("/departure-capacity", response_model=FlightsInboundResponse)
def departure_capacity_get(
    airports: list[str] = Query(default=[], description="Repeat per airport."),
    time: str = Query(description="ISO-8601 timestamp, e.g. 2025-08-21T18:03:00Z."),
    day: Optional[str] = Query(default=None),
):
    """Convenience GET form of POST /departure-capacity."""
    return compute_flight_counts("departure", airports, time, day)


# --- airport capacity (VMC AAR) + demand-vs-capacity overload ---------------


def _ensure_capacity_seeded(conn) -> None:
    """Seed the curated AAR table if empty, so reads work without a refresh.

    The AAR values are static curated constants (``capacity.VMC_AAR``), so there
    is no reason to force an explicit refresh before the first read -- unlike the
    arrival-frequency demand, which must be computed from snapshots. Idempotent.
    """
    if not db.read_capacity(conn):
        db.write_capacity(conn, capacity.capacity_rows())


def _seed_capacity() -> dict:
    """(Re)write the curated VMC AAR table into SQLite."""
    conn = db.connect(DB_PATH)
    try:
        rates = capacity.capacity_rows()
        written = db.write_capacity(conn, rates)
    finally:
        conn.close()
    return {"db_path": str(DB_PATH), "written": written, "rates": rates}


@app.get("/capacity_rates")
def capacity_rates(
    airports: list[str] = Query(
        default=[],
        description="Optional ICAO filter; repeat per airport. Omit for all.",
    ),
):
    """Read the stored VMC AAR (arrivals/hour) per airport.

    The single capacity reference used by /overload. Seeds the curated table on
    first read. Only the slot-controlled core airports (KJFK/KLGA/KEWR) have an
    AAR; metro relievers are absent (no FAA capacity profile).
    """
    wanted = [a.upper() for a in airports] or None
    conn = db.connect(DB_PATH)
    try:
        _ensure_capacity_seeded(conn)
        rates = db.read_capacity(conn, wanted)
    finally:
        conn.close()
    return {"count": len(rates), "rates": rates}


@app.post("/capacity_rates/refresh")
def capacity_rates_refresh():
    """(Re)seed the curated VMC AAR table into SQLite. Idempotent."""
    return _seed_capacity()


@app.get("/capacity_rates/refresh")
def capacity_rates_refresh_get():
    """Convenience GET form of POST /capacity_rates/refresh."""
    return _seed_capacity()


@app.get("/overload")
def overload(
    day: str = Query(description="Day to analyze, YYYY-MM-DD (must be refreshed)."),
    airport: Optional[str] = Query(
        default=None,
        description="Optional ICAO filter; omit to analyze all capacity airports.",
    ),
):
    """Rolling-hour arrival demand vs the VMC AAR, per airport, for a day.

    Rolls the stored 5-minute arrival demand into a rolling 60-minute count and
    compares it to each airport's hourly AAR, flagging the windows where demand
    exceeds capacity. Refresh the day's demand (POST /refresh) first.
    """
    conn = db.connect(DB_PATH)
    try:
        _ensure_capacity_seeded(conn)
        aar_by_airport = {r["airport"]: r["aar"] for r in db.read_capacity(conn)}
        demand_rows = db.read_day(conn, day, "arrival")
    finally:
        conn.close()

    if not demand_rows:
        raise HTTPException(
            status_code=404,
            detail={
                "error": f"No stored arrival demand for day {day!r}.",
                "hint": "Call /refresh first.",
            },
        )

    if airport is not None:
        airport = airport.upper()
        if airport not in aar_by_airport:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": f"No stored capacity (AAR) for {airport!r}.",
                    "available": sorted(aar_by_airport),
                },
            )
        targets = [airport]
    else:
        targets = sorted(aar_by_airport)

    demand_by_airport: dict[str, list[dict]] = {}
    for row in demand_rows:
        demand_by_airport.setdefault(row["airport"], []).append(row)

    results = []
    for icao in targets:
        aar = aar_by_airport[icao]
        series = capacity.rolling_hour_overload(demand_by_airport.get(icao, []), aar)
        overloaded = [s for s in series if s["overloaded"]]
        results.append(
            {
                "airport": icao,
                "aar": aar,
                "peak_rolling_arrivals": max(
                    (s["rolling_arrivals"] for s in series), default=0
                ),
                "overloaded_window_count": len(overloaded),
                "series": series,
            }
        )

    return {"day": day, "airport": airport, "airports": results}


# --- reroute recommendation --------------------------------------------------

# Airports considered as reroute candidates when none specified.
NYC_CORE = ["KJFK", "KLGA", "KEWR"]
DEFAULT_RECOMMEND_DAY = "2025-12-25"


def _snap_to_5min(t: datetime) -> datetime:
    return t.replace(minute=(t.minute // 5) * 5, second=0, microsecond=0)


def _rolling_count_at(buckets: list[dict], t: datetime) -> int:
    """Sum arrivals across the 12 five-minute buckets ending at t (matching rolling_hour_overload)."""
    t_snap = _snap_to_5min(t)
    # 12 buckets × 5 min = 60 min; window is [t-55min, t] inclusive (12 steps).
    window_start = t_snap - timedelta(minutes=55)
    return sum(
        int(b["flight_count"])
        for b in buckets
        if window_start <= datetime.fromisoformat(b["bucket_start"]) <= t_snap
    )


class RecommendRequest(BaseModel):
    airport: str = Field(description="Desired destination airport ICAO, e.g. 'KJFK'.")
    time: str = Field(description="Desired arrival time, ISO-8601 UTC.")
    day: Optional[str] = Field(
        default=None,
        description="Day to analyze, YYYY-MM-DD. Defaults to 2025-12-25.",
    )
    alternatives: Optional[list[str]] = Field(
        default=None,
        description="Alternative airport ICAOs to score. Defaults to all NYC core airports.",
    )


class AirportLoad(BaseModel):
    airport: str
    rolling_arrivals: int
    aar: int
    utilization: float
    available_capacity: int
    is_overloaded: bool


class RecommendResponse(BaseModel):
    requested_airport: str
    requested_time: str
    day: str
    target: AirportLoad
    alternatives: list[AirportLoad]
    recommendation: Optional[str] = Field(
        description="ICAO of the best alternative airport, or null if target has capacity."
    )


@app.post("/recommend", response_model=RecommendResponse)
def recommend(req: RecommendRequest):
    """Reroute recommendation for a desired arrival.

    Given a target airport and desired arrival time, computes rolling-60-minute
    arrival demand for the target and all alternatives, then ranks alternatives
    by available capacity (AAR minus current demand). Returns the best
    alternative if the target is at or over capacity.
    """
    airport = req.airport.upper()
    day = req.day or DEFAULT_RECOMMEND_DAY
    t = _parse_time(req.time)

    alts = [a.upper() for a in req.alternatives] if req.alternatives else NYC_CORE
    all_airports = list({airport} | set(alts))

    conn = db.connect(DB_PATH)
    try:
        _ensure_capacity_seeded(conn)
        aar_by_airport = {r["airport"]: r["aar"] for r in db.read_capacity(conn)}
        demand_rows = db.read_day(conn, day, "arrival")
    finally:
        conn.close()

    if not demand_rows:
        raise HTTPException(
            status_code=404,
            detail={
                "error": f"No stored arrival demand for day {day!r}.",
                "hint": "Seed this day first (e.g. via seed_bts.py for 2025-12-25).",
            },
        )

    # Group demand by airport.
    demand_by_airport: dict[str, list[dict]] = {}
    for row in demand_rows:
        demand_by_airport.setdefault(row["airport"], []).append(row)

    def airport_load(icao: str) -> AirportLoad:
        aar = aar_by_airport.get(icao, 0)
        count = _rolling_count_at(demand_by_airport.get(icao, []), t)
        util = round(count / aar, 3) if aar else 0.0
        return AirportLoad(
            airport=icao,
            rolling_arrivals=count,
            aar=aar,
            utilization=util,
            available_capacity=aar - count,
            is_overloaded=count > aar,
        )

    target_load = airport_load(airport)
    alt_loads = sorted(
        [airport_load(a) for a in alts if a != airport],
        key=lambda x: (-x.available_capacity, x.airport),
    )

    # Recommend the alternative with the most headroom, but only surface a
    # redirect if the target is overloaded or within 5% of capacity.
    recommend_icao: Optional[str] = None
    if target_load.is_overloaded or target_load.utilization >= 0.95:
        best = next((a for a in alt_loads if not a.is_overloaded), None)
        if best:
            recommend_icao = best.airport

    return RecommendResponse(
        requested_airport=airport,
        requested_time=t.isoformat(),
        day=day,
        target=target_load,
        alternatives=alt_loads,
        recommendation=recommend_icao,
    )


@app.get("/recommend")
def recommend_get(
    airport: str = Query(description="Target airport ICAO, e.g. KJFK."),
    time: str = Query(description="Desired arrival time, ISO-8601 UTC."),
    day: Optional[str] = Query(default=None),
):
    """Convenience GET form of POST /recommend."""
    return recommend(RecommendRequest(airport=airport, time=time, day=day))


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
