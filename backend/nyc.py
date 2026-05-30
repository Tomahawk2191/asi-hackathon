"""NYC-metro flight frequency (arrivals and departures).

Counts flights at each NY-metro airport, bucketed into 5-minute windows, and
tags each airport with the LOW sector its footprint sits in. The two directions
share one code path and differ only in which flight endpoint they look at:

- **arrival**   -- group by destination, bucket by scheduled landing time,
  locate the sector at the last route waypoint (the arrival airport).
- **departure** -- group by origin, bucket by take-off time, locate the sector
  at the first route waypoint (the departure airport).

Reads only local bundle files (``data/nyc_dataset/nyc_<YYYY-MM-DD>.json``) --
no network access. Reference: data/nyc_dataset/README.md
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from flights import RoutesSnapshot
from sectors import Sector

NYC_DIR = Path(__file__).resolve().parent.parent / "data" / "nyc_dataset"

# Canonical NY-metro airport set (matches the nyc_dataset manifest). Used as a
# fallback when a snapshot carries no embedded ``nyc_filter``.
NYC_CORE = ("KEWR", "KJFK", "KLGA")
NYC_METRO_EXTRA = ("KBDR", "KCDW", "KFRG", "KHPN", "KISP", "KLDJ", "KMMU", "KSWF", "KTEB")

BUCKET_MINUTES = 5


@dataclass(frozen=True)
class Direction:
    """One flight endpoint to count -- an arrival or a departure.

    Captures everything that differs between the two so the counting logic can
    stay direction-agnostic.
    """

    name: str  # "arrival" | "departure" (also the value stored in SQLite)
    airport_attr: str  # Flight field naming the NY-metro airport to group/filter on
    time_attr: str  # Flight field with the timestamp to bucket
    waypoint: int  # index into lats/lons used to locate the airport's sector


ARRIVAL = Direction("arrival", "destination_airport_icao", "scheduled_landing_time", -1)
DEPARTURE = Direction("departure", "origin_airport_icao", "take_off_time", 0)
DIRECTIONS: dict[str, Direction] = {d.name: d for d in (ARRIVAL, DEPARTURE)}


def available_days() -> list[str]:
    """List the dates (``YYYY-MM-DD``) for which a NYC dataset file exists."""
    if not NYC_DIR.exists():
        return []
    return sorted(p.stem[len("nyc_"):] for p in NYC_DIR.glob("nyc_*.json"))


def day_file(day: str) -> Path:
    """Path to a given day's NYC routes file. Raises if it does not exist."""
    path = NYC_DIR / f"nyc_{day}.json"
    if not path.exists():
        raise FileNotFoundError(f"No NYC dataset file for day {day!r}: {path}")
    return path


def metro_airports(snapshot: RoutesSnapshot) -> set[str]:
    """The NY-metro airport set: the snapshot's own filter, else the default."""
    flt = snapshot.nyc_filter
    if flt is not None:
        return set(flt.core) | set(flt.metro_extra)
    return set(NYC_CORE) | set(NYC_METRO_EXTRA)


def _floor_bucket(when: datetime) -> datetime:
    """Floor a timestamp down to the start of its 5-minute window."""
    return when.replace(
        minute=(when.minute // BUCKET_MINUTES) * BUCKET_MINUTES,
        second=0,
        microsecond=0,
    )


def _sector_for_point(lon: float, lat: float, low_sectors: list[Sector]) -> Optional[str]:
    """Name of the LOW sector whose footprint contains the point, or None."""
    for sector in low_sectors:
        if sector.contains(lon, lat):
            return sector.name
    return None


def flight_frequency(
    snapshot: RoutesSnapshot,
    sectors: Iterable[Sector],
    direction: Direction,
) -> list[dict]:
    """Per-(airport, 5-min bucket) flight counts for NY-metro airports.

    A flight contributes if the airport at ``direction``'s endpoint (origin for
    departures, destination for arrivals) is a NY-metro airport. It is bucketed
    by ``direction``'s timestamp and tagged with the LOW sector that airport
    sits in (constant per airport).

    Returns a list of rows sorted by (bucket_start, airport):
        {"sector": str | None, "airport": str,
         "bucket_start": ISO-8601 UTC str, "flight_count": int}
    """
    low_sectors = [s for s in sectors if s.name.startswith("LOW_")]
    metro = metro_airports(snapshot)

    airport_sector: dict[str, Optional[str]] = {}
    counts: dict[tuple[str, str], int] = {}

    for flight in snapshot.flights:
        airport = getattr(flight, direction.airport_attr)
        if airport not in metro or not flight.lats or not flight.lons:
            continue
        if airport not in airport_sector:
            airport_sector[airport] = _sector_for_point(
                flight.lons[direction.waypoint],
                flight.lats[direction.waypoint],
                low_sectors,
            )
        bucket = _floor_bucket(getattr(flight, direction.time_attr)).isoformat()
        counts[(airport, bucket)] = counts.get((airport, bucket), 0) + 1

    rows = [
        {
            "sector": airport_sector[airport],
            "airport": airport,
            "bucket_start": bucket,
            "flight_count": count,
        }
        for (airport, bucket), count in counts.items()
    ]
    rows.sort(key=lambda r: (r["bucket_start"], r["airport"]))
    return rows
