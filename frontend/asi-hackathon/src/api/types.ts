// TypeScript types that mirror the Pydantic models in backend/flights.py.

// A single planned flight from the hackathon data bundle.
export interface Flight {
  flight_number: string
  take_off_time: string           // UTC ISO 8601
  scheduled_landing_time: string  // UTC ISO 8601
  origin_airport_icao: string     // e.g. "KJFK"
  destination_airport_icao: string
  cruise_altitude_ft: number
  cruise_speed_kt: number
  lats: number[]
  lons: number[]
  is_airborne: boolean  // false = pre-departure, eligible for rerouting
}

// Which airports count as "NYC" for load-balancing purposes.
export interface NycFilter {
  core: string[]
  metro_extra: string[]
}

// Top-level payload from a single scenario's routes.json.
// Each scenario is a snapshot of all planned US flights at a point in time.
export interface RoutesSnapshot {
  asked_at: string      // the "as-of" timestamp for this scenario
  window_start: string  // flights with departures inside [window_start, window_end)
  window_end: string
  nyc_filter?: NycFilter
  flights: Flight[]
}
