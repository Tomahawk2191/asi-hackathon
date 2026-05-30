# API Endpoints

FastAPI backend for the ASI hackathon air-traffic tools. Base URL: `http://localhost:8000`.
Interactive docs (Swagger): `http://localhost:8000/docs`.

| Method | Path         | Summary                                                        |
| ------ | ------------ | -------------------------------------------------------------- |
| GET    | `/`          | Health check.                                                  |
| GET    | `/scenarios` | List available scenario snapshots + the default.               |
| GET    | `/sectors`   | Summarize all sectors (name, altitude band, capacity).         |
| POST   | `/landings`  | Flights landing in a set of sectors, grouped by arrival airport. |
| GET    | `/landings`  | Convenience query-param form of `POST /landings`.              |
| POST   | `/refresh`   | Build & store the 5-min NYC arrival-frequency table for a day. |
| GET    | `/refresh`   | Convenience query-param form of `POST /refresh`.               |
| GET    | `/arrivals`  | Read back stored NYC arrival frequency for a day.              |
| POST   | `/flights-inbound` | Inbound flight count for airports at the closest stored time. |
| GET    | `/flights-inbound` | Convenience query-param form of `POST /flights-inbound`.      |
| GET    | `/capacity_rates` | Stored VMC AAR (arrivals/hour) per airport.                   |
| POST   | `/capacity_rates/refresh` | (Re)seed the curated VMC AAR table. Idempotent.       |
| GET    | `/capacity_rates/refresh` | Convenience form of `POST /capacity_rates/refresh`.   |
| GET    | `/overload`  | Rolling-hour arrival demand vs the AAR, per airport, for a day.  |
| GET    | `/busyness`  | Per-airport "busyness" score at a time (live from the snapshots).  |
| GET    | `/sister-airports` | Nearby airports less busy than a given airport at a time.    |

---

### `GET /`

Health check. Returns `{"message": "Hello from FastAPI"}`.

### `GET /scenarios`

Lists the available scenario ids — the `YYYY-MM-DD` date of each `nyc_<date>.json`
snapshot in `data/nyc_dataset/` (the valid values for the `scenario`/`day` fields
elsewhere) — and the default used when omitted (the earliest). Because scenarios
come from the NYC dataset, `/landings` sees only NYC-metro flights.

```json
{
  "scenarios": [
    "2025-05-29",
    "2025-08-21",
    "2026-01-13",
    "2026-03-04",
    "2026-04-08"
  ],
  "default": "2025-05-29"
}
```

### `GET /sectors`

Summarizes every sector so you can pick names for `/landings`. Geometry is omitted.

```json
{
  "count": 712,
  "sectors": [
    {
      "name": "HIGH_006",
      "altitude_from_ft": 35000,
      "altitude_to_ft": 60000,
      "capacity": 20
    },
    "..."
  ]
}
```

### `POST /landings`

Counts the flights that **land** within a set of sectors, grouped by arrival
airport. A flight lands in the set if its destination waypoint (the arrival
airport) falls inside any of the given sectors. Counts sum once across the set
(a flight in two of the listed sectors is still counted once).

> Landing happens at ground level, so pass **LOW** band sectors for meaningful
> results — the geometry test does not filter by altitude itself.

**Request body**

| Field          | Type       | Required | Description                                                                     |
| -------------- | ---------- | -------- | ------------------------------------------------------------------------------- |
| `sector_names` | `string[]` | yes      | Sectors defining the region, e.g. `["LOW_295"]` (min 1).                        |
| `scenario`     | `string`   | no       | Scenario id — a `YYYY-MM-DD` date (see `/scenarios`); defaults to the earliest. |

**Response** (`per_airport` sorted high → low)

```json
{
  "scenario": "2025-08-21",
  "sector_names": ["LOW_295"],
  "total_flights": 859,
  "per_airport": {
    "KLGA": 264,
    "KEWR": 222,
    "KJFK": 209,
    "KHPN": 77,
    "KTEB": 71,
    "KFRG": 15,
    "KBLM": 1
  }
}
```

```bash
curl -s -X POST http://localhost:8000/landings \
  -H 'Content-Type: application/json' \
  -d '{"sector_names":["LOW_295"],"scenario":"2025-08-21"}'
```

### `GET /landings`

Same result as `POST /landings`, for quick manual testing. Repeat `sectors` to
pass several; `scenario` is optional.

```bash
curl -s "http://localhost:8000/landings?sectors=LOW_295&sectors=LOW_296&scenario=2025-08-21"
```

### `POST /refresh`

Builds the **NYC-metro frequency** tables and writes them to SQLite. For the
given day it computes, for **both arrivals and departures**, the count of flights
at each NY-metro airport bucketed into 5-minute windows — arrivals by scheduled
landing time (grouped by destination), departures by take-off time (grouped by
origin) — each tagged with the LOW sector the airport sits in. Reads **only local
bundle files** (`data/nyc_dataset/`) — no network. Idempotent: re-running a day
replaces that day's rows for both directions.

**Request body**

| Field | Type     | Required | Description                                                       |
| ----- | -------- | -------- | ----------------------------------------------------------------- |
| `day` | `string` | no       | Day as `YYYY-MM-DD` (one of the 5 NYC days). Omit to refresh all. |

**Response** — per day, a `rows`/`flights` summary for each direction.

```json
{
  "db_path": "/.../backend/arrivals.db",
  "total_flights": 1792,
  "refreshed": [
    {
      "day": "2025-08-21",
      "arrivals": { "rows": 480, "flights": 894 },
      "departures": { "rows": 415, "flights": 898 }
    }
  ]
}
```

```bash
curl -s -X POST http://localhost:8000/refresh -H 'Content-Type: application/json' -d '{"day":"2025-08-21"}'
curl -s -X POST http://localhost:8000/refresh -H 'Content-Type: application/json' -d '{}'   # all days
```

### `GET /refresh`

Same as `POST /refresh`: `GET /refresh?day=2025-08-21` (omit `day` for all days).

### `GET /arrivals` · `GET /departures`

Read back the stored rows for a day (refresh it first), optionally filtered to one
sector. `/arrivals` returns the arrival series, `/departures` the departure series;
both share the same shape and an echoed `direction` field.

| Query    | Required | Description                             |
| -------- | -------- | --------------------------------------- |
| `day`    | yes      | Day to read, `YYYY-MM-DD`.              |
| `sector` | no       | Restrict to one sector, e.g. `LOW_295`. |

```json
{
  "day": "2025-08-21",
  "direction": "arrival",
  "sector": "LOW_295",
  "count": 449,
  "rows": [
    {
      "day": "2025-08-21",
      "direction": "arrival",
      "sector": "LOW_295",
      "airport": "KLGA",
      "bucket_start": "2025-08-21T18:00:00+00:00",
      "flight_count": 2
    }
  ]
}
```

```bash
curl -s "http://localhost:8000/arrivals?day=2025-08-21&sector=LOW_295"
curl -s "http://localhost:8000/departures?day=2025-08-21&sector=LOW_295"
```

### `POST /flights-inbound` · `POST /departure-capacity`

Historic flight load for a set of airports at a given time. Finds the **closest
stored 5-minute bucket** to the requested time and returns each airport's count
there. `/flights-inbound` uses the **arrival** series (flights inbound to each
airport); `/departure-capacity` uses the **departure** series. Both share
request/response shapes and read from the SQLite DB, so refresh the relevant day
first.

> The count is the historic **flights-per-5-minutes** we store per airport
> (observed throughput / demand), not a regulatory capacity limit — that time
> series is the only time-stamped per-airport data in the DB.

**Request body**

| Field      | Type       | Required | Description                                            |
| ---------- | ---------- | -------- | ------------------------------------------------------ |
| `airports` | `string[]` | yes      | ICAO codes (case-insensitive), e.g. `["KJFK","KLGA"]`. |
| `time`     | `string`   | yes      | ISO-8601 timestamp, e.g. `2025-08-21T18:03:00Z`.       |
| `day`      | `string`   | no       | Restrict the search to one `YYYY-MM-DD`.               |

**Response** — `flight_count` is `0` when the airport had no flights (that
direction) in the matched window, and `null` when the airport has no stored data
at all (`has_data: false`).

```json
{
  "requested_time": "2025-08-21T18:03:00+00:00",
  "matched_time": "2025-08-21T18:05:00+00:00",
  "offset_seconds": 120,
  "day": "2025-08-21",
  "airports": [
    {
      "airport": "KJFK",
      "sector": "LOW_295",
      "flight_count": 2,
      "has_data": true
    },
    {
      "airport": "KLGA",
      "sector": "LOW_295",
      "flight_count": 5,
      "has_data": true
    }
  ]
}
```

```bash
# inbound (arrivals)
curl -s -X POST http://localhost:8000/flights-inbound -H 'Content-Type: application/json' \
  -d '{"airports":["KJFK","KLGA","KEWR"],"time":"2025-08-21T18:03:00Z"}'
# departures
curl -s -X POST http://localhost:8000/departure-capacity -H 'Content-Type: application/json' \
  -d '{"airports":["KJFK","KLGA","KEWR"],"time":"2025-08-21T18:03:00Z"}'
```

### `GET /flights-inbound` · `GET /departure-capacity`

Convenience GET forms; repeat `airports`, e.g.
`GET /departure-capacity?airports=KJFK&airports=KLGA&time=2025-08-21T18:03:00Z`.

### `GET /capacity_rates`

The stored **VMC AAR** (Airport Arrival Rate, arrivals/hour) per airport — the
capacity reference used by `/overload`.

> A single VMC value per airport (long-range planning under optimum conditions —
> no weather tiers). Only the slot-controlled core airports have an AAR; metro
> relievers return no rows (no FAA capacity profile). This is *arrivals-only*, to
> match arrival demand — distinct from the combined FAA slot caps. Values are the
> FAA facility-reported VMC AAR (Airport Capacity Profiles 2014). The curated
> table is seeded automatically on first read.

| Query      | Required | Description                                          |
| ---------- | -------- | ---------------------------------------------------- |
| `airports` | no       | ICAO filter (case-insensitive); repeat per airport.  |

```json
{ "count": 3,
  "rates": [
    { "airport": "KEWR", "aar": 52, "source": "FAA Airport Capacity Profiles 2014 ..." },
    { "airport": "KJFK", "aar": 52, "source": "..." },
    { "airport": "KLGA", "aar": 40, "source": "..." } ] }
```

```bash
curl -s "http://localhost:8000/capacity_rates"
curl -s "http://localhost:8000/capacity_rates?airports=KLGA"
```

### `POST /capacity_rates/refresh`

(Re)seeds the curated VMC AAR table into SQLite. Idempotent: re-seeding replaces
the whole table, never duplicates. (`GET /capacity_rates/refresh` is an
equivalent convenience form.)

```json
{ "db_path": "/.../backend/arrivals.db", "written": 3,
  "rates": [ { "airport": "KEWR", "aar": 52, "source": "..." }, "..." ] }
```

```bash
curl -s -X POST http://localhost:8000/capacity_rates/refresh
```

### `GET /overload`

Rolling-hour arrival **demand vs capacity** for a day. Rolls the stored 5-minute
arrival demand into a rolling 60-minute count and compares it to each airport's
hourly AAR, flagging the windows where demand exceeds capacity.

> Refresh the day's demand (`POST /refresh`) first. The rolling-60-minute rate is
> the meaningful, sustainable number — 15-minute bursts ×4 over-extrapolate.
> `overload` = `rolling_arrivals - aar` (negative = spare capacity); `overloaded`
> is strict (`rolling_arrivals > aar`).

| Query     | Required | Description                                              |
| --------- | -------- | -------------------------------------------------------- |
| `day`     | yes      | Day to analyze, `YYYY-MM-DD` (must be refreshed).        |
| `airport` | no       | ICAO filter; omit to analyze all capacity airports.      |

```json
{ "day": "2025-08-21", "airport": "KLGA",
  "airports": [
    { "airport": "KLGA", "aar": 40,
      "peak_rolling_arrivals": 43, "overloaded_window_count": 6,
      "series": [
        { "bucket_start": "2025-08-21T18:00:00+00:00", "rolling_arrivals": 41,
          "aar": 40, "overload": 1, "overloaded": true } ] } ] }
```

```bash
curl -s "http://localhost:8000/overload?day=2025-08-21&airport=KLGA"
```

### `GET /busyness`

A rough per-airport **busyness ("popularity") score** at a moment in time,
computed **live from the scenario snapshot** in `data/` — no `/refresh` needed.
For a window centered on `time`, it blends **inbound** (arrivals), **outbound**
(departures), and the **inbound-capacity** reference (VMC AAR) into one estimate.

> Score model (a deliberate estimate, not an exact rate):
> `movements = inbound + outbound`, `score = round(100 * movements / (2 * AAR))`.
> `~100` ≈ a core airport at practical capacity (it can exceed 100). Relievers have
> no FAA AAR, so they're scaled on the busiest-core reference (52) and report
> `capacity: null`. All raw parts are returned, so you can re-derive your own score.

| Query            | Required | Description                                                       |
| ---------------- | -------- | ----------------------------------------------------------------- |
| `scenario`       | no       | Scenario id (`YYYY-MM-DD`); defaults to the earliest.             |
| `time`           | no       | ISO-8601 center time; defaults to the scenario's window midpoint. |
| `window_minutes` | no       | Window width centered on `time` (5–240, default 60).             |

**Response** — `airports` sorted busiest → least busy.

```json
{
  "scenario": "2025-08-21",
  "time": "2025-08-21T19:15:00+00:00",
  "window_minutes": 60,
  "airports": [
    { "airport": "KLGA", "inbound": 34, "outbound": 41, "movements": 75, "capacity": 40, "has_capacity": true, "score": 94 },
    { "airport": "KEWR", "inbound": 17, "outbound": 33, "movements": 50, "capacity": 52, "has_capacity": true, "score": 48 },
    { "airport": "KTEB", "inbound": 16, "outbound": 15, "movements": 31, "capacity": null, "has_capacity": false, "score": 30 },
    "..."
  ]
}
```

```bash
curl -s "http://localhost:8000/busyness?scenario=2025-08-21&time=2025-08-21T19:15:00Z"
```

### `GET /sister-airports`

Nearby airports that are **less busy** than a given airport at a time — offload /
diversion candidates. Scores every NYC-metro airport (same model as `/busyness`)
and returns those scoring below the primary, **least busy first** (so the most
spare capacity is first; nearest breaks ties). Distances are great-circle nm from
airport coordinates derived from the snapshot's route endpoints.

| Query            | Required | Description                                                         |
| ---------------- | -------- | ------------------------------------------------------------------- |
| `airport`        | yes      | Primary airport ICAO to relieve, e.g. `KLGA`.                       |
| `scenario`       | no       | Scenario id (`YYYY-MM-DD`); defaults to the earliest.               |
| `time`           | no       | ISO-8601 center time; defaults to the window midpoint.              |
| `radius_nm`      | no       | Proximity filter in nm (`>0`); omit to consider the whole metro.    |
| `window_minutes` | no       | 5–240, default 60.                                                  |

**Response** — `less_busy_by` = `primary.score − airport.score`. `distance_nm` is
`null` for an airport with no flights in the scenario (can't be located); those are
excluded when `radius_nm` is set.

```json
{
  "scenario": "2025-08-21",
  "time": "2025-08-21T19:15:00+00:00",
  "window_minutes": 60,
  "radius_nm": null,
  "primary": { "airport": "KLGA", "inbound": 34, "outbound": 41, "movements": 75, "capacity": 40, "has_capacity": true, "score": 94 },
  "sisters": [
    { "airport": "KBDR", "inbound": 0, "outbound": 0, "movements": 0, "capacity": null, "has_capacity": false, "score": 0, "distance_nm": 41.0, "less_busy_by": 94 },
    { "airport": "KLDJ", "inbound": 0, "outbound": 0, "movements": 0, "capacity": null, "has_capacity": false, "score": 0, "distance_nm": null, "less_busy_by": 94 },
    "...",
    { "airport": "KTEB", "inbound": 16, "outbound": 15, "movements": 31, "capacity": null, "has_capacity": false, "score": 30, "distance_nm": 9.6, "less_busy_by": 64 }
  ]
}
```

```bash
# whole metro, least busy first
curl -s "http://localhost:8000/sister-airports?airport=KLGA&scenario=2025-08-21&time=2025-08-21T19:15:00Z"
# only candidates within 25 nm
curl -s "http://localhost:8000/sister-airports?airport=KLGA&time=2025-08-21T19:15:00Z&radius_nm=25"
```

---

### Storage

`/refresh` and `/capacity_rates/refresh` write to a SQLite DB (default
`backend/arrivals.db`, override with `$ARRIVALS_DB`). Two tables — demand (one
row per `(day, airport, 5-min bucket)`) and capacity (one row per airport):

```sql
CREATE TABLE flight_frequency (
    day          TEXT    NOT NULL,  -- 'YYYY-MM-DD'
    direction    TEXT    NOT NULL,  -- 'arrival' | 'departure'
    sector       TEXT,              -- LOW sector covering the airport, or NULL
    airport      TEXT    NOT NULL,  -- endpoint airport ICAO (origin or destination)
    bucket_start TEXT    NOT NULL,  -- ISO-8601 UTC, start of 5-minute window
    flight_count INTEGER NOT NULL,
    PRIMARY KEY (day, direction, airport, bucket_start)
);

CREATE TABLE airport_capacity (
    airport TEXT    PRIMARY KEY,  -- destination ICAO
    aar     INTEGER NOT NULL,     -- VMC Airport Arrival Rate, arrivals/hour
    source  TEXT                  -- provenance of the AAR value
);
```

---

### Errors

| Status | When                                                                    |
| ------ | ----------------------------------------------------------------------- |
| `400`  | Empty sector list (GET), unknown sector name(s), or unparseable `time`. |
| `404`  | Unknown `scenario`/`day`, or no stored data for the requested airports. |
| `422`  | Request body fails validation (e.g. empty `sector_names`/`airports`).   |
| `500`  | `/refresh` found no NYC dataset files under `data/nyc_dataset/`.        |
