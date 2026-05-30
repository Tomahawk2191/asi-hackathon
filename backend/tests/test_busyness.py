"""Tests for the airport busyness score + sister-airport finder.

Three layers: the pure score math (``busyness.score_airport``), the windowed
counting/ordering on a tiny in-memory snapshot, and the HTTP endpoints against
the real ``data/`` files via the shared ``client`` fixture. None of this touches
SQLite -- busyness is computed live from snapshots.
"""

from __future__ import annotations

import airports
import busyness
from flights import Flight, NycFilter, RoutesSnapshot


# --- pure score math --------------------------------------------------------


def test_score_components_and_movements():
    s = busyness.score_airport(inbound=12, outbound=8, aar=40)
    assert s["inbound"] == 12 and s["outbound"] == 8
    assert s["movements"] == 20
    assert s["capacity"] == 40 and s["has_capacity"] is True


def test_score_is_100_at_practical_capacity():
    # A balanced airport doing AAR arrivals + AAR departures = 2*AAR movements.
    assert busyness.score_airport(40, 40, 40)["score"] == 100
    assert busyness.score_airport(0, 0, 40)["score"] == 0


def test_score_monotonic_in_movements():
    quiet = busyness.score_airport(5, 5, 40)["score"]
    busy = busyness.score_airport(20, 20, 40)["score"]
    assert busy > quiet


def test_relievers_use_the_reference_aar():
    # No FAA profile -> capacity echoes None, but the score is computed as if the
    # airport had the busiest-core reference AAR.
    reliever = busyness.score_airport(10, 10, None)
    assert reliever["capacity"] is None and reliever["has_capacity"] is False
    assert reliever["score"] == busyness.score_airport(10, 10, busyness.REFERENCE_AAR)["score"]


# --- windowed counting on a synthetic snapshot ------------------------------


def _flight(number, origin, dest, takeoff, landing, o_pt, d_pt):
    """A minimal 2-waypoint flight (origin point -> destination point)."""
    return Flight(
        flight_number=number,
        take_off_time=takeoff,
        scheduled_landing_time=landing,
        origin_airport_icao=origin,
        destination_airport_icao=dest,
        cruise_altitude_ft=35000,
        cruise_speed_kt=450,
        lons=[o_pt[0], d_pt[0]],
        lats=[o_pt[1], d_pt[1]],
        is_airborne=True,
    )


# Distinct coordinates so distances are well defined; KBOS is outside the metro.
PT = {
    "KLGA": (-73.87, 40.78),
    "KJFK": (-73.78, 40.64),
    "KEWR": (-74.17, 40.69),
    "KTEB": (-74.06, 40.85),
    "KBOS": (-71.01, 42.36),
}


def _synthetic_snapshot():
    """A 2-hour window (11:00-13:00) centered on 12:00 with known traffic."""
    d = "2025-01-01"
    flights = [
        # 3 arrivals into KLGA (external origin so only the arrival counts)
        _flight("A1", "KBOS", "KLGA", f"{d}T11:40:00Z", f"{d}T11:50:00Z", PT["KBOS"], PT["KLGA"]),
        _flight("A2", "KBOS", "KLGA", f"{d}T12:00:00Z", f"{d}T12:10:00Z", PT["KBOS"], PT["KLGA"]),
        _flight("A3", "KBOS", "KLGA", f"{d}T12:20:00Z", f"{d}T12:30:00Z", PT["KBOS"], PT["KLGA"]),
        # 2 departures out of KLGA
        _flight("D1", "KLGA", "KBOS", f"{d}T11:55:00Z", f"{d}T13:05:00Z", PT["KLGA"], PT["KBOS"]),
        _flight("D2", "KLGA", "KBOS", f"{d}T12:20:00Z", f"{d}T13:30:00Z", PT["KLGA"], PT["KBOS"]),
        # 1 external arrival into KTEB
        _flight("A4", "KBOS", "KTEB", f"{d}T11:55:00Z", f"{d}T12:05:00Z", PT["KBOS"], PT["KTEB"]),
        # intra-metro hop: KLGA departure AND KTEB arrival (counts on both)
        _flight("H1", "KLGA", "KTEB", f"{d}T12:00:00Z", f"{d}T12:15:00Z", PT["KLGA"], PT["KTEB"]),
        # outside the window -> must not be counted
        _flight("X1", "KBOS", "KLGA", f"{d}T08:50:00Z", f"{d}T09:00:00Z", PT["KBOS"], PT["KLGA"]),
    ]
    return RoutesSnapshot(
        asked_at=f"{d}T12:00:00Z",
        window_start=f"{d}T11:00:00Z",
        window_end=f"{d}T13:00:00Z",
        nyc_filter=NycFilter(core=["KJFK", "KLGA", "KEWR"], metro_extra=["KTEB"]),
        flights=flights,
    )


def _center():
    from datetime import datetime

    return datetime.fromisoformat("2025-01-01T12:00:00+00:00")


def test_count_in_window_counts_both_directions_and_respects_the_window():
    counts = busyness.count_in_window(_synthetic_snapshot(), _center(), window_minutes=120)
    # KLGA: 3 arrivals (A1-A3), 3 departures (D1, D2, hop H1); X1 is out of window.
    assert counts["KLGA"] == (3, 3)
    # KTEB: 2 arrivals (A4 + hop H1), 0 departures.
    assert counts["KTEB"] == (2, 0)
    # Quiet metro airports still appear, at zero.
    assert counts["KJFK"] == (0, 0)
    assert counts["KEWR"] == (0, 0)


def test_airport_busyness_orders_busiest_first():
    rows = busyness.airport_busyness(_synthetic_snapshot(), _center(), window_minutes=120)
    assert [r["airport"] for r in rows[:2]] == ["KLGA", "KTEB"]
    assert rows[0]["movements"] == 6 and rows[1]["movements"] == 2
    # Score descending overall.
    scores = [r["score"] for r in rows]
    assert scores == sorted(scores, reverse=True)


# --- airport geometry -------------------------------------------------------


def test_airport_coords_and_distance():
    coords = airports.airport_coords(_synthetic_snapshot())
    assert coords["KLGA"] == PT["KLGA"]
    assert coords["KTEB"] == PT["KTEB"]
    # LGA <-> TEB is ~9-10 nm in reality (KJFK has no flights in this snapshot,
    # so it is intentionally absent from the derived coords).
    d = airports.great_circle_nm(coords["KLGA"], coords["KTEB"])
    assert 5 < d < 15
    assert airports.great_circle_nm(coords["KLGA"], coords["KLGA"]) == 0


# --- HTTP endpoints against the real data/ files ----------------------------

PEAK = {"scenario": "2025-08-21", "time": "2025-08-21T19:15:00Z"}


def test_busyness_endpoint_ranks_lga_busiest_at_peak(client):
    resp = client.get("/busyness", params=PEAK)
    assert resp.status_code == 200
    body = resp.json()
    assert body["window_minutes"] == 60
    airport_rows = body["airports"]
    # Sorted busiest-first, core airports present, LGA on top at this peak.
    scores = [a["score"] for a in airport_rows]
    assert scores == sorted(scores, reverse=True)
    assert airport_rows[0]["airport"] == "KLGA"
    icaos = {a["airport"] for a in airport_rows}
    assert {"KJFK", "KLGA", "KEWR"} <= icaos


def test_sister_airports_are_all_less_busy_least_busy_first(client):
    resp = client.get("/sister-airports", params={"airport": "klga", **PEAK})
    assert resp.status_code == 200
    body = resp.json()
    assert body["primary"]["airport"] == "KLGA"
    primary_score = body["primary"]["score"]
    sisters = body["sisters"]
    assert sisters, "expected sisters at a busy peak"
    for s in sisters:
        assert s["score"] < primary_score
        assert s["less_busy_by"] == primary_score - s["score"]
    # Least busy first.
    assert [s["score"] for s in sisters] == sorted(s["score"] for s in sisters)
    # The real LGA relievers (Teterboro / White Plains) should surface.
    assert {"KTEB", "KHPN"} <= {s["airport"] for s in sisters}


def test_sister_airports_radius_filter(client):
    resp = client.get("/sister-airports", params={"airport": "KLGA", "radius_nm": 15, **PEAK})
    assert resp.status_code == 200
    sisters = resp.json()["sisters"]
    assert sisters
    for s in sisters:
        assert s["distance_nm"] is not None and s["distance_nm"] <= 15


def test_busyness_bad_time_is_400(client):
    assert client.get("/busyness", params={"time": "not-a-time"}).status_code == 400


def test_sister_airports_unknown_airport_is_404(client):
    resp = client.get("/sister-airports", params={"airport": "KZZZ", "scenario": "2025-08-21"})
    assert resp.status_code == 404
