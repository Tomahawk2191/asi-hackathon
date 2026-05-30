// Domain types for the Airport Load console. These mirror the on-disk NYC
// dataset (data/nyc_dataset/*.json) plus a few derived shapes we precompute
// once at load time so the render loop stays allocation-free.

// --- raw on-disk schema (one scenario snapshot per day) ----------------------

export interface RawFlight {
  flight_number: string
  take_off_time: string // UTC ISO-8601
  scheduled_landing_time: string // UTC ISO-8601
  origin_airport_icao: string
  destination_airport_icao: string
  cruise_altitude_ft: number
  cruise_speed_kt: number
  lats: number[]
  lons: number[]
  is_airborne: boolean
}

export interface NycFilter {
  core: string[]
  metro_extra: string[]
}

export interface RawSnapshot {
  asked_at: string
  window_start: string
  window_end: string
  nyc_filter: NycFilter
  flights: RawFlight[]
}

export interface ManifestDay {
  date: string
  file: string
  window_start: string
  window_end: string
  metro_flights: number
  core_flights: number
  departures_from_nyc: number
  arrivals_to_nyc: number
  per_core_airport: Record<string, number>
}

export interface Manifest {
  airports: NycFilter
  days: ManifestDay[]
}

// --- derived, render-ready shapes --------------------------------------------

// A flight with its route pre-projected to mercator unit-square space and
// arc-length parameterised, so we can find its position at any time t with a
// single binary-search-free linear scan.
export interface Flight {
  idx: number
  number: string
  origin: string
  dest: string
  cruiseAltFt: number
  cruiseSpeedKt: number
  airborneAtStart: boolean
  t0: number // takeoff epoch ms
  t1: number // scheduled landing epoch ms
  // mercator polyline + cumulative normalised arc length (0..1)
  mx: Float32Array
  my: Float32Array
  cum: Float32Array // length === mx.length, cum[last] === 1
}

export interface Airport {
  icao: string
  lng: number
  lat: number
  isCore: boolean
  // arrivals bucketed into 5-min windows across the day window
  arrivalBuckets: Int32Array
  // departures (origin + take-off time) bucketed the same way; with arrivals
  // these give the movements the busyness score is built from
  departureBuckets: Int32Array
  arrivalsTotal: number
  // nominal hourly arrival capacity used for the load gauge
  capacity: number
  // VMC arrival acceptance rate (arrivals/hr); score = 100 * movements / (2 * aar)
  aar: number
}

export interface SectorFeature {
  name: string
  band: 'LOW' | 'HIGH'
  altFrom: number
  altTo: number
  capacity: number
  // outer ring as flat [lng,lat,...] for point-in-polygon (LOW only kept)
  ring: Float64Array
}

export type Selection =
  | { kind: 'flight'; idx: number }
  | { kind: 'sector'; name: string }
  | { kind: 'airport'; icao: string }
  | null

export interface Scenario {
  date: string
  windowStart: number // epoch ms
  windowEnd: number // epoch ms
  bucketMs: number // 5 min
  bucketCount: number
  flights: Flight[]
  airports: Airport[]
  airportByIcao: Map<string, Airport>
  // total arrivals per 5-min bucket across all NYC airports (timeline histogram)
  totalArrivalBuckets: Int32Array
  coreIcaos: string[]
  metroIcaos: string[]
}
