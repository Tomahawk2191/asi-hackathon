"""Airport geometry derived from a routes snapshot.

The dataset ships no airport-coordinate table, but it doesn't need one: every
flight's route *ends* at its destination airport and *begins* at its origin, and
in these snapshots every flight sharing an endpoint airport reports the
**identical** endpoint waypoint (0 nm spread). So a snapshot is itself an exact
airport gazetteer -- take the first waypoint of any departure / the last
waypoint of any arrival.

Coordinates are ``[longitude, latitude]`` in decimal degrees, WGS84 (GeoJSON
order), matching the rest of the backend.
"""

from __future__ import annotations

import math

from flights import RoutesSnapshot

# Mean Earth radius in nautical miles (6371.0088 km / 1.852 km per nm).
EARTH_RADIUS_NM = 6371.0088 / 1.852


def airport_coords(snapshot: RoutesSnapshot) -> dict[str, tuple[float, float]]:
    """Map each airport ICAO to its ``(lon, lat)``, read from route endpoints.

    A flight's first waypoint is its origin airport and its last waypoint is its
    destination airport. Every flight touching a given airport reports the same
    endpoint point, so the first one seen wins (later identical points are
    ignored). Airports that never appear as a route endpoint are absent.
    """
    coords: dict[str, tuple[float, float]] = {}
    for flight in snapshot.flights:
        if not flight.lats or not flight.lons:
            continue
        coords.setdefault(flight.origin_airport_icao, (flight.lons[0], flight.lats[0]))
        coords.setdefault(
            flight.destination_airport_icao, (flight.lons[-1], flight.lats[-1])
        )
    return coords


def great_circle_nm(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in nautical miles between two ``(lon, lat)`` points.

    Haversine formula; inputs are GeoJSON order ``(lon, lat)`` in decimal degrees.
    """
    lon1, lat1 = a
    lon2, lat2 = b
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    h = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_NM * math.asin(math.sqrt(h))
