"""Demand-based airport load balancing (works for every seeded day + metro).

Unlike ``optimize.py`` (snapshot busyness, NYC-only), this runs off the SQLite
``flight_frequency`` arrival demand, so it covers Christmas 2025 and all 10
metro areas. For a day + instant it computes each airport's rolling-60-minute
arrival demand vs its VMC AAR (utilization), then rebalances arrivals *within
each metro* to minimize the metro's peak utilization — the before/after the
sidebar shows.

Reassignment stays inside a metro: you can shift a New York arrival from LGA to
JFK/EWR, never New York -> Los Angeles. ``scope`` selects which metros to
optimize ("all", or a single metro key like "nyc").
"""

from __future__ import annotations

from datetime import datetime, timedelta

from seed_bts import METROS

ROLLING_MINUTES = 60
BUCKET_MINUTES = 5


def icao_to_metro() -> dict[str, str]:
    """ICAO -> metro key (e.g. 'KJFK' -> 'nyc')."""
    out: dict[str, str] = {}
    for name, metro in METROS.items():
        for icao in metro.airports.values():
            out[icao] = name
    return out


def _snap5(t: datetime) -> datetime:
    return t.replace(minute=(t.minute // 5) * 5, second=0, microsecond=0)


def rolling_arrivals(rows: list[dict], t: datetime) -> int:
    """Arrivals in the 60 minutes ending at t (12 five-minute buckets)."""
    end = _snap5(t)
    start = end - timedelta(minutes=ROLLING_MINUTES - BUCKET_MINUTES)
    total = 0
    for r in rows:
        b = datetime.fromisoformat(r["bucket_start"])
        if start <= b <= end:
            total += int(r["flight_count"])
    return total


def _optimize_metro(airports: list[dict]) -> int:
    """Greedy minimax: move arrivals from the highest- to lowest-utilization
    airport in the metro while it strictly lowers the metro's peak. Mutates each
    airport dict's ``after`` field. Returns the number of reassignments."""
    if len(airports) < 2:
        return 0
    util = lambda a: a["after"] / a["aar"] if a["aar"] else 0.0
    moved = 0
    cap = sum(a["before"] for a in airports) + 1
    for _ in range(cap):
        busiest = max(airports, key=util)
        quietest = min(airports, key=util)
        if busiest is quietest or busiest["after"] <= 0:
            break
        peak_now = max(util(busiest), util(quietest))
        nb = (busiest["after"] - 1) / busiest["aar"]
        nq = (quietest["after"] + 1) / quietest["aar"]
        if max(nb, nq) < peak_now - 1e-9:
            busiest["after"] -= 1
            quietest["after"] += 1
            moved += 1
        else:
            break
    return moved


def rebalance(
    demand_rows: list[dict],
    aar_by_airport: dict[str, int],
    when: datetime,
    scope: str = "all",
) -> list[dict]:
    """Per-metro baseline + optimized airport load at ``when``.

    ``demand_rows`` are arrival rows (db.read_day(..., 'arrival')); only airports
    with a known AAR are included (the metro mains, not GA relievers).
    """
    by_airport: dict[str, list[dict]] = {}
    for r in demand_rows:
        by_airport.setdefault(r["airport"], []).append(r)

    to_metro = icao_to_metro()
    metros: dict[str, list[dict]] = {}
    for icao, aar in aar_by_airport.items():
        metro = to_metro.get(icao)
        if metro is None or not aar:
            continue
        if scope != "all" and metro != scope:
            continue
        arrivals = rolling_arrivals(by_airport.get(icao, []), when)
        metros.setdefault(metro, []).append(
            {"airport": icao, "aar": aar, "before": arrivals, "after": arrivals}
        )

    out: list[dict] = []
    for metro, aps in metros.items():
        # When viewing everything, hide metros with no arrivals this day (e.g. the
        # NYC-only days carry no Chicago/LA demand). A focused scope always shows.
        if scope == "all" and sum(a["before"] for a in aps) == 0:
            continue
        moved = _optimize_metro(aps)
        rows = [
            {
                "airport": a["airport"],
                "metro": metro,
                "aar": a["aar"],
                "arrivals_before": a["before"],
                "arrivals_after": a["after"],
                "util_before": round(a["before"] / a["aar"], 3),
                "util_after": round(a["after"] / a["aar"], 3),
            }
            for a in aps
        ]
        rows.sort(key=lambda r: (-r["util_before"], r["airport"]))
        out.append(
            {
                "metro": metro,
                "peak_before": max((r["util_before"] for r in rows), default=0.0),
                "peak_after": max((r["util_after"] for r in rows), default=0.0),
                "moved": moved,
                "airports": rows,
            }
        )
    out.sort(key=lambda m: (-m["peak_before"], m["metro"]))
    return out
