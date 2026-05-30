"""Unit tests for the pure capacity logic (no DB, no HTTP)."""

from __future__ import annotations

from datetime import datetime, timedelta

import capacity


def _series(counts, start="2025-01-01T12:00:00+00:00"):
    """Build dense 5-minute demand buckets from a list of counts."""
    t0 = datetime.fromisoformat(start)
    return [
        {"bucket_start": (t0 + timedelta(minutes=5 * i)).isoformat(), "flight_count": c}
        for i, c in enumerate(counts)
    ]


def test_capacity_rows_are_the_three_core_airports():
    aar = {r["airport"]: r["aar"] for r in capacity.capacity_rows()}
    assert aar == {"KJFK": 52, "KLGA": 40, "KEWR": 52}
    assert all(r["source"] for r in capacity.capacity_rows())  # provenance present


def test_empty_demand_yields_empty_series():
    assert capacity.rolling_hour_overload([], 40) == []


def test_below_capacity_is_never_overloaded():
    series = capacity.rolling_hour_overload(_series([3, 4]), 40)
    assert [s["rolling_arrivals"] for s in series] == [3, 7]
    assert all(not s["overloaded"] for s in series)
    assert series[-1]["overload"] == 7 - 40  # negative = spare capacity


def test_demand_exactly_at_capacity_is_not_overloaded():
    # Twelve 5-min buckets summing to exactly 40 over the rolling hour.
    series = capacity.rolling_hour_overload(_series([4] * 10 + [0, 0]), 40)
    assert max(s["rolling_arrivals"] for s in series) == 40
    assert all(not s["overloaded"] for s in series)  # strict > AAR


def test_sustained_demand_above_capacity_flags_windows():
    # 4 arrivals every 5 min -> 48/hr at the top of the rolling hour > AAR 40.
    series = capacity.rolling_hour_overload(_series([4] * 12), 40)
    assert series[-1]["rolling_arrivals"] == 48
    assert series[-1]["overloaded"] is True
    assert series[-1]["overload"] == 8
    # Overloaded only once rolling clears 40: at 44 (bucket 11) and 48 (bucket 12).
    assert sum(s["overloaded"] for s in series) == 2


def test_rolling_window_drops_buckets_older_than_an_hour():
    # 13 consecutive buckets: the last hour holds only the trailing 12 (=48).
    series = capacity.rolling_hour_overload(_series([4] * 13), 40)
    assert series[-1]["rolling_arrivals"] == 48


def test_gaps_are_zero_filled():
    # Two bursts 30 min apart; both fall inside one rolling hour.
    buckets = [
        {"bucket_start": "2025-01-01T12:00:00+00:00", "flight_count": 10},
        {"bucket_start": "2025-01-01T12:30:00+00:00", "flight_count": 10},
    ]
    series = capacity.rolling_hour_overload(buckets, 40)
    assert len(series) == 7  # 12:00..12:30 densified to 5-min steps
    assert series[-1]["rolling_arrivals"] == 20
    assert all(not s["overloaded"] for s in series)
