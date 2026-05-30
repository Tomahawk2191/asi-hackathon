// Derives the render-ready Scenario from the backend payloads.
//
// The data itself comes from the FastAPI backend (TanStack Query hooks in
// hooks/useFlights.ts): GET /scenarios/{id}/routes for flight geometry and
// GET /sectors/geojson for sector polygons. Everything heavy (mercator
// projection, arc-length parameterisation, arrival bucketing) happens once
// here, off the render loop.

import { lngLatToMercator } from './geo'
import type { Metro } from './metros'
import type { ArrivalFrequencyRow, RoutesSnapshot } from '../api/types'
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
  // Other metros' core hubs and relievers. Numbers reuse the backend's VMC AAR
  // (backend/capacity.py); relievers without a published FAA profile get a
  // sensible smaller default. Anything absent falls back to 20 below.
  KBOS: 44,
  KPVD: 24,
  KBDL: 24,
  KMHT: 18,
  KORD: 80,
  KMDW: 40,
  KATL: 100,
  KDCA: 40,
  KIAD: 52,
  KBWI: 40,
  KMIA: 52,
  KFLL: 30,
  KPBI: 24,
  KLAX: 60,
  KSNA: 20,
  KBUR: 20,
  KONT: 20,
  KSFO: 60,
  KOAK: 22,
  KSJC: 22,
  // DB hubs (the 2025-12-25 arrival-count metros). These AARs come from the
  // backend's airport_capacity table; anything absent falls back to 20 below.
  KDEN: 72,
  KDFW: 78,
  KDAL: 36,
  KPHX: 54,
  KSEA: 46,
  KLGB: 20,
}

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
export function deriveScenario(snap: RoutesSnapshot, metro: Metro): Scenario {
  const windowStart = Date.parse(snap.window_start)
  const windowEnd = Date.parse(snap.window_end)
  const bucketCount = Math.max(1, Math.ceil((windowEnd - windowStart) / BUCKET_MS))

  // Airports that belong to the selected metro (core hubs + relievers). The
  // timeline and airport list are scoped to this set; per-flight geometry and
  // the arrival maps below still index ALL airports.
  const metroSet = new Set([...metro.core, ...metro.extra])

  const flights: Flight[] = []
  const airportLngLat = new Map<string, { lng: number; lat: number }>()
  const arrivalsByAirport = new Map<string, Int32Array>()
  const totals = new Int32Array(bucketCount)

  const ensureAirport = (icao: string) => {
    let a = arrivalsByAirport.get(icao)
    if (!a) {
      a = new Int32Array(bucketCount)
      arrivalsByAirport.set(icao, a)
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
      ensureAirport(rf.destination_airport_icao)[b]++
      if (metroSet.has(rf.destination_airport_icao)) totals[b]++
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

  const coreSet = new Set(metro.core)
  const airports: Airport[] = []
  const airportByIcao = new Map<string, Airport>()
  for (const icao of [...metro.core, ...metro.extra]) {
    const ll = airportLngLat.get(icao)
    if (!ll) continue
    const buckets = arrivalsByAirport.get(icao) ?? new Int32Array(bucketCount)
    let arrivalsTotal = 0
    for (let i = 0; i < buckets.length; i++) arrivalsTotal += buckets[i]
    const a: Airport = {
      icao,
      lng: ll.lng,
      lat: ll.lat,
      isCore: coreSet.has(icao),
      arrivalBuckets: buckets,
      arrivalsTotal,
      capacity: CAPACITY[icao] ?? 20,
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
    coreIcaos: metro.core,
    metroIcaos: metro.extra,
  }
}

// Build the render-ready Scenario from stored 5-minute arrival counts (GET
// /arrivals), used by non-NYC metros. The DB carries no route geometry, so
// `flights` is empty by design — the map renders airport dots, the load board,
// timeline, and sector grid, but no animated tracks. Coordinates come from the
// metro registry (the DB has none).
export function deriveScenarioFromDb(rows: ArrivalFrequencyRow[], metro: Metro): Scenario {
  const metroAirports = [...metro.core, ...metro.extra]
  const metroSet = new Set(metroAirports)
  const filtered = rows.filter((r) => metroSet.has(r.airport))

  // No rows for this metro: return a minimal but valid Scenario so the UI still
  // mounts (single empty bucket, no airports).
  if (filtered.length === 0) {
    const t = metro.day ? Date.parse(metro.day + 'T00:00:00Z') : Date.now()
    return {
      date: metro.day ?? rows[0]?.day ?? '',
      windowStart: t,
      windowEnd: t,
      bucketMs: BUCKET_MS,
      bucketCount: 1,
      flights: [],
      airports: [],
      airportByIcao: new Map(),
      totalArrivalBuckets: new Int32Array(1),
      coreIcaos: metro.core,
      metroIcaos: metro.extra,
    }
  }

  let windowStart = Infinity
  let maxStart = -Infinity
  for (const r of filtered) {
    const t = Date.parse(r.bucket_start)
    if (t < windowStart) windowStart = t
    if (t > maxStart) maxStart = t
  }
  const windowEnd = maxStart + BUCKET_MS
  const bucketCount = Math.max(1, Math.ceil((windowEnd - windowStart) / BUCKET_MS))

  const arrivalsByAirport = new Map<string, Int32Array>()
  const totals = new Int32Array(bucketCount)
  const ensureAirport = (icao: string) => {
    let a = arrivalsByAirport.get(icao)
    if (!a) {
      a = new Int32Array(bucketCount)
      arrivalsByAirport.set(icao, a)
    }
    return a
  }

  for (const r of filtered) {
    const b = Math.floor((Date.parse(r.bucket_start) - windowStart) / BUCKET_MS)
    if (b < 0 || b >= bucketCount) continue
    ensureAirport(r.airport)[b] += r.flight_count
    totals[b] += r.flight_count
  }

  const coreSet = new Set(metro.core)
  const airports: Airport[] = []
  const airportByIcao = new Map<string, Airport>()
  for (const icao of metroAirports) {
    const ll = metro.coords?.[icao]
    if (!ll) continue // db metros must supply coords; skip any without
    const buckets = arrivalsByAirport.get(icao) ?? new Int32Array(bucketCount)
    let arrivalsTotal = 0
    for (let i = 0; i < buckets.length; i++) arrivalsTotal += buckets[i]
    const a: Airport = {
      icao,
      lng: ll[0],
      lat: ll[1],
      isCore: coreSet.has(icao),
      arrivalBuckets: buckets,
      arrivalsTotal,
      capacity: CAPACITY[icao] ?? 20,
    }
    airports.push(a)
    airportByIcao.set(icao, a)
  }
  airports.sort((a, b) => b.arrivalsTotal - a.arrivalsTotal)

  return {
    date: metro.day ?? rows[0]?.day ?? '',
    windowStart,
    windowEnd,
    bucketMs: BUCKET_MS,
    bucketCount,
    flights: [],
    airports,
    airportByIcao,
    totalArrivalBuckets: totals,
    coreIcaos: metro.core,
    metroIcaos: metro.extra,
  }
}

// Rolling arrivals in the 60 minutes starting at bucket index b (inclusive).
export function rollingHour(buckets: Int32Array, b: number): number {
  let sum = 0
  for (let i = b; i < Math.min(b + 12, buckets.length); i++) sum += buckets[i]
  return sum
}
