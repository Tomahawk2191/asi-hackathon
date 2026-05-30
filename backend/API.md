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

---

### Errors

| Status | When                                                                  |
| ------ | --------------------------------------------------------------------- |
| `400`  | Empty sector list (GET), or unknown sector name(s) (`detail.unknown`). |
| `404`  | Unknown `scenario` (`detail.available` lists valid values).           |
| `422`  | Request body fails validation (e.g. empty `sector_names` on POST).    |
