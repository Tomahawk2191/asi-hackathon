"""Static weather (.npz) loaders + live HRRR fetcher from AWS Open Data.

The static bundle ships REFC / RETOP as 256x358 float matrices on an
equirectangular grid (LAT_MIN..LAT_MAX, LON_MIN..LON_MAX).

For live data, NOAA publishes HRRR grib2 files to s3://noaa-hrrr-bdp-pds.
Each cycle's .grib2 file is accompanied by a .grib2.idx text file that lists
byte offsets for each message — we use it to range-pull just REFC + RETOP,
keeping the download under ~10 MB instead of ~130 MB per cycle.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import httpx
import numpy as np

from ..config import (
    CACHE_DIR,
    COLS,
    LAT_MAX,
    LAT_MIN,
    LON_MAX,
    LON_MIN,
    REFC_NODATA,
    RETOP_NODATA,
    ROWS,
)
from .snapshots import get_snapshot

# -----------------------------------------------------------------------------
# Static bundle (.npz)
# -----------------------------------------------------------------------------

# Filename example:
#   2025-05-29_21:00:00_2025-05-29_20:52:30_2025-05-29_21:07:30.npz
# format: based_at _ valid_from _ valid_to
_WX_RE = re.compile(
    r"^(?P<based>\d{4}-\d{2}-\d{2}_\d{2}:\d{2}:\d{2})_"
    r"(?P<vf>\d{4}-\d{2}-\d{2}_\d{2}:\d{2}:\d{2})_"
    r"(?P<vt>\d{4}-\d{2}-\d{2}_\d{2}:\d{2}:\d{2})\.npz$"
)


def _parse_ts(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d_%H:%M:%S").replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class WxStrip:
    field: str  # "refc" or "retop"
    based_at: datetime
    valid_from: datetime
    valid_to: datetime
    path: Path


@lru_cache(maxsize=32)
def list_strips(snapshot_name: str, field: str) -> list[WxStrip]:
    snap = get_snapshot(snapshot_name)
    d = snap.path / "wx" / field
    out: list[WxStrip] = []
    for p in sorted(d.glob("*.npz")):
        m = _WX_RE.match(p.name)
        if not m:
            continue
        out.append(WxStrip(
            field=field,
            based_at=_parse_ts(m.group("based")),
            valid_from=_parse_ts(m.group("vf")),
            valid_to=_parse_ts(m.group("vt")),
            path=p,
        ))
    return out


def pick_strip(snapshot_name: str, field: str, at: datetime) -> WxStrip | None:
    """Pick the strip whose [valid_from, valid_to) window covers `at`."""
    strips = list_strips(snapshot_name, field)
    for s in strips:
        if s.valid_from <= at < s.valid_to:
            return s
    # Fall back to nearest in time.
    if not strips:
        return None
    return min(strips, key=lambda s: abs((s.valid_from - at).total_seconds()))


@lru_cache(maxsize=64)
def load_strip_matrix(path: str) -> np.ndarray:
    with np.load(path) as data:
        return data["matrix"].astype(np.float32)


def mask_nodata(field: str, m: np.ndarray) -> np.ndarray:
    if field == "refc":
        return np.where(m <= REFC_NODATA, np.nan, m)
    return np.where(m < RETOP_NODATA, np.nan, m)


# -----------------------------------------------------------------------------
# Live HRRR from AWS Open Data
# -----------------------------------------------------------------------------

HRRR_BUCKET_URL = "https://noaa-hrrr-bdp-pds.s3.amazonaws.com"
# HRRR releases hourly. The `wrfsfc` (surface) file contains REFC + RETOP.
# Pattern: hrrr.YYYYMMDD/conus/hrrr.tHHz.wrfsfcfFF.grib2[.idx]


def latest_hrrr_cycle(now: datetime | None = None) -> datetime:
    """Pick a recent cycle that is likely already published.

    HRRR data lands in S3 ~50-60 min after the cycle hour. We back off 90 min
    to be safe.
    """
    now = now or datetime.now(timezone.utc)
    candidate = (now - timedelta(minutes=90)).replace(minute=0, second=0, microsecond=0)
    return candidate


def hrrr_paths(cycle: datetime, fh: int) -> tuple[str, str]:
    day = cycle.strftime("%Y%m%d")
    hh = cycle.strftime("%H")
    base = f"{HRRR_BUCKET_URL}/hrrr.{day}/conus/hrrr.t{hh}z.wrfsfcf{fh:02d}.grib2"
    return base, base + ".idx"


@dataclass(frozen=True)
class IdxEntry:
    start: int
    end: int | None  # None = end of file
    short_name: str
    level: str
    fh_label: str


def _parse_idx(idx_text: str) -> list[IdxEntry]:
    """Parse a grib2 .idx file. Each line:
        <msgnum>:<byte_start>:<date>:<short_name>:<level>:<fcst_hour>:
    """
    lines = [ln for ln in idx_text.splitlines() if ln.strip()]
    parsed: list[tuple[int, int, str, str, str]] = []
    for ln in lines:
        parts = ln.split(":")
        if len(parts) < 6:
            continue
        try:
            start = int(parts[1])
        except ValueError:
            continue
        parsed.append((start, len(parsed), parts[3], parts[4], parts[5]))
    parsed.sort()
    entries: list[IdxEntry] = []
    for i, (start, _, name, level, fh_label) in enumerate(parsed):
        end = parsed[i + 1][0] - 1 if i + 1 < len(parsed) else None
        entries.append(IdxEntry(start=start, end=end, short_name=name, level=level, fh_label=fh_label))
    return entries


def _matching(entries: list[IdxEntry], wanted_short_name: str) -> IdxEntry | None:
    for e in entries:
        if e.short_name == wanted_short_name:
            return e
    return None


def _byte_range_get(client: httpx.Client, url: str, start: int, end: int | None) -> bytes:
    headers = {"Range": f"bytes={start}-{end if end is not None else ''}"}
    r = client.get(url, headers=headers, timeout=60.0)
    r.raise_for_status()
    return r.content


@dataclass(frozen=True)
class LiveHrrrFrame:
    field: str            # "refc" or "retop"
    based_at: datetime    # HRRR cycle
    valid_from: datetime
    valid_to: datetime
    matrix: np.ndarray    # regridded to (ROWS, COLS) on the bundle grid


def _cycle_with_fallback(client: httpx.Client, fh: int) -> tuple[datetime, list[IdxEntry], str]:
    """Find the most recent published cycle that has both the grib and idx."""
    cycle = latest_hrrr_cycle()
    for _ in range(6):  # walk back up to 6 hours
        grib_url, idx_url = hrrr_paths(cycle, fh)
        try:
            r = client.get(idx_url, timeout=15.0)
            if r.status_code == 200:
                entries = _parse_idx(r.text)
                if entries:
                    return cycle, entries, grib_url
        except httpx.HTTPError:
            pass
        cycle -= timedelta(hours=1)
    raise RuntimeError("Could not locate a recent HRRR cycle with idx")


def fetch_live(field: str, fh: int = 0) -> LiveHrrrFrame:
    """Pull REFC or RETOP for a given forecast hour from the latest HRRR cycle."""
    short_name = {"refc": "REFC", "retop": "RETOP"}[field]
    cache_key = f"hrrr_live_{field}_fh{fh:02d}.npz"
    cache_path = CACHE_DIR / cache_key
    # Cheap cache: re-use if <30 min old.
    if cache_path.exists():
        age = datetime.now().timestamp() - cache_path.stat().st_mtime
        if age < 30 * 60:
            with np.load(cache_path, allow_pickle=True) as d:
                return LiveHrrrFrame(
                    field=field,
                    based_at=datetime.fromisoformat(str(d["based_at"])),
                    valid_from=datetime.fromisoformat(str(d["valid_from"])),
                    valid_to=datetime.fromisoformat(str(d["valid_to"])),
                    matrix=d["matrix"].astype(np.float32),
                )

    with httpx.Client(follow_redirects=True) as client:
        cycle, entries, grib_url = _cycle_with_fallback(client, fh)
        entry = _matching(entries, short_name)
        if entry is None:
            raise RuntimeError(f"{short_name} not found in HRRR cycle {cycle.isoformat()}")
        blob = _byte_range_get(client, grib_url, entry.start, entry.end)

    matrix = _decode_and_regrid(blob, field)
    valid_from = cycle + timedelta(hours=fh)
    valid_to = valid_from + timedelta(minutes=15)
    np.savez(cache_path,
             matrix=matrix,
             based_at=cycle.isoformat(),
             valid_from=valid_from.isoformat(),
             valid_to=valid_to.isoformat())
    return LiveHrrrFrame(field=field, based_at=cycle, valid_from=valid_from, valid_to=valid_to, matrix=matrix)


def _decode_and_regrid(grib_bytes: bytes, field: str) -> np.ndarray:
    """Decode a 1-message grib2 blob and regrid to the bundle's 256x358 grid."""
    import tempfile
    import xarray as xr

    with tempfile.NamedTemporaryFile(suffix=".grib2", delete=False) as tf:
        tf.write(grib_bytes)
        tmp = tf.name
    try:
        ds = xr.open_dataset(tmp, engine="cfgrib", backend_kwargs={"indexpath": ""})
        var_name = list(ds.data_vars)[0]
        da = ds[var_name]
        # HRRR native is Lambert conformal. Coordinates `latitude` / `longitude`
        # are 2D arrays. We bilinearly resample onto our target equirectangular grid.
        lat2d = ds["latitude"].values  # (ny, nx)
        lon2d = ds["longitude"].values
        lon2d = np.where(lon2d > 180, lon2d - 360, lon2d)
        vals = da.values
        return _regrid_to_target(lat2d, lon2d, vals, field)
    finally:
        Path(tmp).unlink(missing_ok=True)


def _regrid_to_target(lat2d: np.ndarray, lon2d: np.ndarray, vals: np.ndarray, field: str) -> np.ndarray:
    """Nearest-neighbor resample from HRRR native grid → (ROWS, COLS) target.

    Target row 0 = north, col 0 = west.
    """
    from scipy.spatial import cKDTree

    out = np.full((ROWS, COLS), np.nan, dtype=np.float32)
    # Target pixel centers.
    target_lats = LAT_MAX - (np.arange(ROWS) + 0.5) / ROWS * (LAT_MAX - LAT_MIN)
    target_lons = LON_MIN + (np.arange(COLS) + 0.5) / COLS * (LON_MAX - LON_MIN)
    tlat, tlon = np.meshgrid(target_lats, target_lons, indexing="ij")

    # Build KD-tree over source points (project to a quick local plane is fine
    # since HRRR coverage is bounded and we just need nearest neighbor).
    src_pts = np.column_stack([lat2d.ravel(), lon2d.ravel()])
    tree = cKDTree(src_pts)
    qry = np.column_stack([tlat.ravel(), tlon.ravel()])
    dist, idx = tree.query(qry, k=1)
    sampled = vals.ravel()[idx].reshape(ROWS, COLS).astype(np.float32)

    # Mask: anything farther than ~0.3° from a source point is "outside coverage".
    mask = dist.reshape(ROWS, COLS) > 0.3
    if field == "refc":
        sampled[mask] = REFC_NODATA - 1.0
    else:
        sampled[mask] = -1.0
    out[:] = sampled
    return out
