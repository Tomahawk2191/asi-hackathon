# ASI Hackathon — Air-Traffic Tools

A small full-stack project for analyzing US air traffic over CONUS airspace, with
a focus on the NYC metro. Given a set of airspace **sectors** and a flight
**snapshot**, the core feature counts how many flights land in that region,
grouped by arrival airport.

## Layout

| Path                      | What it is                                                              |
| ------------------------- | ----------------------------------------------------------------------- |
| `backend/`                | FastAPI service (Python 3.8+, Pydantic v2). The landing-count API.      |
| `frontend/`               | React 19 + Vite + MapLibre GL SPA (map, load board, timeline). |
| `data/`                   | Committed datasets: `sectors.geojson` + `nyc_dataset/`.                 |

## Running

**Backend** (serves on `http://localhost:8000`, Swagger at `/docs`):
```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

**Frontend** (Vite dev server on `http://localhost:5173` — uses **bun**, see `bun.lock`):
```bash
cd frontend
bun install
bun run dev      # dev server
bun run build    # tsc -b && vite build
bun run lint     # eslint
```

The backend CORS config only allows `http://localhost:5173`, so run the frontend
on that port (Vite's default).

## Scenarios & data wiring

The backend reads its inputs entirely from the committed `data/` directory — no
external bundle needed:

- **Sectors** come from `data/sectors.geojson` (`get_sectors` in `main.py`).
- **Flight snapshots** come from `data/nyc_dataset/nyc_<date>.json`. Each file is
  one **scenario**, and the scenario id the API exposes is its `<date>` (e.g.
  `2025-08-21`). See `_scenario_name`, `list_scenarios`, and `_routes_path` in
  `main.py`; `.json.gz` variants are also recognized.

`GET /scenarios` lists those dates; the default (when `scenario` is omitted) is the
earliest. Both data accessors are `lru_cache`'d, so the dev server keeps parsed
snapshots in memory after first use. Because the dataset is NYC-filtered, landing
counts only ever include NYC-metro airports.

## Backend internals

- `main.py` — FastAPI app, request/response models, endpoints, and `lru_cache`'d
  data access (`get_sectors`, `get_snapshot`). See `backend/API.md` for the full
  endpoint spec.
- `flights.py` — `Flight` and `RoutesSnapshot` Pydantic models. A flight's route is
  parallel `lats`/`lons` waypoint arrays; first point is origin, **last point is the
  destination (landing) airport**. Identity is `(flight_number, take_off_time,
  origin_airport_icao)` — `flight_number` alone is not unique.
- `sectors.py` — `Sector` model + the landing logic. Point-in-polygon is **pure
  Python ray-casting** (`_point_in_ring`) with a cached bounding box — intentionally
  no shapely/GEOS dependency. `flights_landing_per_airport()` tests each flight's
  last waypoint against the sectors' 2D footprints.
- `loaders.py` — generic JSON/gzip → Pydantic loader.

### Sector gotcha
Sectors partition airspace into two altitude bands: **LOW** `[0, 35000)` ft and
**HIGH** `[35000, 60000)` ft (356 of each, 712 total in `sectors.geojson`). Landing
happens at ground level, so pass **LOW_*** sectors for meaningful landing counts —
`contains()` only tests the 2D footprint and does **not** filter by altitude.

Coordinates everywhere are **`[lon, lat]`** decimal degrees, WGS84 (GeoJSON order).
Times are UTC ISO 8601.

## Data

- `data/sectors.geojson` — 712 sector polygons (`LOW_*` / `HIGH_*`), each with an
  altitude band and capacity.
- `data/nyc_dataset/` — 5 daily NYC-metro flight snapshots (`nyc_<date>.json`) plus
  `manifest.json` (per-day windows, counts, airport filter). A flight is included if
  its origin OR destination is in the NYC airport set (core `KJFK/KLGA/KEWR` + metro
  relievers). Each "day" is an ~18 h window (~noon → 6am EDT), not a calendar day.
  See `data/nyc_dataset/README.md`.

## Airport capacity (FAA slot caps)

Airport capacity is a **throughput** (movements/hour), not a count of planes present,
and it's a trade-off between arrivals and departures (a capacity *envelope*, not one
number). The reference ceiling for this project is the **FAA slot cap** — the declared
hourly limit on *scheduled* operations the FAA enforces at the slot-controlled NYC
airports. All three orders run through **Oct 24, 2026**:

| Airport  | Cap (scheduled ops/hr) | Notes                                                              |
| -------- | ---------------------- | ------------------------------------------------------------------ |
| **KJFK** | **81**                 | During slot-controlled hours; order in place since 2008.           |
| **KLGA** | **71**                 | Plus 3 unscheduled/hr (≈74 total); cut 75→71 in 2009.              |
| **KEWR** | **72**                 | Raised 68→72 eff. Oct 26, 2025 after the 2025 staffing/runway cuts. |

**What kind of limit it is.** The slot cap is *administrative*, deliberately set below
the good-weather (VMC) physical maximum so the system stays resilient. VMC capacity is
higher than the cap; IMC (bad-weather) capacity can fall **below** it — which is why
capped airports still incur delays. It counts only *scheduled* ops during
*slot-controlled hours* (excludes GA/unscheduled and overnight), so raw movement counts
won't match it 1:1.

**Empirical cross-check ("revealed capacity").** Binning the dataset's `take_off_time`
(departures) and `scheduled_landing_time` (arrivals) per core airport into rolling
60-min windows and taking the peak recovers a usable capacity estimate:
- **KLGA** peaks at **73–81/hr** across the 5 days — right on its 71(+3) cap, so LGA is
  the capacity-bound airport, and this validates both the cap and the method.
- **KJFK** (46–62/hr) and **KEWR** (47–61/hr) run under cap in these 18-h windows —
  either real headroom or the window clips a late bank.

Don't trust short windows ×4 (15-min bursts extrapolate to 100–128/hr for LGA); the
**rolling 60-min** rate is the meaningful, sustainable number.

**Using it.** Make the slot cap the capacity line in a demand-vs-capacity
(cumulative-queue) analysis: demand = rolling movement count; overload = where demand >
cap. Mind the ~18-h window caveat (misses the morning departure push) — see
`data/nyc_dataset/README.md`.

Sources: FAA Operating Limitations orders (Federal Register) —
[JFK](https://www.federalregister.gov/documents/2024/05/13/2024-10297/operating-limitations-at-john-f-kennedy-international-airport),
[LGA](https://www.federalregister.gov/documents/2022/10/28/2022-23617/operating-limitations-at-new-york-laguardia-airport),
[EWR](https://www.federalregister.gov/documents/2025/09/29/2025-18871/operating-limitations-at-newark-liberty-international-airport).

## Conventions

- Backend code uses `from __future__ import annotations`, type hints throughout,
  and module docstrings explaining each file's role and data schema. Match that
  style — explain the *why* of domain quirks (altitude bands, coordinate order) in
  comments.
- No test suite or formatter config is present yet.

## Agent skills

### Issue tracker

Issues and PRDs are tracked as **GitHub issues** (`Tomahawk2191/asi-hackathon`) via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default triage vocabulary — `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

**Single-context.** One `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
