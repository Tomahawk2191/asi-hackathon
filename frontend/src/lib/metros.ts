// Frontend-only registry of metro areas. Used to pan/zoom the map to a region
// and to filter flights by the metro a flight touches (core hub or reliever).
// The `nyc` entry mirrors the dataset's `nyc_filter` (data/nyc_dataset), so the
// default NYC view is effectively a no-op filter over the NYC-scoped snapshot.

export interface Metro {
  id: string
  label: string
  center: [number, number] // [lng, lat]
  zoom: number
  core: string[] // primary hub ICAOs — bigger dots, real capacity
  extra: string[] // secondary fields / relievers
}

export const METROS: Metro[] = [
  {
    id: 'nyc',
    label: 'NYC Metro',
    center: [-73.78, 40.7],
    zoom: 7.2,
    core: ['KJFK', 'KLGA', 'KEWR'],
    extra: ['KTEB', 'KHPN', 'KISP', 'KFRG', 'KSWF', 'KCDW', 'KMMU', 'KBDR', 'KLDJ'],
  },
  {
    id: 'bos',
    label: 'Boston',
    center: [-71.01, 42.36],
    zoom: 8.2,
    core: ['KBOS'],
    extra: ['KPVD', 'KBDL', 'KMHT'],
  },
  {
    id: 'chi',
    label: 'Chicago',
    center: [-87.83, 41.9],
    zoom: 8.2,
    core: ['KORD'],
    extra: ['KMDW'],
  },
  {
    id: 'atl',
    label: 'Atlanta',
    center: [-84.43, 33.64],
    zoom: 8.6,
    core: ['KATL'],
    extra: [],
  },
  {
    id: 'dca',
    label: 'Washington DC',
    center: [-77.2, 38.95],
    zoom: 8.0,
    core: ['KDCA', 'KIAD', 'KBWI'],
    extra: [],
  },
  {
    id: 'mia',
    label: 'South Florida',
    center: [-80.18, 26.18],
    zoom: 7.8,
    core: ['KMIA', 'KFLL', 'KPBI'],
    extra: [],
  },
  {
    id: 'lax',
    label: 'Los Angeles',
    center: [-118.3, 33.97],
    zoom: 8.2,
    core: ['KLAX'],
    extra: ['KSNA', 'KBUR', 'KONT'],
  },
  {
    id: 'sfo',
    label: 'SF Bay Area',
    center: [-122.2, 37.6],
    zoom: 8.4,
    core: ['KSFO'],
    extra: ['KOAK', 'KSJC'],
  },
]

export const DEFAULT_METRO = 'nyc'

// Look up a metro by id, falling back to the NYC metro for unknown ids so the
// caller always gets a usable region to render.
export function metroById(id: string): Metro {
  return METROS.find((m) => m.id === id) ?? METROS.find((m) => m.id === DEFAULT_METRO)!
}
