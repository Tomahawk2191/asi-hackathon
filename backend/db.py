"""SQLite storage for NYC-metro arrival frequency and airport capacity.

Two tables:

- ``arrival_frequency`` -- per-(day, airport, 5-min bucket) arrival counts
  (demand). Writes are idempotent per day: refreshing a day replaces that day's
  rows.
- ``airport_capacity`` -- one VMC AAR (arrivals/hour) per airport (the capacity
  reference, sibling to demand). Writes replace the whole curated table.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Iterable, Optional, Union

PathLike = Union[str, Path]

# Default DB lives next to the backend code; override with $ARRIVALS_DB.
DEFAULT_DB_PATH = Path(os.environ.get("ARRIVALS_DB") or (Path(__file__).resolve().parent / "arrivals.db"))

_COLUMNS = "day, direction, sector, airport, bucket_start, flight_count"

SCHEMA = """
CREATE TABLE IF NOT EXISTS flight_frequency (
    day          TEXT    NOT NULL,  -- 'YYYY-MM-DD'
    direction    TEXT    NOT NULL,  -- 'arrival' | 'departure'
    sector       TEXT,              -- LOW sector covering the airport, or NULL
    airport      TEXT    NOT NULL,  -- endpoint airport ICAO (origin or destination)
    bucket_start TEXT    NOT NULL,  -- ISO-8601 UTC, start of 5-minute window
    flight_count INTEGER NOT NULL,
    PRIMARY KEY (day, direction, airport, bucket_start)
);
CREATE INDEX IF NOT EXISTS idx_flight_frequency_day_sector ON flight_frequency(day, sector);

CREATE TABLE IF NOT EXISTS airport_capacity (
    airport TEXT    PRIMARY KEY,  -- destination ICAO
    aar     INTEGER NOT NULL,     -- VMC Airport Arrival Rate, arrivals/hour
    source  TEXT                  -- provenance of the AAR value
);
"""


def connect(db_path: PathLike = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open a connection (creating the file) with the schema ensured."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def write_day(
    conn: sqlite3.Connection,
    day: str,
    direction: str,
    rows: Iterable[dict],
) -> int:
    """Replace ``(day, direction)``'s rows with ``rows``; returns the count.

    Each row needs keys: ``sector``, ``airport``, ``bucket_start``,
    ``flight_count``. Runs in a single transaction.
    """
    rows = list(rows)
    with conn:  # commit/rollback transaction
        conn.execute(
            "DELETE FROM flight_frequency WHERE day = ? AND direction = ?",
            (day, direction),
        )
        conn.executemany(
            f"INSERT INTO flight_frequency ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (day, direction, r["sector"], r["airport"], r["bucket_start"], r["flight_count"])
                for r in rows
            ],
        )
    return len(rows)


def read_day(
    conn: sqlite3.Connection,
    day: str,
    direction: str,
    sector: Optional[str] = None,
) -> list[dict]:
    """Read a (day, direction)'s rows, optionally one sector, time-ordered."""
    query = f"SELECT {_COLUMNS} FROM flight_frequency WHERE day = ? AND direction = ?"
    params: list = [day, direction]
    if sector is not None:
        query += " AND sector = ?"
        params.append(sector)
    query += " ORDER BY bucket_start, airport"
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def read_airport_rows(
    conn: sqlite3.Connection,
    direction: str,
    airports: Iterable[str],
    day: Optional[str] = None,
) -> list[dict]:
    """All stored rows for a set of airports in one direction.

    Optionally restricted to a day. Returns an empty list if ``airports`` is
    empty. The closest-time selection is done by the caller so timestamp
    parsing stays in Python.
    """
    airports = list(airports)
    if not airports:
        return []
    placeholders = ",".join("?" for _ in airports)
    query = (
        f"SELECT {_COLUMNS} FROM flight_frequency "
        f"WHERE direction = ? AND airport IN ({placeholders})"
    )
    params: list = [direction, *airports]
    if day is not None:
        query += " AND day = ?"
        params.append(day)
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def write_capacity(conn: sqlite3.Connection, rows: Iterable[dict]) -> int:
    """Replace the whole ``airport_capacity`` table with ``rows``.

    Each row needs keys ``airport`` and ``aar``; ``source`` is optional. The
    curated capacity table is small and seeded as a unit, so a refresh clears it
    and rewrites -- idempotent: re-seeding replaces, never duplicates. Returns
    the number of rows written.
    """
    rows = list(rows)
    with conn:  # commit/rollback transaction
        conn.execute("DELETE FROM airport_capacity")
        conn.executemany(
            "INSERT INTO airport_capacity (airport, aar, source) VALUES (?, ?, ?)",
            [(r["airport"], r["aar"], r.get("source")) for r in rows],
        )
    return len(rows)


def read_capacity(
    conn: sqlite3.Connection,
    airports: Optional[Iterable[str]] = None,
) -> list[dict]:
    """Read stored AARs, optionally restricted to a set of airports.

    Returns rows ``{"airport", "aar", "source"}`` ordered by airport.
    """
    query = "SELECT airport, aar, source FROM airport_capacity"
    params: list = []
    if airports is not None:
        airports = list(airports)
        if not airports:
            return []
        placeholders = ",".join("?" for _ in airports)
        query += f" WHERE airport IN ({placeholders})"
        params = list(airports)
    query += " ORDER BY airport"
    return [dict(row) for row in conn.execute(query, params).fetchall()]
