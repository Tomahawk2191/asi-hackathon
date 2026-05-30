"""Types for the flights / routes dataset.

A snapshot of US flights and their planned paths at a single point in time.
Each flight lists the sequence of waypoints (parallel ``lats`` / ``lons``
arrays) it was planned to fly from origin to destination.

Times are UTC ISO 8601; coordinates are decimal degrees, WGS84.
Reference: hackathon_data_bundle/documentation/routes/FILE_FORMAT.md
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class Flight(BaseModel):
    """A single flight and its planned route."""

    flight_number: str = Field(
        description="Airline identifier (e.g. UAL2367). Not unique on its own; a flight is "
        "uniquely identified by (flight_number, take_off_time, origin_airport_icao)."
    )
    take_off_time: datetime = Field(description="When the flight departs the origin airport.")
    scheduled_landing_time: datetime = Field(
        description="When the flight is scheduled to touch down at the destination."
    )
    origin_airport_icao: str = Field(description="4-letter ICAO code of the departure airport.")
    destination_airport_icao: str = Field(
        description="4-letter ICAO code of the arrival airport."
    )
    cruise_altitude_ft: int = Field(description="Cruise altitude in feet above sea level.")
    cruise_speed_kt: int = Field(description="Cruise speed in knots (nautical miles per hour).")
    lats: list[float] = Field(
        description="Waypoint latitudes in flight order; first is origin, last is destination."
    )
    lons: list[float] = Field(
        description="Waypoint longitudes in flight order; parallel to lats."
    )
    is_airborne: bool = Field(
        description="True if the flight had already taken off by asked_at; else pre-departure."
    )


class NycFilter(BaseModel):
    """Airport groups used to select NYC-area flights (NYC dataset only)."""

    core: list[str] = Field(description="Core NYC airport ICAO codes (e.g. KEWR, KJFK, KLGA).")
    metro_extra: list[str] = Field(
        description="Additional NYC metro-area airport ICAO codes."
    )


class RoutesSnapshot(BaseModel):
    """Top-level routes / flights snapshot.

    Every flight has a scheduled gate departure inside
    ``[window_start, window_end)``.
    """

    asked_at: datetime = Field(description="The 'as-of' timestamp this snapshot reflects.")
    window_start: datetime = Field(description="Inclusive start of the flight-selection window.")
    window_end: datetime = Field(description="Exclusive end of the flight-selection window.")
    nyc_filter: Optional[NycFilter] = Field(
        default=None, description="Airport filter; present only in the NYC dataset."
    )
    flights: list[Flight] = Field(
        default_factory=list, description="One entry per flight in the snapshot."
    )

    @classmethod
    def from_raw(cls, payload: dict) -> "RoutesSnapshot":
        """Parse a routes/flights JSON payload into a typed snapshot."""
        return cls.model_validate(payload)
