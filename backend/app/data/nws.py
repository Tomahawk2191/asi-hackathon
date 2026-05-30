"""NWS active alerts (live weather polygons).

API: https://api.weather.gov/alerts/active — no auth required.

Returns a GeoJSON FeatureCollection of currently-in-effect polygons:
tornado/severe-thunderstorm/flash-flood warnings, special marine, etc. Polygons
are far more actionable for ATC routing than a raw reflectivity raster.

We cache for 60 seconds. The NWS asks clients to identify themselves via a
User-Agent — we send one.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import httpx

NWS_URL = "https://api.weather.gov/alerts/active"
USER_AGENT = "ASI-Hackathon-RoutingLab/0.1 (contact: rohan.kathuria@live.com)"
TTL = 60.0

_lock = threading.Lock()
_cache: dict = {"data": None, "fetched_at": 0.0, "error": None}


@dataclass
class AlertsPayload:
    geojson: dict
    fetched_at: float
    stale: bool
    error: str | None
    count: int


# Severity → color hint (the frontend may also map this).
SEVERITY_RANK = {"Extreme": 4, "Severe": 3, "Moderate": 2, "Minor": 1, "Unknown": 0}


def _normalize(payload: dict) -> dict:
    feats = payload.get("features") or []
    out_feats = []
    for f in feats:
        geom = f.get("geometry")
        if not geom or geom.get("type") not in ("Polygon", "MultiPolygon"):
            continue
        props = f.get("properties") or {}
        evt = props.get("event") or "Alert"
        sev = props.get("severity") or "Unknown"
        urg = props.get("urgency") or "Unknown"
        cert = props.get("certainty") or "Unknown"
        out_feats.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "event": evt,
                "severity": sev,
                "urgency": urg,
                "certainty": cert,
                "headline": props.get("headline") or "",
                "areaDesc": props.get("areaDesc") or "",
                "effective": props.get("effective") or "",
                "expires": props.get("expires") or "",
                "sender": props.get("senderName") or "",
                "severity_rank": SEVERITY_RANK.get(sev, 0),
            },
        })
    return {"type": "FeatureCollection", "features": out_feats}


def fetch_alerts() -> AlertsPayload:
    now = time.time()
    with _lock:
        cached = _cache["data"]
        age = now - _cache["fetched_at"]
        if cached is not None and age < TTL:
            return AlertsPayload(
                geojson=cached, fetched_at=_cache["fetched_at"],
                stale=False, error=_cache["error"],
                count=len(cached.get("features") or []),
            )
    try:
        with httpx.Client(headers={"User-Agent": USER_AGENT, "Accept": "application/geo+json"}) as c:
            r = c.get(NWS_URL, timeout=15.0)
            r.raise_for_status()
            normalized = _normalize(r.json())
        with _lock:
            _cache["data"] = normalized
            _cache["fetched_at"] = now
            _cache["error"] = None
        return AlertsPayload(
            geojson=normalized, fetched_at=now,
            stale=False, error=None,
            count=len(normalized["features"]),
        )
    except Exception as e:  # noqa: BLE001
        msg = f"{type(e).__name__}: {e}"
        with _lock:
            _cache["error"] = msg
            cached = _cache["data"]
            cached_at = _cache["fetched_at"]
        if cached is not None:
            return AlertsPayload(
                geojson=cached, fetched_at=cached_at,
                stale=True, error=msg,
                count=len(cached.get("features") or []),
            )
        raise
