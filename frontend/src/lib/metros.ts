// Frontend-only registry of metro areas. Used to pan/zoom the map to a region
// and to scope airports/flights to the metro a flight touches (core hub or reliever).
//
// Two data sources back these metros:
//   - `nyc` (source: 'json') mirrors the dataset's `nyc_filter` (data/nyc_dataset)
//     and renders animated flight tracks from the JSON snapshot (/scenarios/{id}/routes).
//   - Every other metro (source: 'db') has no route geometry; its data is aggregated
//     5-minute arrival counts pulled from the SQLite DB (GET /arrivals?day=2025-12-25),
//     and only exists for the single day 2025-12-25. The DB carries no coordinates,
//     so db metros must supply per-airport `coords` here.

export interface Metro {
  id: string
  label: string
  center: [number, number] // [lng, lat]
  zoom: number
  source: 'json' | 'db' // nyc = json (animated tracks); all others = db (arrival counts)
  day?: string // db metros: the only day available (2025-12-25)
  core: string[] // primary hub ICAOs — bigger dots, real capacity
  extra: string[] // secondary fields / relievers
  coords?: Record<string, [number, number]> // [lng,lat] per ICAO; required for db metros
}

export const METROS: Metro[] = [
  {
    id: 'nyc',
    label: 'NYC Metro',
    center: [-73.78, 40.7],
    zoom: 7.2,
    source: 'json',
    core: ['KJFK', 'KLGA', 'KEWR'],
    extra: ['KTEB', 'KHPN', 'KISP', 'KFRG', 'KSWF', 'KCDW', 'KMMU', 'KBDR', 'KLDJ'],
  },
  {
    id: 'atl',
    label: 'Atlanta',
    center: [-84.43, 33.64],
    zoom: 8.6,
    source: 'db',
    day: '2025-12-25',
    core: ['KATL'],
    extra: [],
    coords: { KATL: [-84.428, 33.637] },
  },
  {
    id: 'bos',
    label: 'Boston',
    center: [-71.01, 42.36],
    zoom: 8.2,
    source: 'db',
    day: '2025-12-25',
    core: ['KBOS'],
    extra: [],
    coords: { KBOS: [-71.006, 42.363] },
  },
  {
    id: 'chi',
    label: 'Chicago',
    center: [-87.83, 41.9],
    zoom: 8.2,
    source: 'db',
    day: '2025-12-25',
    core: ['KORD'],
    extra: ['KMDW'],
    coords: { KORD: [-87.908, 41.977], KMDW: [-87.752, 41.786] },
  },
  {
    id: 'dfw',
    label: 'Dallas–Fort Worth',
    center: [-96.95, 32.87],
    zoom: 8.4,
    source: 'db',
    day: '2025-12-25',
    core: ['KDFW'],
    extra: ['KDAL'],
    coords: { KDFW: [-97.038, 32.897], KDAL: [-96.851, 32.846] },
  },
  {
    id: 'den',
    label: 'Denver',
    center: [-104.67, 39.86],
    zoom: 8.5,
    source: 'db',
    day: '2025-12-25',
    core: ['KDEN'],
    extra: [],
    coords: { KDEN: [-104.673, 39.862] },
  },
  {
    id: 'lax',
    label: 'Los Angeles',
    center: [-118.2, 33.95],
    zoom: 8.0,
    source: 'db',
    day: '2025-12-25',
    core: ['KLAX'],
    extra: ['KSNA', 'KBUR', 'KONT', 'KLGB'],
    coords: {
      KLAX: [-118.408, 33.942],
      KSNA: [-117.868, 33.676],
      KBUR: [-118.359, 34.201],
      KONT: [-117.601, 34.056],
      KLGB: [-118.152, 33.818],
    },
  },
  {
    id: 'mia',
    label: 'South Florida',
    center: [-80.2, 25.95],
    zoom: 8.4,
    source: 'db',
    day: '2025-12-25',
    core: ['KMIA'],
    extra: ['KFLL'],
    coords: { KMIA: [-80.29, 25.795], KFLL: [-80.15, 26.072] },
  },
  {
    id: 'phx',
    label: 'Phoenix',
    center: [-112.01, 33.43],
    zoom: 8.5,
    source: 'db',
    day: '2025-12-25',
    core: ['KPHX'],
    extra: [],
    coords: { KPHX: [-112.012, 33.434] },
  },
  {
    id: 'sea',
    label: 'Seattle',
    center: [-122.31, 47.45],
    zoom: 8.4,
    source: 'db',
    day: '2025-12-25',
    core: ['KSEA'],
    extra: [],
    coords: { KSEA: [-122.312, 47.45] },
  },
  {
    id: 'sfo',
    label: 'SF Bay Area',
    center: [-122.2, 37.6],
    zoom: 8.4,
    source: 'db',
    day: '2025-12-25',
    core: ['KSFO'],
    extra: ['KOAK', 'KSJC'],
    coords: {
      KSFO: [-122.375, 37.619],
      KOAK: [-122.221, 37.721],
      KSJC: [-121.929, 37.363],
    },
  },
]

export const DEFAULT_METRO = 'nyc'

// Look up a metro by id, falling back to the NYC metro for unknown ids so the
// caller always gets a usable region to render.
export function metroById(id: string): Metro {
  return METROS.find((m) => m.id === id) ?? METROS.find((m) => m.id === DEFAULT_METRO)!
}
