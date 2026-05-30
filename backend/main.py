"""FastAPI backend for the ASI hackathon air-traffic tools.

Exposes the sector landing-count helper over HTTP: given a set of sectors and
a scenario snapshot, return how many flights land in that region, grouped by
arrival airport.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import db
import nyc
from flights import RoutesSnapshot
from loaders import load_routes
from sectors import Sector, flights_landing_per_airport, load_sectors

ROOT = Path(__file__).resolve().parent.parent
SECTORS_PATH = ROOT / "data" / "sectors.geojson"
BUNDLE = ROOT / "hackathon_data_bundle"
DB_PATH = Path(os.environ.get("ARRIVALS_DB") or db.DEFAULT_DB_PATH)

app = FastAPI(title="ASI Hackathon API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- cached data access ------------------------------------------------------


@lru_cache(maxsize=1)
def get_sectors() -> dict[str, Sector]:
    """Load the shared sectors file once, indexed by name."""
    return {s.name: s for s in load_sectors(SECTORS_PATH)}


def list_scenarios() -> list[str]:
    """Names of the scenario snapshot directories in the data bundle."""
    if not BUNDLE.exists():
        return []
    return sorted(
        p.name
        for p in BUNDLE.iterdir()
        if p.is_dir() and p.name.startswith("asked_at_")
    )


def default_scenario() -> Optional[str]:
    scenarios = list_scenarios()
    return scenarios[0] if scenarios else None


def _routes_path(scenario: str) -> Path:
    """Locate a scenario's routes file (plain or gzipped)."""
    base = BUNDLE / scenario
    for name in ("routes.json", "routes.json.gz"):
        candidate = base / name
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"No routes file found for scenario {scenario!r}")


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
        description="Scenario directory name (see GET /scenarios). "
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


def compute_landings(sector_names: list[str], scenario: Optional[str]) -> LandingsResponse:
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
    """Compute NYC arrival frequency from local files and write it to SQLite."""
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
            rows = nyc.nyc_arrival_frequency(load_routes(nyc.day_file(d)), sector_list)
            written = db.write_day(conn, d, rows)
            refreshed.append(
                {"day": d, "rows": written, "flights": sum(r["flight_count"] for r in rows)}
            )
    finally:
        conn.close()
    return {
        "db_path": str(DB_PATH),
        "refreshed": refreshed,
        "total_flights": sum(r["flights"] for r in refreshed),
    }


@app.post("/refresh")
def refresh(req: RefreshRequest):
    """Build the 5-minute NYC arrival-frequency table for a day (or all days).

    Reads only local bundle files and writes the result to the SQLite DB.
    """
    return _refresh(req.day)


@app.get("/refresh")
def refresh_get(day: Optional[str] = Query(default=None)):
    """Convenience GET form of POST /refresh."""
    return _refresh(day)


@app.get("/arrivals")
def arrivals(
    day: str = Query(description="Day to read, YYYY-MM-DD (must be refreshed first)."),
    sector: Optional[str] = Query(default=None, description="Optional sector filter."),
):
    """Read back stored arrival frequency for a day (optionally one sector)."""
    conn = db.connect(DB_PATH)
    try:
        rows = db.read_day(conn, day, sector)
    finally:
        conn.close()
    return {"day": day, "sector": sector, "count": len(rows), "rows": rows}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
