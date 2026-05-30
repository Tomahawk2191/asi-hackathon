"""Airport load-balancing optimizer (peak-shave on the busyness score).

Strategic predictive rerouting at the *airport* altitude: given a routes
snapshot and a moment in time, reassign core-airport arrivals across the three
slot-controlled NYC airports (KJFK / KLGA / KEWR — all within ~25 nm of each
other) to flatten the busyness score, i.e. minimize the worst airport's score.

This is the airport half of the plan. Sector effects are left for a later pass;
here we balance the score the team computes in ``busyness.py``.

Greedy minimax: while the busiest core airport's score exceeds the least-busy
one's by more than a single reassignment would close, move one in-window arrival
from busiest to least-busy. Each move shifts ~``100 / (2*AAR)`` score points, so
the loop converges to a balanced trio. Relievers are left untouched (no FAA
arrival capacity; can't absorb airline arrivals).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import capacity
from busyness import REFERENCE_AAR, count_in_window, score_airport
from flights import RoutesSnapshot
from nyc import metro_airports

# The slot-controlled core airports we rebalance among.
CORE = ["KJFK", "KLGA", "KEWR"]


def _score(inbound: int, outbound: int, aar: int | None) -> float:
    movements = inbound + outbound
    practical = 2 * (aar if aar is not None else REFERENCE_AAR)
    return 100 * movements / practical if practical else 0.0


def _rows(inbound: dict[str, int], outbound: dict[str, int], metro: set[str]) -> list[dict]:
    rows = [
        {"airport": a, **score_airport(inbound[a], outbound[a], capacity.VMC_AAR.get(a))}
        for a in metro
    ]
    rows.sort(key=lambda r: (-r["score"], r["airport"]))
    return rows


def rebalance(
    snapshot: RoutesSnapshot,
    center: datetime,
    window_minutes: int = 60,
    candidates: list[str] = CORE,
) -> dict:
    """Balance the busyness score across ``candidates`` at ``center``.

    Returns baseline + optimized busyness rows (all metro airports), the list of
    arrival reassignments, and the peak score before/after.
    """
    metro = metro_airports(snapshot)
    counts = count_in_window(snapshot, center, window_minutes)
    inbound = {a: counts.get(a, (0, 0))[0] for a in metro}
    outbound = {a: counts.get(a, (0, 0))[1] for a in metro}
    before = _rows(inbound, outbound, metro)

    cands = [a for a in candidates if a in metro]

    # In-window arrivals currently assigned to each candidate airport (the pool
    # we can move). We only need a count per airport to rebalance, but we track
    # flight numbers so the response can show concrete reassignments.
    half = timedelta(minutes=window_minutes / 2)
    lo, hi = center - half, center + half
    pool: dict[str, list[str]] = {a: [] for a in cands}
    for f in snapshot.flights:
        dest = f.destination_airport_icao
        if dest in pool and lo <= f.scheduled_landing_time < hi:
            pool[dest].append(f.flight_number)

    def score_of(a: str) -> float:
        return _score(inbound[a], outbound[a], capacity.VMC_AAR.get(a))

    def delta(a: str) -> float:  # score points one arrival adds/removes at a
        return 100 / (2 * (capacity.VMC_AAR.get(a) or REFERENCE_AAR))

    moves: list[dict] = []
    # Bound the loop generously; it converges well before this.
    for _ in range(sum(len(v) for v in pool.values()) + 1):
        busiest = max(cands, key=score_of)
        quietest = min(cands, key=score_of)
        if not pool[busiest]:
            break
        # Stop once a single move would no longer narrow the gap (it would just
        # swap which airport is the peak).
        if score_of(busiest) - score_of(quietest) <= delta(busiest) + delta(quietest):
            break
        flight = pool[busiest].pop()
        inbound[busiest] -= 1
        inbound[quietest] += 1
        pool[quietest].append(flight)
        moves.append({"flight": flight, "from": busiest, "to": quietest})

    after = _rows(inbound, outbound, metro)
    core_before = [r for r in before if r["airport"] in cands]
    core_after = [r for r in after if r["airport"] in cands]
    return {
        "candidates": cands,
        "window_minutes": window_minutes,
        "before": before,
        "after": after,
        "moves": moves,
        "moved": len(moves),
        "max_before": max((r["score"] for r in core_before), default=0),
        "max_after": max((r["score"] for r in core_after), default=0),
    }
