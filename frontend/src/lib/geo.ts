// Web-Mercator helpers. We work in MapLibre's "mercator square" coordinate
// space: the whole world maps to the unit square [0,1] x [0,1], with (0,0) at
// the top-left (lng -180, lat ~85.05) and (1,1) at the bottom-right. This is
// exactly the space MapLibre's custom-layer projection matrix expects, so any
// point we convert here can be multiplied by that matrix to land on screen.

export interface MercatorXY {
  x: number
  y: number
}

const DEG2RAD = Math.PI / 180

// lng/lat (degrees) -> mercator unit-square coordinates.
export function lngLatToMercator(lng: number, lat: number): MercatorXY {
  const x = (180 + lng) / 360
  const sin = Math.sin(lat * DEG2RAD)
  const y = 0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)
  return { x, y }
}

// Inverse of lngLatToMercator: mercator unit-square -> lng/lat (degrees).
export function mercatorToLngLat(x: number, y: number): [number, number] {
  const lng = x * 360 - 180
  const lat = (Math.atan(Math.sinh(Math.PI * (1 - 2 * y))) * 180) / Math.PI
  return [lng, lat]
}

// Distance between two mercator points (unit-square units). Good enough for
// arc-length parameterisation of a flight's polyline at NYC-metro scale.
export function mercatorDist(ax: number, ay: number, bx: number, by: number): number {
  const dx = bx - ax
  const dy = by - ay
  return Math.sqrt(dx * dx + dy * dy)
}

// Point-in-polygon (ray casting) over a single linear ring in lng/lat.
// `ring` is a flat [lng, lat, lng, lat, ...] array.
export function pointInRing(lng: number, lat: number, ring: Float64Array): boolean {
  let inside = false
  const n = ring.length / 2
  for (let i = 0, j = n - 1; i < n; j = i++) {
    const xi = ring[i * 2]
    const yi = ring[i * 2 + 1]
    const xj = ring[j * 2]
    const yj = ring[j * 2 + 1]
    const intersect =
      yi > lat !== yj > lat &&
      lng < ((xj - xi) * (lat - yi)) / (yj - yi) + xi
    if (intersect) inside = !inside
  }
  return inside
}
