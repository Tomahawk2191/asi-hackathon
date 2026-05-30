"""Types for the OpenSky Network REST API.

Covers the ``GET /states/all`` endpoint, which returns the most recent
state vectors for aircraft. The endpoint encodes each state vector as a
positional JSON array rather than an object, so we parse that array into a
named Pydantic model via :meth:`StateVector.from_array`.

Reference: https://openskynetwork.github.io/opensky-api/rest.html
"""

from __future__ import annotations

from enum import IntEnum
from typing import Optional

from pydantic import BaseModel, Field


class PositionSource(IntEnum):
    """Origin of a state vector's position (index 16)."""

    ADS_B = 0
    ASTERIX = 1
    MLAT = 2
    FLARM = 3


class AircraftCategory(IntEnum):
    """Aircraft category (index 17). Only present on some responses."""

    NO_INFORMATION = 0
    NO_ADS_B_EMITTER_CATEGORY = 1
    LIGHT = 2  # < 15500 lbs
    SMALL = 3  # 15500 to 75000 lbs
    LARGE = 4  # 75000 to 300000 lbs
    HIGH_VORTEX_LARGE = 5  # e.g. B-757
    HEAVY = 6  # > 300000 lbs
    HIGH_PERFORMANCE = 7  # > 5g acceleration and > 400 kts
    ROTORCRAFT = 8
    GLIDER_SAILPLANE = 9
    LIGHTER_THAN_AIR = 10
    PARACHUTIST_SKYDIVER = 11
    ULTRALIGHT_HANG_PARAGLIDER = 12
    RESERVED = 13
    UAV = 14
    SPACE_TRANS_ATMOSPHERIC = 15
    SURFACE_EMERGENCY_VEHICLE = 16
    SURFACE_SERVICE_VEHICLE = 17
    POINT_OBSTACLE = 18
    CLUSTER_OBSTACLE = 19
    LINE_OBSTACLE = 20


class StateVector(BaseModel):
    """A single aircraft state vector.

    Fields map to the positional array elements documented by OpenSky.
    Many fields are nullable because they depend on receiver coverage.
    """

    icao24: str = Field(description="Unique ICAO 24-bit address (hex), lowercase.")
    callsign: Optional[str] = Field(
        default=None, description="Callsign of the vehicle (8 chars). May be padded/None."
    )
    origin_country: str = Field(description="Country inferred from the ICAO 24-bit address.")
    time_position: Optional[int] = Field(
        default=None, description="Unix time (s) of last position update; None if no position."
    )
    last_contact: int = Field(description="Unix time (s) of last update from the transponder.")
    longitude: Optional[float] = Field(default=None, description="WGS-84 longitude in degrees.")
    latitude: Optional[float] = Field(default=None, description="WGS-84 latitude in degrees.")
    baro_altitude: Optional[float] = Field(
        default=None, description="Barometric altitude in meters."
    )
    on_ground: bool = Field(description="True if the position was reported from a ground surface.")
    velocity: Optional[float] = Field(default=None, description="Ground speed in m/s.")
    true_track: Optional[float] = Field(
        default=None, description="True track in decimal degrees clockwise from north (0=north)."
    )
    vertical_rate: Optional[float] = Field(
        default=None,
        description="Vertical rate in m/s; positive = climbing, negative = descending.",
    )
    sensors: Optional[list[int]] = Field(
        default=None, description="IDs of receivers that contributed to this vector."
    )
    geo_altitude: Optional[float] = Field(
        default=None, description="Geometric altitude in meters."
    )
    squawk: Optional[str] = Field(default=None, description="Transponder squawk code.")
    spi: bool = Field(description="Whether flight status indicates special purpose indicator.")
    position_source: PositionSource = Field(description="Origin of this state's position.")
    category: Optional[AircraftCategory] = Field(
        default=None, description="Aircraft category; only present on some responses."
    )

    @classmethod
    def from_array(cls, raw: list) -> "StateVector":
        """Build a StateVector from OpenSky's positional array.

        The array has 17 elements, with an optional 18th (``category``).
        """
        get = lambda i: raw[i] if i < len(raw) else None
        return cls(
            icao24=raw[0],
            callsign=(raw[1].strip() if raw[1] else None),
            origin_country=raw[2],
            time_position=raw[3],
            last_contact=raw[4],
            longitude=raw[5],
            latitude=raw[6],
            baro_altitude=raw[7],
            on_ground=raw[8],
            velocity=raw[9],
            true_track=raw[10],
            vertical_rate=raw[11],
            sensors=raw[12],
            geo_altitude=raw[13],
            squawk=raw[14],
            spi=raw[15],
            position_source=raw[16],
            category=get(17),
        )


class StatesResponse(BaseModel):
    """Response body of ``GET /states/all``.

    The raw API returns ``states`` as a list of positional arrays; use
    :meth:`from_raw` to parse the whole payload into named state vectors.
    """

    time: int = Field(description="Unix time (s) the snapshot of states is associated with.")
    states: list[StateVector] = Field(
        default_factory=list, description="State vectors, empty if no data is available."
    )

    @classmethod
    def from_raw(cls, payload: dict) -> "StatesResponse":
        """Parse the raw JSON returned by ``/states/all``."""
        raw_states = payload.get("states") or []
        return cls(
            time=payload["time"],
            states=[StateVector.from_array(s) for s in raw_states],
        )
