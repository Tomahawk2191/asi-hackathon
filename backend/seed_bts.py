"""Seed BTS On-Time Performance arrivals into arrivals.db.

Usage:
    python backend/seed_bts.py <path-to-bts_YYYY_MM.zip> [--metro all|nyc|lax|...]

Reads the BTS CSV once, extracts arrivals for every configured metro area,
converts local arrival times to UTC 5-minute buckets, and upserts each day
into the DB as direction='arrival'. Sector is NULL (BTS has no sector routing).

December uses standard time throughout (no DST).
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db

BTS_CSV = "On_Time_Reporting_Carrier_On_Time_Performance_(1987_present)_2025_12.csv"
DAY = "2025-12-25"


class Metro(NamedTuple):
    name: str
    airports: dict[str, str]  # IATA -> ICAO
    utc_offset: int            # hours from UTC (negative = west); December standard time


METROS: dict[str, Metro] = {
    "nyc": Metro("nyc", {"JFK": "KJFK", "LGA": "KLGA", "EWR": "KEWR"}, -5),
    "atlanta": Metro("atlanta", {"ATL": "KATL"}, -5),
    "boston": Metro("boston", {"BOS": "KBOS"}, -5),
    "miami": Metro("miami", {"MIA": "KMIA", "FLL": "KFLL"}, -5),
    "chicago": Metro("chicago", {"ORD": "KORD", "MDW": "KMDW"}, -6),
    "dallas": Metro("dallas", {"DFW": "KDFW", "DAL": "KDAL"}, -6),
    "denver": Metro("denver", {"DEN": "KDEN"}, -7),
    "phoenix": Metro("phoenix", {"PHX": "KPHX"}, -7),
    "lax": Metro("lax", {"LAX": "KLAX", "BUR": "KBUR", "LGB": "KLGB",
                          "ONT": "KONT", "SNA": "KSNA"}, -8),
    "sfba": Metro("sfba", {"SFO": "KSFO", "OAK": "KOAK", "SJC": "KSJC"}, -8),
    "seattle": Metro("seattle", {"SEA": "KSEA"}, -8),
}


def _snap_to_5min(h: int, m: int) -> tuple[int, int]:
    """Floor (h, m) to the nearest 5-minute bucket."""
    return h, (m // 5) * 5


def parse_arrivals(
    zip_path: str,
    metros: list[Metro],
) -> dict[str, list[dict]]:
    """Parse the BTS CSV once and return {icao: [bucket rows]} for every metro.

    One pass over the CSV regardless of how many metros are requested.
    """
    # Build a flat IATA→(ICAO, utc_offset) lookup across all requested metros.
    iata_map: dict[str, tuple[str, int]] = {}
    for metro in metros:
        for iata, icao in metro.airports.items():
            iata_map[iata] = (icao, metro.utc_offset)

    # (icao, bucket_utc_str) → count
    buckets: dict[tuple[str, str], int] = defaultdict(int)

    with zipfile.ZipFile(zip_path) as z:
        with z.open(BTS_CSV) as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
            for row in reader:
                if row["FlightDate"] != DAY:
                    continue
                dest_iata = row["Dest"].strip()
                if dest_iata not in iata_map:
                    continue
                if row["Cancelled"].strip() not in ("", "0", "0.00"):
                    continue
                arr_time = row["ArrTime"].strip()
                if not arr_time:
                    continue

                icao, utc_offset = iata_map[dest_iata]
                hhmm = arr_time.zfill(4)
                h, m = int(hhmm[:2]), int(hhmm[2:])
                if h >= 24:
                    h -= 24
                h, m = _snap_to_5min(h, m)

                tz = timezone(timedelta(hours=utc_offset))
                local_dt = datetime(2025, 12, 25, h, m, tzinfo=tz)
                utc_str = local_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
                buckets[(icao, utc_str)] += 1

    # Group by ICAO into rows ready for db.write_day.
    by_icao: dict[str, list[dict]] = defaultdict(list)
    for (icao, ts), count in sorted(buckets.items()):
        by_icao[icao].append({
            "sector": None,
            "airport": icao,
            "bucket_start": ts,
            "flight_count": count,
        })
    return dict(by_icao)


def seed(zip_path: str, metros: list[Metro]) -> None:
    rows_by_icao = parse_arrivals(zip_path, metros)

    # Collect all rows regardless of metro, keyed by icao
    all_icaos = {icao for metro in metros for icao in metro.airports.values()}

    by_metro: dict[str, dict[str, int]] = {m.name: {} for m in metros}
    for metro in metros:
        for icao in metro.airports.values():
            total = sum(r["flight_count"] for r in rows_by_icao.get(icao, []))
            by_metro[metro.name][icao] = total

    # One DB connection; write all rows in one transaction per direction/day
    # (write_day replaces the whole (day, direction) set, so we write once with
    # all airports merged -- not once per metro -- to avoid overwriting previous metros).
    conn = db.connect()
    try:
        existing = db.read_day(conn, DAY, "arrival")
        existing_icaos = {r["airport"] for r in existing}
        kept = [r for r in existing if r["airport"] not in all_icaos]
        new_rows = [r for icao in all_icaos for r in rows_by_icao.get(icao, [])]
        db.write_day(conn, DAY, "arrival", kept + new_rows)
    finally:
        conn.close()

    # Summary
    for metro in metros:
        totals = by_metro[metro.name]
        airports_str = "  ".join(
            f"{icao}: {totals.get(icao, 0)}" for icao in metro.airports.values()
        )
        print(f"{metro.name:10s}  {airports_str}")

    total_flights = sum(r["flight_count"] for rows in rows_by_icao.values() for r in rows)
    print(f"\nTotal arrivals seeded: {total_flights}  ({len(rows_by_icao)} airports, day {DAY})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("zip", help="Path to the BTS On-Time Performance ZIP")
    parser.add_argument(
        "--metro",
        default="all",
        help=f"Metro(s) to seed: all, or comma-separated from {list(METROS)}. Default: all.",
    )
    args = parser.parse_args()

    if args.metro == "all":
        chosen = list(METROS.values())
    else:
        names = [n.strip() for n in args.metro.split(",")]
        unknown = [n for n in names if n not in METROS]
        if unknown:
            print(f"Unknown metro(s): {unknown}. Available: {list(METROS)}")
            sys.exit(1)
        chosen = [METROS[n] for n in names]

    seed(args.zip, chosen)


if __name__ == "__main__":
    main()
