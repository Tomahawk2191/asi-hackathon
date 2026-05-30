"""SQLite storage for NYC-metro arrival frequency.

One table, ``arrival_frequency``, holding per-(day, airport, 5-min bucket)
arrival counts. Writes are idempotent per day: refreshing a day replaces that
day's rows.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Iterable, Optional, Union

PathLike = Union[str, Path]

# Default DB lives next to the backend code; override with $ARRIVALS_DB.
DEFAULT_DB_PATH = Path(os.environ.get("ARRIVALS_DB") or (Path(__file__).resolve().parent / "arrivals.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS arrival_frequency (
    day          TEXT    NOT NULL,  -- 'YYYY-MM-DD'
    sector       TEXT,              -- LOW sector covering the airport, or NULL
    airport      TEXT    NOT NULL,  -- destination ICAO
    bucket_start TEXT    NOT NULL,  -- ISO-8601 UTC, start of 5-minute window
    flight_count INTEGER NOT NULL,
    PRIMARY KEY (day, airport, bucket_start)
);
CREATE INDEX IF NOT EXISTS idx_arrival_day_sector ON arrival_frequency(day, sector);
"""


def connect(db_path: PathLike = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open a connection (creating the file) with the schema ensured."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def write_day(conn: sqlite3.Connection, day: str, rows: Iterable[dict]) -> int:
    """Replace ``day``'s rows with ``rows``; returns the number written.

    Each row needs keys: ``sector``, ``airport``, ``bucket_start``,
    ``flight_count``. Runs in a single transaction.
    """
    rows = list(rows)
    with conn:  # commit/rollback transaction
        conn.execute("DELETE FROM arrival_frequency WHERE day = ?", (day,))
        conn.executemany(
            "INSERT INTO arrival_frequency "
            "(day, sector, airport, bucket_start, flight_count) VALUES (?, ?, ?, ?, ?)",
            [
                (day, r["sector"], r["airport"], r["bucket_start"], r["flight_count"])
                for r in rows
            ],
        )
    return len(rows)


def read_day(
    conn: sqlite3.Connection,
    day: str,
    sector: Optional[str] = None,
) -> list[dict]:
    """Read a day's rows, optionally filtered to one sector, time-ordered."""
    query = (
        "SELECT day, sector, airport, bucket_start, flight_count "
        "FROM arrival_frequency WHERE day = ?"
    )
    params: list = [day]
    if sector is not None:
        query += " AND sector = ?"
        params.append(sector)
    query += " ORDER BY bucket_start, airport"
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def read_airport_rows(
    conn: sqlite3.Connection,
    airports: Iterable[str],
    day: Optional[str] = None,
) -> list[dict]:
    """All stored rows for a set of airports (optionally restricted to a day).

    Returns an empty list if ``airports`` is empty. The closest-time selection
    is done by the caller so timestamp parsing stays in Python.
    """
    airports = list(airports)
    if not airports:
        return []
    placeholders = ",".join("?" for _ in airports)
    query = (
        "SELECT day, sector, airport, bucket_start, flight_count "
        f"FROM arrival_frequency WHERE airport IN ({placeholders})"
    )
    params: list = list(airports)
    if day is not None:
        query += " AND day = ?"
        params.append(day)
    return [dict(row) for row in conn.execute(query, params).fetchall()]
