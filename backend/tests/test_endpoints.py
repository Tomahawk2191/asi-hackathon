"""Integration tests for the capacity / overload endpoints via TestClient."""

from __future__ import annotations

from datetime import datetime, timedelta

import db


def _seed_demand(db_path, day, airport, counts, start="12:00"):
    """Write synthetic arrival_frequency rows for one airport on one day."""
    t0 = datetime.fromisoformat(f"{day}T{start}:00+00:00")
    rows = [
        {
            "sector": "LOW_295",
            "airport": airport,
            "bucket_start": (t0 + timedelta(minutes=5 * i)).isoformat(),
            "flight_count": c,
        }
        for i, c in enumerate(counts)
    ]
    conn = db.connect(db_path)
    try:
        db.write_day(conn, day, rows)
    finally:
        conn.close()


def test_capacity_rates_returns_seeded_aar(client):
    resp = client.get("/capacity_rates")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 3
    aar = {r["airport"]: r["aar"] for r in body["rates"]}
    assert aar == {"KJFK": 52, "KLGA": 40, "KEWR": 52}


def test_capacity_rates_airport_filter(client):
    resp = client.get("/capacity_rates", params={"airports": ["klga"]})  # case-insensitive
    assert resp.status_code == 200
    assert [r["airport"] for r in resp.json()["rates"]] == ["KLGA"]


def test_capacity_rates_reliever_is_no_data(client):
    resp = client.get("/capacity_rates", params={"airports": ["KTEB"]})
    assert resp.status_code == 200
    assert resp.json()["rates"] == []  # relievers have no AAR


def test_capacity_rates_refresh_writes_three_rows(client):
    resp = client.post("/capacity_rates/refresh")
    assert resp.status_code == 200
    assert resp.json()["written"] == 3


def test_overload_flags_oversaturated_windows(client, db_path):
    # 4 arrivals / 5 min at KLGA == 48/hr > AAR 40.
    _seed_demand(db_path, "2025-01-01", "KLGA", [4] * 12)
    resp = client.get("/overload", params={"day": "2025-01-01", "airport": "KLGA"})
    assert resp.status_code == 200
    klga = resp.json()["airports"][0]
    assert klga["airport"] == "KLGA"
    assert klga["aar"] == 40
    assert klga["peak_rolling_arrivals"] == 48
    assert klga["overloaded_window_count"] == 2


def test_overload_all_airports_when_unfiltered(client, db_path):
    _seed_demand(db_path, "2025-01-01", "KLGA", [1, 1])
    resp = client.get("/overload", params={"day": "2025-01-01"})
    assert resp.status_code == 200
    assert {a["airport"] for a in resp.json()["airports"]} == {"KJFK", "KLGA", "KEWR"}


def test_overload_unrefreshed_day_404(client):
    resp = client.get("/overload", params={"day": "1999-01-01"})
    assert resp.status_code == 404


def test_overload_airport_without_capacity_404(client, db_path):
    _seed_demand(db_path, "2025-01-01", "KLGA", [1])
    resp = client.get("/overload", params={"day": "2025-01-01", "airport": "KTEB"})
    assert resp.status_code == 404
