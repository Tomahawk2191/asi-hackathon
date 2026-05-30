// Derived analytics computed on demand (not in the render loop): the current
// time bucket, per-airport rolling load, and which airports are over their
// arrival capacity right now. (Sector landings come live from the backend
// /landings endpoint, not from here.)

import { rollingHour } from './data'
import type { Scenario } from './types'

export function bucketAt(s: Scenario, t: number): number {
  return Math.min(s.bucketCount - 1, Math.max(0, Math.floor((t - s.windowStart) / s.bucketMs)))
}

export interface AirportLoad {
  icao: string
  rolling: number // arrivals in the next 60 min
  capacity: number
  ratio: number
  over: boolean
  // busyness score: 100 * (arrivals + departures) / (2 * aar). ~100 = saturated
  // (a balanced airport running its AAR for both arrivals and departures); can exceed 100.
  score: number
}

// Per-airport rolling-hour load at sim time t, busiest first.
export function airportLoads(s: Scenario, t: number): AirportLoad[] {
  const b = bucketAt(s, t)
  return s.airports
    .map((a) => {
      const rolling = rollingHour(a.arrivalBuckets, b)
      const ratio = rolling / a.capacity
      // Movements-based busyness score, mirroring backend busyness.py: arrivals +
      // departures over the same rolling hour, against a 2*AAR practical ceiling.
      const movements = rolling + rollingHour(a.departureBuckets, b)
      const score = Math.round((100 * movements) / (2 * a.aar))
      return { icao: a.icao, rolling, capacity: a.capacity, ratio, over: rolling > a.capacity, score }
    })
    .sort((x, y) => y.score - x.score)
}

// Set of ICAOs currently over capacity (used to color arriving aircraft red).
export function overloadedSet(s: Scenario, t: number): Set<string> {
  const b = bucketAt(s, t)
  const out = new Set<string>()
  for (const a of s.airports) {
    if (rollingHour(a.arrivalBuckets, b) > a.capacity) out.add(a.icao)
  }
  return out
}

// Count of aircraft airborne (within their takeoff..landing window) at time t.
export function countActive(s: Scenario, t: number): number {
  let n = 0
  for (const f of s.flights) if (t >= f.t0 && t <= f.t1) n++
  return n
}

export function fmtClock(t: number): string {
  const d = new Date(t)
  const hh = String(d.getUTCHours()).padStart(2, '0')
  const mm = String(d.getUTCMinutes()).padStart(2, '0')
  const ss = String(d.getUTCSeconds()).padStart(2, '0')
  return `${hh}:${mm}:${ss}Z`
}

export function fmtDate(t: number): string {
  return new Date(t).toISOString().slice(0, 10)
}
