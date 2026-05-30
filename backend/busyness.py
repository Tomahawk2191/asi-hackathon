"""Airport "busyness" (popularity) scoring for NYC-metro airports.

A rough, POC-grade estimate of how busy an airport is at a given moment, built
straight from a routes snapshot -- no SQLite / ``/refresh`` step. Busyness blends
the three signals we care about: **inbound** (arrivals), **outbound**
(departures), and the **inbound capacity** reference (VMC AAR, from
``capacity.py``).

Score model (deliberately approximate -- a "general idea", not an exact rate).
For a window centered on time ``T``::

    movements          = inbound + outbound
    practical_capacity = 2 * (aar or REFERENCE_AAR)
    score              = round(100 * movements / practical_capacity)

A balanced airport running flat out does ~AAR arrivals *and* ~AAR departures, so
~``2*AAR`` movements/hour is its practical ceiling: score ~100 means "saturated",
and can exceed 100. Metro relievers have no FAA capacity profile, so they're
scaled on the busiest-core reference (``REFERENCE_AAR``) -- their low movement
counts then read as low busyness, exactly what a "less busy than X" comparison
wants.

Inbound / outbound are defined identically to the rest of the backend by reusing
``nyc.ARRIVAL`` / ``nyc.DEPARTURE`` (arrival = destination + scheduled landing
time; departure = origin + take-off time). Times are UTC ISO 8601.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import capacity
from flights import RoutesSnapshot
from nyc import ARRIVAL, DEPARTURE, metro_airports

# Relievers have no FAA capacity profile; scale them on the busiest core airport
# so every metro airport lands on one comparable 0-100 scale.
REFERENCE_AAR = max(capacity.VMC_AAR.values())

DEFAULT_WINDOW_MINUTES = 60


def count_in_window(
    snapshot: RoutesSnapshot,
    center: datetime,
    window_minutes: int = DEFAULT_WINDOW_MINUTES,
) -> dict[str, tuple[int, int]]:
    """Per NYC-metro airport, ``(inbound, outbound)`` flights around ``center``.

    The window is centered on ``center``: ``[center - w/2, center + w/2)``.
    Inbound counts arrivals (by destination + scheduled landing time); outbound
    counts departures (by origin + take-off time) -- the same field mapping the
    rest of the backend uses (``nyc.ARRIVAL`` / ``nyc.DEPARTURE``). A single
    intra-metro hop is correctly counted as a departure from its origin *and* an
    arrival at its destination. Every metro airport is present in the result,
    with ``(0, 0)`` when it has no flights in the window.
    """
    metro = metro_airports(snapshot)
    half = timedelta(minutes=window_minutes / 2)
    lo, hi = center - half, center + half

    inbound: dict[str, int] = {}
    outbound: dict[str, int] = {}
    for flight in snapshot.flights:
        for direction, counts in ((ARRIVAL, inbound), (DEPARTURE, outbound)):
            airport = getattr(flight, direction.airport_attr)
            if airport not in metro:
                continue
            when = getattr(flight, direction.time_attr)
            if lo <= when < hi:
                counts[airport] = counts.get(airport, 0) + 1

    return {
        airport: (inbound.get(airport, 0), outbound.get(airport, 0))
        for airport in metro
    }


def score_airport(inbound: int, outbound: int, aar: Optional[int]) -> dict:
    """Busyness score (and its raw parts) for one airport in one window.

    See the module docstring for the model. ``aar`` is the airport's VMC AAR, or
    None for relievers (which fall back to ``REFERENCE_AAR``). The returned
    ``capacity`` echoes the *real* AAR (None for relievers) so callers can tell
    which airports have a true FAA capacity profile.
    """
    movements = inbound + outbound
    practical_capacity = 2 * (aar if aar is not None else REFERENCE_AAR)
    return {
        "inbound": inbound,
        "outbound": outbound,
        "movements": movements,
        "capacity": aar,
        "has_capacity": aar is not None,
        "score": round(100 * movements / practical_capacity),
    }


def airport_busyness(
    snapshot: RoutesSnapshot,
    center: datetime,
    window_minutes: int = DEFAULT_WINDOW_MINUTES,
) -> list[dict]:
    """Busyness for every NYC-metro airport at ``center``, busiest first.

    Each row is ``score_airport(...)`` plus the ``airport`` ICAO, sorted by score
    descending then ICAO (stable order for ties).
    """
    counts = count_in_window(snapshot, center, window_minutes)
    rows = [
        {"airport": airport, **score_airport(inbound, outbound, capacity.VMC_AAR.get(airport))}
        for airport, (inbound, outbound) in counts.items()
    ]
    rows.sort(key=lambda r: (-r["score"], r["airport"]))
    return rows
