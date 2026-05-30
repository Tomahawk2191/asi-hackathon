// Samples a flight's position along its mercator polyline at a given sim time.
// Position is parameterised by arc length: progress p = (t - t0)/(t1 - t0) maps
// linearly to distance travelled, then we walk the cumulative-length table to
// find the enclosing segment. No allocation — caller passes a scratch object.

import type { Flight } from './types'

export interface FlightSample {
  active: boolean
  x: number // mercator
  y: number
  dx: number // unit heading vector (mercator space)
  dy: number
  progress: number // 0..1
}

const _scratch: FlightSample = { active: false, x: 0, y: 0, dx: 0, dy: 1, progress: 0 }

export function sampleFlight(f: Flight, t: number, out: FlightSample = _scratch): FlightSample {
  const span = f.t1 - f.t0
  const p = span > 0 ? (t - f.t0) / span : -1
  out.progress = p
  if (p < 0 || p > 1) {
    out.active = false
    return out
  }
  out.active = true

  const cum = f.cum
  const n = cum.length
  // find segment i such that cum[i] <= p <= cum[i+1]
  let i = 1
  while (i < n - 1 && cum[i] < p) i++
  const a = i - 1
  const segLen = cum[i] - cum[a] || 1e-9
  const local = (p - cum[a]) / segLen

  const ax = f.mx[a]
  const ay = f.my[a]
  const bx = f.mx[i]
  const by = f.my[i]
  out.x = ax + (bx - ax) * local
  out.y = ay + (by - ay) * local

  const hx = bx - ax
  const hy = by - ay
  const hl = Math.hypot(hx, hy)
  if (hl < 1e-9) {
    out.dx = 0
    out.dy = 1 // keep a stable heading on zero-length segments
  } else {
    out.dx = hx / hl
    out.dy = hy / hl
  }
  return out
}
