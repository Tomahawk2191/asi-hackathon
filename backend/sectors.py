"""Types and helpers for the airspace sectors dataset.

A sector is a piece of CONUS airspace: a polygon boundary, an altitude band,
and a capacity (max flights allowed inside at once). Sectors partition the
airspace into two bands -- LOW [0, 35000) ft and HIGH [35000, 60000) ft --
with no gaps or overlaps within a band.

Coordinates are [longitude, latitude] in decimal degrees, WGS84 (GeoJSON
order). Reference: hackathon_data_bundle/documentation/sectors/FILE_FORMAT.md
"""

from __future__ import annotations

import gzip
import json
from collections import Counter
from pathlib import Path
from typing import Iterable, Optional, Union

from pydantic import BaseModel, Field, PrivateAttr

from flights import RoutesSnapshot

PathLike = Union[str, Path]

# A linear ring is a list of [lon, lat] points; a polygon is a list of rings
# (exterior first, then any holes), matching GeoJSON Polygon coordinates.
Ring = list[list[float]]


def _point_in_ring(lon: float, lat: float, ring: Ring) -> bool:
    """Ray-casting point-in-polygon test for a single ring.

    Returns True if the point (lon, lat) is inside the ring. Pure Python so
    the backend needs no shapely/GEOS dependency.
    """
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        # Does the horizontal ray at `lat` cross the edge (i, j)?
        if (yi > lat) != (yj > lat):
            x_cross = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lon < x_cross:
                inside = not inside
        j = i
    return inside


class Sector(BaseModel):
    """A single ATC sector: a polygon footprint plus an altitude band."""

    name: str = Field(description="Unique id, e.g. HIGH_042 or LOW_017.")
    altitude_from_ft: int = Field(description="Floor of the altitude band, feet (inclusive).")
    altitude_to_ft: int = Field(description="Ceiling of the altitude band, feet (exclusive).")
    capacity: int = Field(description="Max flights that should be in the sector at once.")
    polygon: list[Ring] = Field(
        description="GeoJSON Polygon coordinates: exterior ring first, then any holes. "
        "Each point is [lon, lat]."
    )

    # Cached exterior-ring bounding box (min_lon, min_lat, max_lon, max_lat),
    # filled lazily on first containment test to skip the full ray cast.
    _bbox: Optional[tuple[float, float, float, float]] = PrivateAttr(default=None)

    @classmethod
    def from_feature(cls, feature: dict) -> "Sector":
        """Build a Sector from a GeoJSON Feature with a Polygon geometry."""
        props = feature["properties"]
        return cls(
            name=props["name"],
            altitude_from_ft=props["altitude_from_ft"],
            altitude_to_ft=props["altitude_to_ft"],
            capacity=props["capacity"],
            polygon=feature["geometry"]["coordinates"],
        )

    def contains(self, lon: float, lat: float) -> bool:
        """True if the point (lon, lat) falls within this sector's footprint.

        A point is inside if it lies in the exterior ring and not inside any
        hole. Altitude is not considered here -- only the 2D footprint.
        """
        if not self.polygon:
            return False
        min_lon, min_lat, max_lon, max_lat = self._bounds()
        if lon < min_lon or lon > max_lon or lat < min_lat or lat > max_lat:
            return False
        exterior, holes = self.polygon[0], self.polygon[1:]
        if not _point_in_ring(lon, lat, exterior):
            return False
        return not any(_point_in_ring(lon, lat, hole) for hole in holes)

    def _bounds(self) -> tuple[float, float, float, float]:
        """Bounding box of the exterior ring, cached after first use."""
        if self._bbox is None:
            exterior = self.polygon[0]
            lons = [pt[0] for pt in exterior]
            lats = [pt[1] for pt in exterior]
            self._bbox = (min(lons), min(lats), max(lons), max(lats))
        return self._bbox


def load_sectors(path: PathLike) -> list[Sector]:
    """Read a sectors GeoJSON file (plain ``.geojson`` or gzipped ``.gz``)."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Sectors file not found: {path}")
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt") as fh:
        data = json.load(fh)
    return [Sector.from_feature(f) for f in data["features"]]


def flights_landing_per_airport(
    sectors: Iterable[Sector],
    snapshot: RoutesSnapshot,
) -> dict[str, int]:
    """Count flights landing within a set of sectors, grouped by airport.

    A flight is "landing in" the sector set if its destination -- the last
    waypoint (``lons[-1]``, ``lats[-1]``), i.e. the arrival airport -- falls
    inside the footprint of any sector in ``sectors``. Flights are then
    tallied by ``destination_airport_icao``.

    Note on altitude: touchdown happens at ground level, so the LOW band
    ([0, 35000) ft) sectors are the meaningful ones for "landing". Pass the
    sectors you care about (e.g. only LOW sectors) -- this function tests the
    2D footprint of whatever is given and does not filter by band itself.

    Args:
        sectors: the sectors defining the region of interest.
        snapshot: a parsed routes snapshot (see ``load_routes``).

    Returns:
        Mapping of destination airport ICAO -> number of flights in the
        snapshot whose landing point lies within the sector set. Airports
        with no qualifying flights are omitted.
    """
    sectors = list(sectors)
    counts: Counter[str] = Counter()
    for flight in snapshot.flights:
        if not flight.lats or not flight.lons:
            continue
        lon, lat = flight.lons[-1], flight.lats[-1]
        if any(sector.contains(lon, lat) for sector in sectors):
            counts[flight.destination_airport_icao] += 1
    return dict(counts)
