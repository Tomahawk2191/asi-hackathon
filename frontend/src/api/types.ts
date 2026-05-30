// TypeScript types that mirror the Pydantic models.

// /scenarios

export interface ScenariosResponse {
  scenarios: string[]   // e.g. ["asked_at_2025-05-29T21-00-00Z", ...]
  default: string | null // earliest scenario, used when none is specified
}

// /sectors

export interface SectorSummary {
  name: string             // e.g. "LOW_295" or "HIGH_042"
  altitude_from_ft: number // LOW = 0, HIGH = 35000
  altitude_to_ft: number   // LOW = 35000, HIGH = 60000
  capacity: number         // max simultaneous flights
}

export interface SectorsResponse {
  count: number
  sectors: SectorSummary[]
}

// /landings

// POST body for /landings -- which sectors to query and which scenario to use.
// Pass LOW band sectors (altitude_from_ft = 0) since landings happen at ground level.
export interface LandingsRequest {
  sector_names: string[]  // e.g. ["LOW_295"] -- use /sectors to look these up
  scenario?: string       // omit to use the default (earliest) scenario
}

// Arrival counts per airport for the queried sector set.
// per_airport is sorted high → low -- the most congested airport is first.
export interface LandingsResponse {
  scenario: string
  sector_names: string[]
  total_flights: number
  per_airport: Record<string, number>  // ICAO → landing count, e.g. { KJFK: 209, KLGA: 264 }
}

// /sectors/population -- live sector occupancy at a moment, by altitude band

export interface SectorPopRow {
  name: string
  count: number       // flights inside the sector right now
  capacity: number
  ratio: number       // count / capacity (>1 = over capacity)
}

export interface SectorPopulationResponse {
  scenario: string
  time: string
  band: 'LOW' | 'HIGH'
  total: number
  occupied: number
  sectors: SectorPopRow[]  // busiest first
}

// /recommend

export interface AirportLoad {
  airport: string
  rolling_arrivals: number
  aar: number
  utilization: number        // 0.0–1.0+ (>1 = over capacity)
  available_capacity: number // aar - rolling_arrivals (negative = overloaded)
  is_overloaded: boolean
}

export interface RecommendRequest {
  airport: string            // desired destination ICAO, e.g. "KJFK"
  time: string               // ISO-8601 UTC arrival time
  day?: string               // YYYY-MM-DD, defaults to 2025-12-25
  alternatives?: string[]    // ICAOs to score; defaults to all NYC core airports
}

export interface RecommendResponse {
  requested_airport: string
  requested_time: string
  day: string
  target: AirportLoad
  alternatives: AirportLoad[]  // sorted by available_capacity desc
  recommendation: string | null // best alternative ICAO, or null if target is fine
}

// /arrivals -- stored 5-minute arrival counts per airport for a day (SQLite DB).
// Backs the non-NYC metros, which carry no route geometry.

export interface ArrivalFrequencyRow {
  day: string
  direction: string
  sector: string | null
  airport: string
  bucket_start: string // ISO-8601 UTC
  flight_count: number
}

export interface ArrivalsResponse {
  day: string
  direction: string
  sector: string | null
  count: number
  rows: ArrivalFrequencyRow[]
}

// /scenarios/{id}/routes (planned -- endpoint not yet live)

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
