"""OpenSky Network live traffic (OAuth2 client_credentials flow).

OpenSky migrated off HTTP basic auth to OAuth2 in 2025. Get a free API client at
  https://opensky-network.org/my-opensky/api-tokens
which yields a `clientId` + `clientSecret`. Provide either as:
  - env vars: OPENSKY_CLIENT_ID, OPENSKY_CLIENT_SECRET, or
  - env var:  OPENSKY_CREDENTIALS_FILE → path to a JSON file with those keys.

Without credentials the anonymous tier returns 429 almost immediately for a
CONUS-wide query, so this module degrades gracefully: cached payloads (TTL 30 s
on success, 90 s back-off on 429) are served with a `stale` flag.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

OPENSKY_URL = "https://opensky-network.org/api/states/all"
TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network/"
    "protocol/openid-connect/token"
)
CONUS = {"lamin": 24.0, "lomin": -125.0, "lamax": 50.0, "lomax": -66.0}
NORMAL_TTL = 30.0
BACKOFF_TTL = 90.0
TOKEN_REFRESH_MARGIN = 30.0  # refresh this many seconds before expiry

_lock = threading.Lock()
_cache: dict = {"data": None, "fetched_at": 0.0, "error": None, "backoff_until": 0.0}
_token_lock = threading.Lock()
_token_cache: dict = {"access_token": None, "expires_at": 0.0}


@dataclass
class LivePayload:
    flights: list[dict]
    fetched_at: float
    stale: bool
    error: str | None
    auth: str  # "oauth2" or "anonymous"


def _credentials() -> tuple[str, str] | None:
    cid = os.environ.get("OPENSKY_CLIENT_ID")
    csec = os.environ.get("OPENSKY_CLIENT_SECRET")
    if cid and csec:
        return (cid, csec)
    cred_file = os.environ.get("OPENSKY_CREDENTIALS_FILE")
    if cred_file and Path(cred_file).is_file():
        try:
            data = json.loads(Path(cred_file).read_text())
            if data.get("clientId") and data.get("clientSecret"):
                return (data["clientId"], data["clientSecret"])
        except Exception:
            pass
    return None


def _get_access_token() -> str | None:
    creds = _credentials()
    if not creds:
        return None
    now = time.time()
    with _token_lock:
        tok = _token_cache["access_token"]
        if tok and now < _token_cache["expires_at"] - TOKEN_REFRESH_MARGIN:
            return tok
    cid, csec = creds
    with httpx.Client() as c:
        r = c.post(
            TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": cid,
                "client_secret": csec,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15.0,
        )
        r.raise_for_status()
        body = r.json()
    access = body["access_token"]
    ttl = float(body.get("expires_in", 1800))
    with _token_lock:
        _token_cache["access_token"] = access
        _token_cache["expires_at"] = now + ttl
    return access


def _normalize(states: list[list]) -> list[dict]:
    out: list[dict] = []
    for s in states:
        if len(s) < 17:
            continue
        lon, lat = s[5], s[6]
        if lon is None or lat is None:
            continue
        if bool(s[8]):  # on_ground
            continue
        baro_m = s[7]
        geo_m = s[13]
        alt_m = baro_m if baro_m is not None else geo_m
        alt_ft = int((alt_m or 0) * 3.28084)
        out.append({
            "flight_number": ((s[1] or s[0]) or "").strip(),
            "icao24": s[0],
            "origin_country": s[2] or "",
            "origin": "?",
            "destination": "?",
            "lat": float(lat),
            "lon": float(lon),
            "altitude_ft": alt_ft,
            "heading_deg": float(s[10] or 0.0),
            "velocity_kt": float((s[9] or 0.0) * 1.94384),
            "vertical_rate_fpm": float((s[11] or 0.0) * 196.85),
            "progress": 0.5,
            "status": "enroute",
        })
    return out


def fetch_live(bbox: dict = CONUS) -> LivePayload:
    now = time.time()
    with _lock:
        cached = _cache["data"]
        age = now - _cache["fetched_at"]
        ttl = NORMAL_TTL
        if now < _cache["backoff_until"]:
            if cached is not None:
                return LivePayload(
                    flights=cached, fetched_at=_cache["fetched_at"],
                    stale=True, error=_cache["error"], auth=_auth_label(),
                )
            ttl = BACKOFF_TTL
        if cached is not None and age < ttl:
            return LivePayload(
                flights=cached, fetched_at=_cache["fetched_at"],
                stale=False, error=_cache["error"], auth=_auth_label(),
            )

    headers: dict[str, str] = {}
    auth_label = _auth_label()
    try:
        if auth_label == "oauth2":
            tok = _get_access_token()
            if tok:
                headers["Authorization"] = f"Bearer {tok}"
        with httpx.Client(headers=headers) as client:
            r = client.get(OPENSKY_URL, params=bbox, timeout=20.0)
            if r.status_code == 401 and auth_label == "oauth2":
                # Token may have just expired — force a refresh and retry once.
                with _token_lock:
                    _token_cache["access_token"] = None
                    _token_cache["expires_at"] = 0.0
                tok = _get_access_token()
                if tok:
                    headers["Authorization"] = f"Bearer {tok}"
                    r = client.get(OPENSKY_URL, params=bbox, timeout=20.0, headers=headers)
            r.raise_for_status()
            payload = r.json()
        flights = _normalize(payload.get("states") or [])
        with _lock:
            _cache["data"] = flights
            _cache["fetched_at"] = now
            _cache["error"] = None
            _cache["backoff_until"] = 0.0
        return LivePayload(flights=flights, fetched_at=now, stale=False, error=None, auth=auth_label)
    except httpx.HTTPStatusError as e:
        msg = f"HTTP {e.response.status_code}"
        with _lock:
            _cache["error"] = msg
            if e.response.status_code == 429:
                _cache["backoff_until"] = now + BACKOFF_TTL
            cached = _cache["data"]
            cached_at = _cache["fetched_at"]
        if cached is not None:
            return LivePayload(flights=cached, fetched_at=cached_at, stale=True, error=msg, auth=auth_label)
        raise
    except Exception as e:  # noqa: BLE001
        msg = f"{type(e).__name__}: {e}"
        with _lock:
            _cache["error"] = msg
            cached = _cache["data"]
            cached_at = _cache["fetched_at"]
        if cached is not None:
            return LivePayload(flights=cached, fetched_at=cached_at, stale=True, error=msg, auth=auth_label)
        raise


def _auth_label() -> str:
    return "oauth2" if _credentials() else "anonymous"
