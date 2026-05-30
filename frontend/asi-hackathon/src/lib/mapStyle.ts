// A hand-built techno-brutalist basemap style over OpenFreeMap's free
// (no-key) OpenMapTiles vector source. Near-black land, faintly lit water,
// hairline roads and boundaries, uppercased letter-spaced labels. The map is
// deliberately quiet so the sector grid and live aircraft read on top of it.

import type { StyleSpecification } from 'maplibre-gl'

const TILES = 'https://tiles.openfreemap.org/planet'
const GLYPHS = 'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf'

const LAND = '#070a0f'
const WATER = '#0c121b'
const ROAD = '#1c222d'
const ROAD_HI = '#2c3340'
const BOUNDARY = '#2a313d'
const LABEL = '#aeb8c6'
const LABEL_HI = '#eaf1fb'
const HALO = '#04060a'
const FONT = ['Noto Sans Regular']

export function brutalistStyle(): StyleSpecification {
  return {
    version: 8,
    glyphs: GLYPHS,
    sources: {
      omt: { type: 'vector', url: TILES },
    },
    layers: [
      { id: 'bg', type: 'background', paint: { 'background-color': LAND } },
      {
        id: 'water',
        type: 'fill',
        source: 'omt',
        'source-layer': 'water',
        paint: { 'fill-color': WATER },
      },
      {
        id: 'waterway',
        type: 'line',
        source: 'omt',
        'source-layer': 'waterway',
        paint: { 'line-color': WATER, 'line-width': ['interpolate', ['linear'], ['zoom'], 6, 0.4, 12, 1.4] },
      },
      {
        id: 'park',
        type: 'fill',
        source: 'omt',
        'source-layer': 'park',
        paint: { 'fill-color': '#0a0f12', 'fill-opacity': 0.5 },
      },
      {
        id: 'boundary',
        type: 'line',
        source: 'omt',
        'source-layer': 'boundary',
        filter: ['<=', ['get', 'admin_level'], 4],
        paint: {
          'line-color': BOUNDARY,
          'line-width': ['interpolate', ['linear'], ['zoom'], 3, 0.4, 10, 1.2],
          'line-dasharray': [3, 2],
        },
      },
      {
        id: 'road-minor',
        type: 'line',
        source: 'omt',
        'source-layer': 'transportation',
        filter: ['in', ['get', 'class'], ['literal', ['minor', 'service', 'street', 'tertiary']]],
        minzoom: 11,
        paint: {
          'line-color': ROAD,
          'line-width': ['interpolate', ['linear'], ['zoom'], 11, 0.3, 16, 1.4],
        },
      },
      {
        id: 'road-major',
        type: 'line',
        source: 'omt',
        'source-layer': 'transportation',
        filter: ['in', ['get', 'class'], ['literal', ['motorway', 'trunk', 'primary', 'secondary']]],
        paint: {
          'line-color': ROAD_HI,
          'line-width': ['interpolate', ['linear'], ['zoom'], 5, 0.4, 10, 1.2, 16, 3],
        },
      },
      {
        id: 'aeroway-line',
        type: 'line',
        source: 'omt',
        'source-layer': 'aeroway',
        paint: {
          'line-color': '#3c4757',
          'line-width': ['interpolate', ['linear'], ['zoom'], 10, 0.6, 14, 2.5],
        },
      },
      {
        id: 'building',
        type: 'fill',
        source: 'omt',
        'source-layer': 'building',
        minzoom: 13,
        paint: { 'fill-color': '#10151c', 'fill-opacity': 0.6 },
      },
      {
        id: 'place-major',
        type: 'symbol',
        source: 'omt',
        'source-layer': 'place',
        filter: ['in', ['get', 'class'], ['literal', ['city', 'town']]],
        layout: {
          'text-field': ['get', 'name'],
          'text-font': FONT,
          'text-size': ['interpolate', ['linear'], ['zoom'], 4, 9, 10, 14],
          'text-letter-spacing': 0.18,
          'text-transform': 'uppercase',
          'text-max-width': 8,
        },
        paint: {
          'text-color': LABEL_HI,
          'text-halo-color': HALO,
          'text-halo-width': 1.4,
        },
      },
      {
        id: 'place-minor',
        type: 'symbol',
        source: 'omt',
        'source-layer': 'place',
        filter: ['in', ['get', 'class'], ['literal', ['suburb', 'village', 'neighbourhood']]],
        minzoom: 10,
        layout: {
          'text-field': ['get', 'name'],
          'text-font': FONT,
          'text-size': 10,
          'text-letter-spacing': 0.14,
          'text-transform': 'uppercase',
        },
        paint: {
          'text-color': LABEL,
          'text-halo-color': HALO,
          'text-halo-width': 1.2,
          'text-opacity': 0.7,
        },
      },
    ],
  }
}
