# Using the API — a quick walkthrough

Task-oriented guide to the ASI air-traffic backend. For the full per-endpoint
reference (every field, schema, error code) see [`API.md`](./API.md).

## 1. Start it

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload          # http://localhost:8000  (Swagger UI at /docs)
```

Everything is local — the API reads the committed datasets under `data/`; no
network or external bundle is needed.

## 2. Concepts you need

- **Scenario** — one day of NYC-metro flights, identified by its date
  (`YYYY-MM-DD`). List them with `GET /scenarios`; the default (when you omit
  `scenario`) is the earliest. Each "day" is an ~18 h window (~noon → 6 am EDT),
  **not** a calendar day.
- **Time** — UTC ISO-8601, e.g. `2025-08-21T19:15:00Z`. Where a `time` is
  optional it defaults to the scenario's **window midpoint**.
- **NYC metro** — core `KJFK / KLGA / KEWR` plus relievers (`KTEB`, `KHPN`,
  `KFRG`, `KISP`, …). Counts only ever include these airports.
- **Two data paths:**
  - **Live from the snapshot** — `/busyness`, `/sister-airports`, `/landings`,
    `/scenarios/{id}/routes`. No setup; computed on demand.
  - **Pre-aggregated in SQLite** — `/arrivals`, `/departures`, `/overload`,
    `/flights-inbound`, `/departure-capacity`. **Run `POST /refresh` first** to
    build the per-5-minute tables for the day (see Recipe C).

---

## Recipe A — How busy is each airport at a given time?

`GET /busyness` scores every NYC-metro airport for a window centered on `time`,
busiest first. It blends **inbound** (arrivals) + **outbound** (departures)
against the airport's **inbound capacity** (VMC AAR) into a rough 0–100 score
(~100 ≈ a core airport at practical capacity; relievers, which have no FAA
capacity profile, report `capacity: null`).

```bash
curl -s "http://localhost:8000/busyness?scenario=2025-08-21&time=2025-08-21T19:15:00Z"
```

```jsonc
{
  "scenario": "2025-08-21",
  "time": "2025-08-21T19:15:00+00:00",
  "window_minutes": 60,
  "airports": [
    { "airport": "KLGA", "inbound": 34, "outbound": 41, "movements": 75, "capacity": 40, "has_capacity": true,  "score": 94 },
    { "airport": "KEWR", "inbound": 17, "outbound": 33, "movements": 50, "capacity": 52, "has_capacity": true,  "score": 48 },
    { "airport": "KTEB", "inbound": 16, "outbound": 15, "movements": 31, "capacity": null, "has_capacity": false, "score": 30 }
    // …
  ]
}
```

- Omit `time` to use the window midpoint; omit `scenario` for the earliest day.
- `window_minutes` (5–240, default 60) widens/narrows the window around `time`.
- The headline `score` is an estimate — `inbound`, `outbound`, `movements`, and
  `capacity` are all returned, so you can recompute it however you like.

## Recipe B — Where can I send overflow from a busy airport?

`GET /sister-airports` ranks the *other* metro airports that are **less busy**
than your airport at that time — offload / diversion candidates — least busy
first, each with its great-circle `distance_nm` and how much less busy it is
(`less_busy_by`).

```bash
# whole metro, least busy first
curl -s "http://localhost:8000/sister-airports?airport=KLGA&scenario=2025-08-21&time=2025-08-21T19:15:00Z"

# only candidates within 25 nm (the realistic ones)
curl -s "http://localhost:8000/sister-airports?airport=KLGA&time=2025-08-21T19:15:00Z&radius_nm=25"
```

```jsonc
{
  "primary": { "airport": "KLGA", "score": 94, "movements": 75, "capacity": 40, "...": "" },
  "radius_nm": 25,
  "sisters": [
    { "airport": "KMMU", "score":  2, "distance_nm": 24.7, "less_busy_by": 92, "...": "" },
    { "airport": "KHPN", "score": 23, "distance_nm": 18.9, "less_busy_by": 71, "...": "" },
    { "airport": "KTEB", "score": 30, "distance_nm":  9.6, "less_busy_by": 64, "...": "" }
    // …
  ]
}
```

Tips:
- **`radius_nm` is the key knob.** Without it you get the whole metro, so tiny GA
  fields (score ≈ 0) sort to the top. Add a radius — and/or filter on
  `has_capacity` / `movements` client-side — to get viable, real-world relievers
  (e.g. Teterboro `KTEB`, White Plains `KHPN` for `KLGA`).
- `distance_nm` is `null` for an airport with no flights in the scenario (it
  can't be located); such airports are dropped when `radius_nm` is set.
- Sweep `time` across the day to see *when* a sister has the most spare capacity.

## Recipe C — Demand vs. capacity over a whole day (rolling hour)

This path uses the SQLite tables, so **refresh first**, then read.

```bash
# 1. build the 5-minute arrival/departure tables for the day (idempotent)
curl -s -X POST http://localhost:8000/refresh -H 'Content-Type: application/json' \
  -d '{"day":"2025-08-21"}'

# 2. rolling-60-min arrival demand vs the VMC AAR, with overload windows flagged
curl -s "http://localhost:8000/overload?day=2025-08-21&airport=KLGA"

# raw per-5-min series, if you want them
curl -s "http://localhost:8000/arrivals?day=2025-08-21&sector=LOW_295"
curl -s "http://localhost:8000/departures?day=2025-08-21&sector=LOW_295"
```

`/overload` is arrivals-only (the AAR is an arrival rate); a window is flagged
when rolling-60-min arrivals exceed the AAR.

## Recipe D — Which flights land in a region?

`POST /landings` counts arrivals by airport for a set of **sectors** (pass
**LOW** sectors — landings happen at ground level).

```bash
curl -s -X POST http://localhost:8000/landings \
  -H 'Content-Type: application/json' \
  -d '{"sector_names":["LOW_295"],"scenario":"2025-08-21"}'
```

---

## Gotchas

- **`/busyness` & `/sister-airports` need no refresh** (live from the snapshot);
  **`/overload`, `/arrivals`, `/departures` do** (call `POST /refresh` first, or
  they return 404 "Call /refresh first").
- **Capacity (AAR) exists only for the core three** (`KJFK/KLGA/KEWR`). Relievers
  show `capacity: null` and are scored on a reference rate.
- **The score is a POC estimate**, not an exact movement rate — good for ranking
  and "less busy than X", not for regulatory use.
- **Windows are ~18 h**, so a `time` near the edges sees a partial hour, and a
  `time` outside the window returns all-zero counts (no error).
- **Times are UTC**; the frontend must run on a `localhost` port (CORS).
```
