# ASI Routing Lab

Hackathon prototype for the ASI Boston Hackathon 2026 data bundle: a 3D MapLibre
UI driven by a FastAPI backend that does flight routing and predictive routing
over historical snapshots OR live OpenSky traffic, with weather pulled from the
bundle or live HRRR off NOAA's S3 Open Data bucket.

![flow](https://img.shields.io/badge/stack-FastAPI%20%2B%20Vite%20%2B%20MapLibre-blue)

## What it does

| Feature | Source |
|---|---|
| Sectors (HIGH/LOW band, color by load) | `sectors.geojson` (synthetic, bundle) |
| Flights (planes on map, rotated to heading) | Snapshot (propagated) **or** OpenSky live |
| Weather (REFC / RETOP overlay) | Snapshot **or** live HRRR via `s3://noaa-hrrr-bdp-pds` |
| Routing | A* over 0.5° CONUS grid; weather + sector-overload penalties; polyline densified to ≤19-min legs |

## Prereqs

- macOS or Linux. Tested on macOS 14 arm64.
- `uv`, `node` ≥ 20, `npm`, `bash`
- `eccodes` C library (for HRRR grib2 decoding). On macOS: `brew install eccodes`.
- (Optional) [OpenSky Network](https://opensky-network.org/) free account → API
  client for live traffic. Without it, "snapshot" flights still work; "live" mode
  will hit anonymous rate limits and serve stale cache.

## Setup

```sh
git clone https://github.com/Tomahawk2191/asi-hackathon.git
cd asi-hackathon
git checkout rohan

# Create your local .env from the template.
cp .env.example .env
# Then edit .env to fill in OPENSKY_CLIENT_ID + OPENSKY_CLIENT_SECRET
# (https://opensky-network.org/my-opensky/api-tokens — free)

# Hackathon data bundle path. Default is /Users/rohan/Downloads/hackathon_data_bundle.
# Override in .env if yours is elsewhere:
#   ASI_BUNDLE_DIR="/path/to/hackathon_data_bundle"
```

## Run everything

```sh
./run.sh
```

That script:
1. Verifies `uv`, `node`, `npm`, and `eccodes` are present (installing eccodes via brew if missing).
2. `uv sync`s backend deps and `npm install`s frontend deps.
3. Starts FastAPI on **http://127.0.0.1:8765** and Vite on **http://localhost:5173**.
4. Tee's logs to `.logs/{backend,frontend}.log`. `Ctrl-C` stops both.

Open <http://localhost:5173>.

## Repo layout

```
asi-hackathon/
├── run.sh                # one-shot dev launcher
├── .env.example          # template for OpenSky creds + bundle path
├── backend/
│   ├── pyproject.toml    # uv-managed; FastAPI + numpy + shapely + cfgrib + httpx
│   └── app/
│       ├── main.py                 # HTTP endpoints
│       ├── config.py               # paths + grid constants + dotenv loader
│       ├── airports.py             # ICAO → lat/lon table for the route picker
│       ├── data/
│       │   ├── snapshots.py        # routes.json loader
│       │   ├── sectors.py          # sectors.geojson + STRtree
│       │   ├── weather.py          # static .npz + live HRRR (byte-range idx → cfgrib → regrid)
│       │   └── opensky.py          # OAuth2 client_credentials, cache, backoff
│       ├── sim/
│       │   ├── geo.py              # haversine, great-circle slerp
│       │   └── simulator.py        # flight propagation + sector load count
│       ├── routing/
│       │   └── router.py           # A* + weather/sector penalties + densify
│       └── render/
│           └── wx_png.py           # matrix → tinted RGBA PNG
└── frontend/
    ├── package.json      # Vite + React + TS + maplibre-gl + turf
    └── src/
        ├── App.tsx       # sidebar + state
        ├── Map.tsx       # MapLibre globe + layers
        ├── api.ts        # backend client
        └── planeIcons.ts # canvas-generated plane sprites
```

## HTTP endpoints

| Method | Path | Notes |
|---|---|---|
| GET  | `/api/snapshots` | List of 11 `asked_at_*` snapshots |
| GET  | `/api/airports`  | Tiny ICAO → coord table |
| GET  | `/api/sectors?band=HIGH\|LOW&snapshot=…&at=…` | GeoJSON + `load`, `load_pct`, `overloaded` |
| GET  | `/api/sectors/live?band=HIGH\|LOW` | Same shape, loads from live OpenSky positions |
| GET  | `/api/flights?snapshot=…&at=…` | Propagated positions for snapshot time |
| GET  | `/api/flights/live` | OpenSky states (CONUS), cached 30 s |
| GET  | `/api/weather?field=refc\|retop&source=static\|live&…` | PNG with bbox headers |
| POST | `/api/route` | `{origin, destination, cruise_altitude_ft, cruise_speed_kt, depart_at, snapshot, avoid_weather, avoid_overloaded_sectors}` |

## Tradeoffs / known limits

- **Synthetic sectors.** Capacities are size-estimated in the bundle; not real MAP values.
- **No wind.** HRRR has it; not in the bundle and we don't pull it live (yet).
- **2D routing.** Flights fly straight at cruise altitude — no climb/descent or step-climbs.
- **Coarse router grid (0.5° = ~30 nm).** Plenty for a demo; sub-nm accuracy would need a finer graph or genuine FAA route segments.
- **MapLibre on WebGL2.** WebGPU is roadmap, not stable. If you need GPU compute (e.g., route ensembles on the GPU), swap to deck.gl.

## Run pieces individually (instead of run.sh)

```sh
# backend
cd backend && uv sync && uv run uvicorn app.main:app --host 127.0.0.1 --port 8765 --reload

# frontend
cd frontend && npm install && npm run dev
```
