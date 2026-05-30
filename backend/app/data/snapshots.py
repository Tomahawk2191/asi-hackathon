from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from ..config import BUNDLE_DIR

SNAPSHOT_RE = re.compile(r"asked_at_(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)")


@dataclass(frozen=True)
class Snapshot:
    name: str           # "asked_at_2025-05-29T21:00:00Z"
    asked_at: datetime  # tz-aware UTC
    path: Path          # bundle subdirectory


def list_snapshots() -> list[Snapshot]:
    out: list[Snapshot] = []
    for p in sorted(BUNDLE_DIR.iterdir()):
        m = SNAPSHOT_RE.match(p.name)
        if not m:
            continue
        ts = datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        out.append(Snapshot(name=p.name, asked_at=ts, path=p))
    return out


def get_snapshot(name: str) -> Snapshot:
    for s in list_snapshots():
        if s.name == name:
            return s
    raise KeyError(f"unknown snapshot {name!r}")


@lru_cache(maxsize=4)
def load_routes(snapshot_name: str) -> dict:
    snap = get_snapshot(snapshot_name)
    with open(snap.path / "routes.json") as f:
        return json.load(f)
