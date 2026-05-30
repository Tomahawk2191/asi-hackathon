from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import orjson
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .airports import AIRPORTS, coords
from .config import LAT_MAX, LAT_MIN, LON_MAX, LON_MIN
from .data.sectors import load_sectors, sectors_as_geojson
from .data.opensky import fetch_live as fetch_live_traffic
from .data.snapshots import get_snapshot, list_snapshots
from .data.weather import (
    fetch_live,
    list_strips,
    load_strip_matrix,
    mask_nodata,
    pick_strip,
)
from .render.wx_png import matrix_to_png
from .routing.router import RouteRequest, plan
from .sim.simulator import (
    load_flights,
    positions_at,
    sector_loads_at,
)

app = FastAPI(title="ASI Hackathon — Routing API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _orjson_response(data) -> Response:
    return Response(
        content=orjson.dumps(data, option=orjson.OPT_SERIALIZE_NUMPY),
        media_type="application/json",
    )


@app.get("/api/snapshots")
def get_snapshots():
    snaps = list_snapshots()
    return _orjson_response([
        {"name": s.name, "asked_at": s.asked_at.isoformat()}
        for s in snaps
    ])


@app.get("/api/airports")
def get_airports():
    return [{"icao": k, "lat": v[0], "lon": v[1]} for k, v in AIRPORTS.items()]


@app.get("/api/sectors")
def get_sectors(band: Optional[str] = Query(None), snapshot: Optional[str] = None, at: Optional[str] = None):
    """Sectors as GeoJSON, optionally annotated with current load."""
    gj = sectors_as_geojson(band=band)
    if snapshot and at:
        t = datetime.fromisoformat(at)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        loads = sector_loads_at(snapshot, t)
        for f in gj["features"]:
            name = f["properties"]["name"]
            count = loads.get(name, 0)
            f["properties"]["load"] = count
            cap = f["properties"]["capacity"]
            f["properties"]["overloaded"] = count > cap
            f["properties"]["load_pct"] = (count / cap) if cap > 0 else 0.0
    return _orjson_response(gj)


@app.get("/api/flights/live")
def get_flights_live(limit: int = 6000):
    try:
        payload = fetch_live_traffic()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"opensky unavailable: {e}")
    flights = payload.flights[:limit]
    headers = {
        "X-Fetched-At": str(payload.fetched_at),
        "X-Stale": "1" if payload.stale else "0",
        "X-Source": "opensky",
        "Access-Control-Expose-Headers": "X-Fetched-At,X-Stale,X-Source,X-Error",
    }
    if payload.error:
        headers["X-Error"] = payload.error
    return Response(
        content=orjson.dumps(flights, option=orjson.OPT_SERIALIZE_NUMPY),
        media_type="application/json",
        headers=headers,
    )


@app.get("/api/sectors/live")
def get_sectors_live(band: Optional[str] = Query(None)):
    """Sectors annotated with load computed from current OpenSky positions."""
    from shapely.geometry import Point
    try:
        payload = fetch_live_traffic()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"opensky unavailable: {e}")
    idx = load_sectors()
    counts: dict[str, int] = {s.name: 0 for s in idx.sectors}
    from .config import HIGH_FLOOR_FT
    for f in payload.flights:
        alt = f["altitude_ft"]
        if alt >= HIGH_FLOOR_FT:
            tree, sectors = idx.tree_high, idx.sectors_high
        else:
            tree, sectors = idx.tree_low, idx.sectors_low
        pt = Point(f["lon"], f["lat"])
        for i in tree.query(pt):
            s = sectors[i]
            if s.geom.contains(pt):
                counts[s.name] += 1
                break
    gj = sectors_as_geojson(band=band)
    for feat in gj["features"]:
        name = feat["properties"]["name"]
        count = counts.get(name, 0)
        cap = feat["properties"]["capacity"]
        feat["properties"]["load"] = count
        feat["properties"]["overloaded"] = count > cap
        feat["properties"]["load_pct"] = (count / cap) if cap > 0 else 0.0
    return _orjson_response(gj)


@app.get("/api/flights")
def get_flights(snapshot: str, at: str, limit: int = 5000):
    t = datetime.fromisoformat(at)
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    positions = positions_at(snapshot, t)[:limit]
    return _orjson_response([
        {
            "flight_number": p.flight_number,
            "origin": p.origin,
            "destination": p.destination,
            "lat": p.lat,
            "lon": p.lon,
            "altitude_ft": p.altitude_ft,
            "heading_deg": p.heading_deg,
            "progress": p.progress,
            "status": p.status,
        }
        for p in positions
    ])


@app.get("/api/weather")
def get_weather(
    field: str = Query(..., pattern="^(refc|retop)$"),
    snapshot: Optional[str] = None,
    at: Optional[str] = None,
    source: str = Query("static", pattern="^(static|live)$"),
    fh: int = Query(0, ge=0, le=18),
):
    """Returns a PNG with bbox metadata in headers."""
    if source == "live":
        frame = fetch_live(field=field, fh=fh)
        m = frame.matrix
        m = mask_nodata(field, m)
        meta = {
            "based_at": frame.based_at.isoformat(),
            "valid_from": frame.valid_from.isoformat(),
            "valid_to": frame.valid_to.isoformat(),
            "source": "live",
        }
    else:
        if not snapshot or not at:
            raise HTTPException(400, "static weather requires snapshot + at")
        t = datetime.fromisoformat(at)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        strip = pick_strip(snapshot, field, t)
        if strip is None:
            raise HTTPException(404, "no weather strip for that time")
        m = mask_nodata(field, load_strip_matrix(str(strip.path)))
        meta = {
            "based_at": strip.based_at.isoformat(),
            "valid_from": strip.valid_from.isoformat(),
            "valid_to": strip.valid_to.isoformat(),
            "source": "static",
        }
    png = matrix_to_png(m, field)
    headers = {
        "X-Lat-Min": str(LAT_MIN), "X-Lat-Max": str(LAT_MAX),
        "X-Lon-Min": str(LON_MIN), "X-Lon-Max": str(LON_MAX),
        "X-Field": field,
        "X-Source": meta["source"],
        "X-Based-At": meta["based_at"],
        "X-Valid-From": meta["valid_from"],
        "X-Valid-To": meta["valid_to"],
        "Access-Control-Expose-Headers": "X-Lat-Min,X-Lat-Max,X-Lon-Min,X-Lon-Max,X-Field,X-Source,X-Based-At,X-Valid-From,X-Valid-To",
        "Cache-Control": "public, max-age=300",
    }
    return Response(content=png, media_type="image/png", headers=headers)


class RouteRequestModel(BaseModel):
    origin: str = Field(..., description="ICAO code, e.g. KJFK")
    destination: str = Field(..., description="ICAO code, e.g. KLAX")
    cruise_altitude_ft: int = 36000
    cruise_speed_kt: float = 460
    depart_at: str = Field(..., description="ISO timestamp UTC")
    snapshot: str
    avoid_weather: bool = True
    avoid_overloaded_sectors: bool = True


@app.post("/api/route")
def post_route(req: RouteRequestModel):
    try:
        o_lat, o_lon = coords(req.origin)
        d_lat, d_lon = coords(req.destination)
    except KeyError as e:
        raise HTTPException(400, str(e))
    t = datetime.fromisoformat(req.depart_at)
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    result = plan(RouteRequest(
        origin_lat=o_lat, origin_lon=o_lon,
        dest_lat=d_lat, dest_lon=d_lon,
        cruise_altitude_ft=req.cruise_altitude_ft,
        cruise_speed_kt=req.cruise_speed_kt,
        depart_at=t,
        snapshot=req.snapshot,
        avoid_weather=req.avoid_weather,
        avoid_overloaded_sectors=req.avoid_overloaded_sectors,
    ))
    return _orjson_response({
        "origin": req.origin,
        "destination": req.destination,
        "lats": result.lats,
        "lons": result.lons,
        "total_nm": result.total_nm,
        "eta_hours": result.eta_hours,
        "base_distance_nm": result.base_distance_nm,
        "extra_nm": result.total_nm - result.base_distance_nm,
        "sectors_traversed": result.sectors_traversed,
        "overloaded_sectors_hit": result.overloaded_sectors_hit,
    })


@app.get("/")
def root():
    return {"ok": True, "service": "asi-routing", "snapshots": len(list_snapshots())}
