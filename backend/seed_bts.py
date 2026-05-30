"""Seed Christmas 2025 BTS arrivals into arrivals.db.

Usage:
    python backend/seed_bts.py <path-to-bts_2025_12.zip>

Parses the BTS On-Time Performance CSV for 2025-12-25, extracts JFK/LGA/EWR
arrivals, buckets by 5-minute UTC windows, and writes to the DB as day
'2025-12-25' direction 'arrival'. Sector is NULL (BTS has no sector routing).
"""

from __future__ import annotations

import csv
import io
import sys
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add backend/ to sys.path so we can import db
sys.path.insert(0, str(Path(__file__).resolve().parent))
import db

NYC_IATA_TO_ICAO = {"JFK": "KJFK", "LGA": "KLGA", "EWR": "KEWR"}
EST = timezone(timedelta(hours=-5))  # December is Eastern Standard Time
DAY = "2025-12-25"
BTS_CSV = "On_Time_Reporting_Carrier_On_Time_Performance_(1987_present)_2025_12.csv"


def parse_arrivals(zip_path: str) -> list[dict]:
    buckets: dict[tuple[str, str], int] = defaultdict(int)

    with zipfile.ZipFile(zip_path) as z:
        with z.open(BTS_CSV) as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
            for row in reader:
                if row["FlightDate"] != DAY:
                    continue
                dest_iata = row["Dest"].strip()
                if dest_iata not in NYC_IATA_TO_ICAO:
                    continue
                cancelled = row["Cancelled"].strip()
                if cancelled not in ("", "0", "0.00"):
                    continue
                arr_time = row["ArrTime"].strip()
                if not arr_time:
                    continue

                icao = NYC_IATA_TO_ICAO[dest_iata]
                hhmm = arr_time.zfill(4)
                h, m = int(hhmm[:2]), int(hhmm[2:])
                if h >= 24:
                    h = h - 24  # midnight/next-day edge case — keep on Dec 25
                m_bucket = (m // 5) * 5
                local_dt = datetime(2025, 12, 25, h, m_bucket, tzinfo=EST)
                utc_str = local_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
                buckets[(icao, utc_str)] += 1

    return [
        {"sector": None, "airport": icao, "bucket_start": ts, "flight_count": count}
        for (icao, ts), count in sorted(buckets.items())
    ]


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python seed_bts.py <path-to-bts_2025_12.zip>")
        sys.exit(1)

    zip_path = sys.argv[1]
    rows = parse_arrivals(zip_path)

    by_airport: dict[str, int] = defaultdict(int)
    for r in rows:
        by_airport[r["airport"]] += r["flight_count"]

    print(f"Parsed {len(rows)} buckets  ({sum(by_airport.values())} flights)")
    for ap, cnt in sorted(by_airport.items()):
        print(f"  {ap}: {cnt} arrivals")

    conn = db.connect()
    n = db.write_day(conn, DAY, "arrival", rows)
    conn.close()
    print(f"Wrote {n} rows to DB for {DAY}")


if __name__ == "__main__":
    main()
