// Derives the render-ready Scenario from the backend payloads.
//
// The data itself comes from the FastAPI backend (TanStack Query hooks in
// hooks/useFlights.ts): GET /scenarios/{id}/routes for flight geometry and
// GET /sectors/geojson for sector polygons. Everything heavy (mercator
// projection, arc-length parameterisation, arrival bucketing) happens once
// here, off the render loop.

import { lngLatToMercator } from './geo'
import type { RoutesSnapshot } from '../api/types'
import type { Airport, Flight, Scenario, SectorFeature } from './types'

const BUCKET_MS = 5 * 60 * 1000 // 5-minute arrival windows

// Nominal hourly arrival capacity per airport, used for the load gauge. Core
// hubs run hot; metro relievers are smaller fields.
const CAPACITY: Record<string, number> = {
  KJFK: 44,
  KLGA: 40,
  KEWR: 44,
  KTEB: 30,
  KHPN: 24,
  KISP: 20,
  KFRG: 20,
  KSWF: 16,
  KCDW: 16,
  KMMU: 18,
  KBDR: 16,
  KLDJ: 12,
}

// VMC Airport Arrival Rate (arrivals/hr), mirroring the backend's curated
// capacity.py VMC_AAR for the slot-controlled NYC core. Metro relievers have no
// published FAA profile, so they fall back to REFERENCE_AAR (the busiest core
// AAR) — exactly as the backend's busyness.py does — keeping every airport on
// one comparable 0–100 busyness scale.
const VMC_AAR: Record<string, number> = { KJFK: 52, KLGA: 40, KEWR: 52 }
const REFERENCE_AAR = 100 // = max(capacity.VMC_AAR) (KATL) in the backend

// Parse a LOW-band sector GeoJSON FeatureCollection into SectorFeatures, keeping
// the outer ring flat for fast point-in-polygon tests.
export function parseLowSectors(gj: GeoJSON.FeatureCollection): SectorFeature[] {
  const out: SectorFeature[] = []
  for (const f of gj.features) {
    const props = (f.properties ?? {}) as Record<string, unknown>
    const name = String(props.name ?? '')
    if (!name.startsWith('LOW')) continue
    if (f.geometry?.type !== 'Polygon') continue
    const coords = f.geometry.coordinates[0] as number[][] // outer ring
    const ring = new Float64Array(coords.length * 2)
    for (let i = 0; i < coords.length; i++) {
      ring[i * 2] = coords[i][0]
      ring[i * 2 + 1] = coords[i][1]
    }
    out.push({
      name,
      band: 'LOW',
      altFrom: Number(props.altitude_from_ft ?? 0),
      altTo: Number(props.altitude_to_ft ?? 0),
      capacity: Number(props.capacity ?? 0),
      ring,
    })
  }
  return out
}

// Build the render-ready Scenario from a routes snapshot fetched from the backend.
export function deriveScenario(snap: RoutesSnapshot): Scenario {
  const windowStart = Date.parse(snap.window_start)
  const windowEnd = Date.parse(snap.window_end)
  const bucketCount = Math.max(1, Math.ceil((windowEnd - windowStart) / BUCKET_MS))

  const filter = snap.nyc_filter ?? { core: [], metro_extra: [] }
  const coreSet = new Set(filter.core)

  const flights: Flight[] = []
  const airportLngLat = new Map<string, { lng: number; lat: number }>()
  const arrivalsByAirport = new Map<string, Int32Array>()
  const departuresByAirport = new Map<string, Int32Array>()
  const totals = new Int32Array(bucketCount)

  const ensureBucket = (map: Map<string, Int32Array>, icao: string) => {
    let a = map.get(icao)
    if (!a) {
      a = new Int32Array(bucketCount)
      map.set(icao, a)
    }
    return a
  }

  let idx = 0
  for (const rf of snap.flights) {
    const n = Math.min(rf.lats.length, rf.lons.length)
    if (n < 2) continue
    const mx = new Float32Array(n)
    const my = new Float32Array(n)
    const cum = new Float32Array(n)
    let total = 0
    for (let i = 0; i < n; i++) {
      const m = lngLatToMercator(rf.lons[i], rf.lats[i])
      mx[i] = m.x
      my[i] = m.y
      if (i > 0) {
        const dx = mx[i] - mx[i - 1]
        const dy = my[i] - my[i - 1]
        total += Math.sqrt(dx * dx + dy * dy)
      }
      cum[i] = total
    }
    if (total > 0) for (let i = 0; i < n; i++) cum[i] /= total

    const t0 = Date.parse(rf.take_off_time)
    const t1 = Date.parse(rf.scheduled_landing_time)

    if (!airportLngLat.has(rf.origin_airport_icao))
      airportLngLat.set(rf.origin_airport_icao, { lng: rf.lons[0], lat: rf.lats[0] })
    if (!airportLngLat.has(rf.destination_airport_icao))
      airportLngLat.set(rf.destination_airport_icao, { lng: rf.lons[n - 1], lat: rf.lats[n - 1] })

    if (t1 >= windowStart && t1 < windowEnd) {
      const b = Math.floor((t1 - windowStart) / BUCKET_MS)
      ensureBucket(arrivalsByAirport, rf.destination_airport_icao)[b]++
      totals[b]++
    }
    if (t0 >= windowStart && t0 < windowEnd) {
      const b = Math.floor((t0 - windowStart) / BUCKET_MS)
      ensureBucket(departuresByAirport, rf.origin_airport_icao)[b]++
    }

    flights.push({
      idx: idx++,
      number: rf.flight_number,
      origin: rf.origin_airport_icao,
      dest: rf.destination_airport_icao,
      cruiseAltFt: rf.cruise_altitude_ft,
      cruiseSpeedKt: rf.cruise_speed_kt,
      airborneAtStart: rf.is_airborne,
      t0,
      t1,
      mx,
      my,
      cum,
    })
  }

  const nyc = [...filter.core, ...filter.metro_extra]
  const airports: Airport[] = []
  const airportByIcao = new Map<string, Airport>()
  for (const icao of nyc) {
    const ll = airportLngLat.get(icao)
    if (!ll) continue
    const buckets = arrivalsByAirport.get(icao) ?? new Int32Array(bucketCount)
    const depBuckets = departuresByAirport.get(icao) ?? new Int32Array(bucketCount)
    let arrivalsTotal = 0
    for (let i = 0; i < buckets.length; i++) arrivalsTotal += buckets[i]
    const a: Airport = {
      icao,
      lng: ll.lng,
      lat: ll.lat,
      isCore: coreSet.has(icao),
      arrivalBuckets: buckets,
      departureBuckets: depBuckets,
      arrivalsTotal,
      capacity: CAPACITY[icao] ?? 20,
      aar: VMC_AAR[icao] ?? REFERENCE_AAR,
    }
    airports.push(a)
    airportByIcao.set(icao, a)
  }
  airports.sort((a, b) => b.arrivalsTotal - a.arrivalsTotal)

  return {
    date: String(snap.window_start).slice(0, 10),
    windowStart,
    windowEnd,
    bucketMs: BUCKET_MS,
    bucketCount,
    flights,
    airports,
    airportByIcao,
    totalArrivalBuckets: totals,
    coreIcaos: filter.core,
    metroIcaos: filter.metro_extra,
  }
}

// Rolling arrivals in the 60 minutes starting at bucket index b (inclusive).
export function rollingHour(buckets: Int32Array, b: number): number {
  let sum = 0
  for (let i = b; i < Math.min(b + 12, buckets.length); i++) sum += buckets[i]
  return sum
}
