"""Airport arrival capacity (VMC AAR) and demand-vs-capacity overload.

Holds one **VMC Airport Arrival Rate** (AAR, arrivals/hour) per slot-controlled
core NYC-metro airport, and compares it against arrivals-only demand to find the
hours where demand exceeds capacity.

Why a single VMC value (no weather tiers): the system models long-range /
seasonal schedule planning under *optimum* (visual) conditions, not live weather
adaptation -- so Marginal/IMC arrival rates are deliberately dropped. One AAR per
airport, no ``weather`` dimension.

Why arrivals-only: the demand series (``arrival_frequency`` in ``db.py`` /
``nyc.py``) counts arrivals only -- destination = metro airport, bucketed by
``scheduled_landing_time``. So capacity must be the AAR (arrivals/hour), NOT the
combined called rate; comparing arrivals-only demand to a combined rate (80-94/hr
for these airports) would be ~2x wrong.

AAR values are the FAA facility-reported ("called") arrival rate from the FAA
Airport Capacity Profiles, 2014 (built from ASPM FY2009-2010). For JFK and EWR
the *arrival-priority* configuration is used (the max-arrivals operating mode).
The arrival/departure split is the ``(Arrivals, Departures)`` data label on each
profile's capacity-curve scatter plot. These are distinct from the FAA *slot
caps* in CLAUDE.md, which are combined *scheduled-ops* administrative limits, not
arrivals-only physical capacity.

Source: https://www.faa.gov/airports/planning_capacity/profiles
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, Optional

# Curated VMC AAR (arrivals/hour). Only the slot-controlled core airports have an
# FAA capacity profile; the metro relievers (KTEB/KHPN/...) intentionally have no
# entry -- they read as "no data" rather than a guessed number.
VMC_AAR: dict[str, int] = {
    "KJFK": 52,  # arrival-priority 13L,22L / 13R; combined called 84 -> (52,32)
    "KLGA": 40,  # rwy 22 / rwy 13; combined called 80 -> balanced (40,40)
    "KEWR": 52,  # arrival-priority 11,22L / 22R; combined called 94 -> (52,42)
}

CAPACITY_SOURCE = (
    "FAA Airport Capacity Profiles 2014 (ASPM FY2009-2010), "
    "facility-reported VMC AAR"
)

# Demand is bucketed in 5-minute windows; AAR is hourly. The overload comparison
# rolls 12 consecutive 5-minute buckets into a rolling 60-minute count before
# comparing to the hourly AAR (the meaningful, sustainable rate -- 15-minute
# bursts x4 over-extrapolate; see CLAUDE.md).
BUCKET_MINUTES = 5
ROLLING_WINDOW_MINUTES = 60
BUCKETS_PER_HOUR = ROLLING_WINDOW_MINUTES // BUCKET_MINUTES  # 12


def capacity_rows() -> list[dict]:
    """The curated AAR table as rows ready for ``db.write_capacity``.

    Returns dicts ``{"airport", "aar", "source"}`` sorted by airport.
    """
    return [
        {"airport": airport, "aar": aar, "source": CAPACITY_SOURCE}
        for airport, aar in sorted(VMC_AAR.items())
    ]


def rolling_hour_overload(buckets: Iterable[dict], aar: int) -> list[dict]:
    """Rolling-60-minute arrival demand vs the hourly AAR, per 5-minute step.

    ``buckets`` is arrivals-only demand for a *single* airport: dicts carrying
    ``bucket_start`` (ISO-8601 UTC, start of a 5-minute window) and
    ``flight_count`` -- the shape ``db.read_day`` returns. Buckets with no
    arrivals may be absent; the timeline from the first to the last bucket is
    densified to 5-minute steps (missing = 0) before rolling.

    Returns one row per 5-minute step (sorted by time):

        {"bucket_start": ISO str, "rolling_arrivals": int, "aar": int,
         "overload": int, "overloaded": bool}

    ``rolling_arrivals`` sums this step plus the prior 11 (the trailing 60
    minutes). The first 55 minutes are partial windows (fewer than 12 buckets
    available), which under-count rather than over-count -- they cannot create a
    false overload. ``overload`` = ``rolling_arrivals - aar`` (negative = spare
    capacity); ``overloaded`` is strict (``rolling_arrivals > aar``), so demand
    exactly at the AAR is not flagged.
    """
    by_time: dict[datetime, int] = {
        datetime.fromisoformat(b["bucket_start"]): int(b["flight_count"])
        for b in buckets
    }
    if not by_time:
        return []

    step = timedelta(minutes=BUCKET_MINUTES)
    start, end = min(by_time), max(by_time)

    # Dense, zero-filled 5-minute timeline so gaps roll correctly.
    timeline: list[tuple[datetime, int]] = []
    t = start
    while t <= end:
        timeline.append((t, by_time.get(t, 0)))
        t += step

    rows: list[dict] = []
    for i, (when, _count) in enumerate(timeline):
        window = timeline[max(0, i - (BUCKETS_PER_HOUR - 1)) : i + 1]
        rolling = sum(count for _, count in window)
        rows.append(
            {
                "bucket_start": when.isoformat(),
                "rolling_arrivals": rolling,
                "aar": aar,
                "overload": rolling - aar,
                "overloaded": rolling > aar,
            }
        )
    return rows
