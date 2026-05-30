// Demand-only map for days without a flight snapshot (e.g. Christmas BTS data).
// Shows all seeded airports as utilization-colored circles on a US-wide base map.
// Reuses the same color ramp and MapLibre style as FlightMap.

import { useEffect, useRef } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { brutalistStyle } from '../lib/mapStyle'

// Coordinates for every airport seeded by seed_bts.py. core=true = primary airport
// of its metro (used to scale the dot and label brightness).
const AIRPORT_POSITIONS: Record<string, { lat: number; lng: number; core: boolean }> = {
  // NYC
  KJFK: { lat: 40.6413, lng: -73.7781, core: true },
  KLGA: { lat: 40.7773, lng: -73.8726, core: true },
  KEWR: { lat: 40.6895, lng: -74.1745, core: true },
  // LAX metro
  KLAX: { lat: 33.9425, lng: -118.4081, core: true },
  KBUR: { lat: 34.2007, lng: -118.3585, core: false },
  KLGB: { lat: 33.8177, lng: -118.1516, core: false },
  KONT: { lat: 34.0560, lng: -117.6012, core: false },
  KSNA: { lat: 33.6757, lng: -117.8683, core: false },
  // SF Bay Area
  KSFO: { lat: 37.6213, lng: -122.3790, core: true },
  KOAK: { lat: 37.7213, lng: -122.2208, core: false },
  KSJC: { lat: 37.3626, lng: -121.9292, core: false },
  // Chicago
  KORD: { lat: 41.9742, lng: -87.9073, core: true },
  KMDW: { lat: 41.7868, lng: -87.7524, core: false },
  // Dallas
  KDFW: { lat: 32.8998, lng: -97.0403, core: true },
  KDAL: { lat: 32.8471, lng: -96.8518, core: false },
  // Miami
  KMIA: { lat: 25.7959, lng: -80.2870, core: true },
  KFLL: { lat: 26.0726, lng: -80.1527, core: false },
  // Single-airport metros
  KATL: { lat: 33.6407, lng: -84.4277, core: true },
  KDEN: { lat: 39.8561, lng: -104.6737, core: true },
  KBOS: { lat: 42.3656, lng: -71.0096, core: true },
  KPHX: { lat: 33.4373, lng: -112.0078, core: true },
  KSEA: { lat: 47.4502, lng: -122.3088, core: true },
}

function buildFC(): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: Object.entries(AIRPORT_POSITIONS).map(([icao, pos]) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [pos.lng, pos.lat] },
      properties: { icao, core: pos.core },
    })),
  }
}

function applyScores(map: maplibregl.Map, scores: Record<string, number> | null) {
  if (!scores || !map.getSource('airports')) return
  map.removeFeatureState({ source: 'airports' })
  for (const [icao, score] of Object.entries(scores)) {
    map.setFeatureState({ source: 'airports', id: icao }, { score })
  }
}

interface Props {
  airportScores: Record<string, number> | null
  label?: string  // optional overlay badge, e.g. "DEMAND MODE · CHRISTMAS 2025"
}

const US_CENTER: [number, number] = [-96, 38]

export default function CapacityMap({ airportScores, label }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  // Ref so the idle handler always reads the latest scores, not a stale closure.
  const scoresRef = useRef(airportScores)
  scoresRef.current = airportScores

  // One-time map setup
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: brutalistStyle(),
      center: US_CENTER,
      zoom: 3.4,
      attributionControl: false,
    })
    mapRef.current = map
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right')
    map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-left')

    map.on('load', () => {
      map.addSource('airports', {
        type: 'geojson',
        data: buildFC(),
        promoteId: 'icao',
      })

      // Reuse the same color ramp as FlightMap so the two views look consistent.
      const score = ['coalesce', ['feature-state', 'score'], -1] as unknown as maplibregl.ExpressionSpecification

      map.addLayer({
        id: 'airport-dot',
        type: 'circle',
        source: 'airports',
        paint: {
          'circle-radius': [
            'interpolate', ['linear'], score,
            -1, ['case', ['get', 'core'], 5, 3.5],
            0,  ['case', ['get', 'core'], 5, 3.5],
            60, 8,
            110, 12,
          ],
          'circle-color': [
            'interpolate', ['linear'], score,
            -1, '#0a0e14',
            1,  '#59e6c3',
            40, '#8fd66b',
            65, '#ffb000',
            90, '#ff8a3d',
            110, '#ff5233',
          ],
          'circle-stroke-color': ['case', ['get', 'core'], '#eaf1fb', '#7d8aa0'],
          'circle-stroke-width': ['case', ['get', 'core'], 1.6, 1],
          'circle-opacity': 0.92,
        },
      })

      map.addLayer({
        id: 'airport-label',
        type: 'symbol',
        source: 'airports',
        layout: {
          'text-field': ['get', 'icao'],
          'text-font': ['Noto Sans Regular'],
          'text-size': ['case', ['get', 'core'], 11, 9],
          'text-offset': [0, -1.3],
          'text-letter-spacing': 0.1,
          'text-anchor': 'bottom',
        },
        paint: {
          'text-color': ['case', ['get', 'core'], '#eaf1fb', '#9aa6ba'],
          'text-halo-color': '#04060a',
          'text-halo-width': 1.6,
        },
      })
    })

    map.on('idle', () => {
      // Use the ref so we always get the latest scores, not the stale closure value.
      applyScores(map, scoresRef.current)
    })

    return () => {
      mapRef.current = null
      map.remove()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Re-apply scores when the prop updates after the map has already loaded.
  // If the map isn't ready yet, the idle handler will pick up scoresRef.current.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !map.isStyleLoaded() || !map.getSource('airports')) return
    applyScores(map, airportScores)
  }, [airportScores])

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
      {label && (
        <div className="capacity-map-badge">{label}</div>
      )}
    </div>
  )
}
