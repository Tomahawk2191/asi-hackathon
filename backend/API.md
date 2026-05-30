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

---

### `GET /`

Health check. Returns `{"message": "Hello from FastAPI"}`.

### `GET /scenarios`

Lists the scenario snapshot directories from the data bundle (the valid values for
the `scenario` field elsewhere) and the default used when `scenario` is omitted
(the earliest one).

```json
{ "scenarios": ["asked_at_2025-05-29T21:00:00Z", "..."], "default": "asked_at_2025-05-29T21:00:00Z" }
```

### `GET /sectors`

Summarizes every sector so you can pick names for `/landings`. Geometry is omitted.

```json
{ "count": 712,
  "sectors": [ { "name": "HIGH_006", "altitude_from_ft": 35000, "altitude_to_ft": 60000, "capacity": 20 }, "..." ] }
```

### `POST /landings`

Counts the flights that **land** within a set of sectors, grouped by arrival
airport. A flight lands in the set if its destination waypoint (the arrival
airport) falls inside any of the given sectors. Counts sum once across the set
(a flight in two of the listed sectors is still counted once).

> Landing happens at ground level, so pass **LOW** band sectors for meaningful
> results — the geometry test does not filter by altitude itself.

**Request body**

| Field          | Type        | Required | Description                                                      |
| -------------- | ----------- | -------- | ---------------------------------------------------------------- |
| `sector_names` | `string[]`  | yes      | Sectors defining the region, e.g. `["LOW_295"]` (min 1).         |
| `scenario`     | `string`    | no       | Scenario name (see `/scenarios`); defaults to the earliest.      |

**Response** (`per_airport` sorted high → low)

```json
{ "scenario": "asked_at_2025-08-21T18:00:00Z",
  "sector_names": ["LOW_295"],
  "total_flights": 866,
  "per_airport": { "KLGA": 264, "KEWR": 222, "KJFK": 209, "KHPN": 77, "KTEB": 71, "KFRG": 15, "KBLM": 8 } }
```

```bash
curl -s -X POST http://localhost:8000/landings \
  -H 'Content-Type: application/json' \
  -d '{"sector_names":["LOW_295"],"scenario":"asked_at_2025-08-21T18:00:00Z"}'
```

### `GET /landings`

Same result as `POST /landings`, for quick manual testing. Repeat `sectors` to
pass several; `scenario` is optional.

```bash
curl -s "http://localhost:8000/landings?sectors=LOW_295&sectors=LOW_296&scenario=asked_at_2025-08-21T18:00:00Z"
```

### `POST /refresh`

Builds the **NYC-metro arrival-frequency** table and writes it to SQLite. For
the given day it counts flights arriving at each NY-metro airport, bucketed into
5-minute windows by scheduled landing time, and tags each airport with the LOW
sector it sits in. Reads **only local bundle files** (`data/nyc_dataset/`) — no
network. Idempotent: re-running a day replaces that day's rows.

**Request body**

| Field | Type     | Required | Description                                                      |
| ----- | -------- | -------- | ---------------------------------------------------------------- |
| `day` | `string` | no       | Day as `YYYY-MM-DD` (one of the 5 NYC days). Omit to refresh all. |

**Response**

```json
{ "db_path": "/.../backend/arrivals.db",
  "total_flights": 894,
  "refreshed": [ { "day": "2025-08-21", "rows": 480, "flights": 894 } ] }
```

```bash
curl -s -X POST http://localhost:8000/refresh -H 'Content-Type: application/json' -d '{"day":"2025-08-21"}'
curl -s -X POST http://localhost:8000/refresh -H 'Content-Type: application/json' -d '{}'   # all days
```

### `GET /refresh`

Same as `POST /refresh`: `GET /refresh?day=2025-08-21` (omit `day` for all days).

### `GET /arrivals`

Reads back the stored rows for a day (refresh it first), optionally filtered to
one sector.

| Query    | Required | Description                          |
| -------- | -------- | ------------------------------------ |
| `day`    | yes      | Day to read, `YYYY-MM-DD`.           |
| `sector` | no       | Restrict to one sector, e.g. `LOW_295`. |

```json
{ "day": "2025-08-21", "sector": "LOW_295", "count": 449,
  "rows": [ { "day": "2025-08-21", "sector": "LOW_295", "airport": "KLGA",
              "bucket_start": "2025-08-21T18:00:00+00:00", "flight_count": 2 } ] }
```

```bash
curl -s "http://localhost:8000/arrivals?day=2025-08-21&sector=LOW_295"
```

### `POST /flights-inbound`

Inbound flight count for a set of airports at a given time. Finds the **closest
stored 5-minute bucket** to the requested time and returns each airport's inbound
flight count there. Reads from the SQLite DB, so refresh the relevant day first.

> This is the historic **arrivals-per-5-minutes** we store per airport (observed
> inbound throughput / demand), not a regulatory capacity limit — that time series
> is the only time-stamped per-airport data in the DB.

**Request body**

| Field      | Type       | Required | Description                                                  |
| ---------- | ---------- | -------- | ------------------------------------------------------------ |
| `airports` | `string[]` | yes      | ICAO codes (case-insensitive), e.g. `["KJFK","KLGA"]`.       |
| `time`     | `string`   | yes      | ISO-8601 timestamp, e.g. `2025-08-21T18:03:00Z`.             |
| `day`      | `string`   | no       | Restrict the search to one `YYYY-MM-DD`.                     |

**Response** — `flight_count` is `0` when the airport had no arrivals in the
matched window, and `null` when the airport has no stored data at all
(`has_data: false`).

```json
{ "requested_time": "2025-08-21T18:03:00+00:00",
  "matched_time": "2025-08-21T18:05:00+00:00",
  "offset_seconds": 120,
  "day": "2025-08-21",
  "airports": [
    { "airport": "KJFK", "sector": "LOW_295", "flight_count": 2, "has_data": true },
    { "airport": "KLGA", "sector": "LOW_295", "flight_count": 5, "has_data": true } ] }
```

```bash
curl -s -X POST http://localhost:8000/flights-inbound -H 'Content-Type: application/json' \
  -d '{"airports":["KJFK","KLGA","KEWR"],"time":"2025-08-21T18:03:00Z"}'
```

### `GET /flights-inbound`

Same as `POST /flights-inbound`: repeat `airports`, e.g.
`GET /flights-inbound?airports=KJFK&airports=KLGA&time=2025-08-21T18:03:00Z`.

---

### Storage

`/refresh` writes to a SQLite DB (default `backend/arrivals.db`, override with
`$ARRIVALS_DB`). Single table, one row per `(day, airport, 5-min bucket)`:

```sql
CREATE TABLE arrival_frequency (
    day          TEXT    NOT NULL,  -- 'YYYY-MM-DD'
    sector       TEXT,              -- LOW sector covering the airport, or NULL
    airport      TEXT    NOT NULL,  -- destination ICAO
    bucket_start TEXT    NOT NULL,  -- ISO-8601 UTC, start of 5-minute window
    flight_count INTEGER NOT NULL,
    PRIMARY KEY (day, airport, bucket_start)
);
```

---

### Errors

| Status | When                                                                       |
| ------ | -------------------------------------------------------------------------- |
| `400`  | Empty sector list (GET), unknown sector name(s), or unparseable `time`.      |
| `404`  | Unknown `scenario`/`day`, or no stored data for the requested airports.      |
| `422`  | Request body fails validation (e.g. empty `sector_names`/`airports`).        |
| `500`  | `/refresh` found no NYC dataset files under `data/nyc_dataset/`.            |
