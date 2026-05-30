import { useEffect, useRef } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { brutalistStyle } from '../lib/mapStyle'
import { mercatorToLngLat } from '../lib/geo'
import { simClock } from '../lib/simClock'
import { fpsTracker } from '../lib/fps'
import { sampleFlight, type FlightSample } from '../lib/flightModel'
import { bucketAt } from '../lib/analysis'
import { rollingHour } from '../lib/data'
import { createFlightRenderer } from '../webgpu/Canvas2DFlightRenderer'
import { INSTANCE_FLOATS, type IFlightRenderer } from '../webgpu/FlightRenderer'
import type { SectorPopRow } from '../api/types'
import type { Scenario, Selection } from '../lib/types'

interface Props {
  scenario: Scenario
  sectorsLow: GeoJSON.FeatureCollection
  sectorsHigh: GeoJSON.FeatureCollection
  sectorBand: 'LOW' | 'HIGH'
  population: SectorPopRow[] | null
  airportScores: Record<string, number> | null
  selection: Selection
  onSelect: (s: Selection) => void
  onBackend: (b: 'webgpu' | 'canvas2d') => void
}

const NYC_CENTER: [number, number] = [-73.78, 40.7]
const BANDS = ['LOW', 'HIGH'] as const

// Choropleth fill keyed off the per-feature `ratio` (occupancy / capacity).
const POP_FILL: maplibregl.ExpressionSpecification = [
  'interpolate',
  ['linear'],
  ['coalesce', ['feature-state', 'ratio'], 0],
  0, 'rgba(60,125,214,0)',
  0.01, 'rgba(70,150,220,0.12)',
  0.5, 'rgba(95,205,225,0.26)',
  1.0, 'rgba(255,176,0,0.45)',
  1.5, 'rgba(255,82,51,0.62)',
]
const FAINT_LINE = 'rgba(120,150,190,0.22)'

export default function FlightMap({
  scenario,
  sectorsLow,
  sectorsHigh,
  sectorBand,
  population,
  airportScores,
  selection,
  onSelect,
  onBackend,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const overlayRef = useRef<HTMLCanvasElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const rendererRef = useRef<IFlightRenderer | null>(null)
  const matrixRef = useRef<Float32Array | null>(null)
  const instancesRef = useRef<Float32Array>(new Float32Array(0))
  const scenarioRef = useRef(scenario)
  const selectionRef = useRef(selection)
  const bandRef = useRef(sectorBand)
  const sizeRef = useRef({ w: 1, h: 1 })

  scenarioRef.current = scenario
  selectionRef.current = selection
  bandRef.current = sectorBand

  // --- one-time map + renderer setup ----------------------------------------
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: brutalistStyle(),
      center: NYC_CENTER,
      zoom: 7.2,
      pitch: 0,
      bearing: 0,
      maxPitch: 70,
      attributionControl: false,
    })
    mapRef.current = map
    map.addControl(new maplibregl.NavigationControl({ showCompass: true }), 'bottom-right')
    map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-left')

    const bandData = { LOW: sectorsLow, HIGH: sectorsHigh }

    map.on('load', () => {
      // --- sector grid + population choropleth, one source per band ---
      for (const band of BANDS) {
        const src = `sec-${band}`
        map.addSource(src, { type: 'geojson', data: bandData[band], promoteId: 'name' })
        map.addLayer({
          id: `sec-fill-${band}`,
          type: 'fill',
          source: src,
          layout: { visibility: band === bandRef.current ? 'visible' : 'none' },
          paint: { 'fill-color': POP_FILL },
        })
        map.addLayer({
          id: `sec-line-${band}`,
          type: 'line',
          source: src,
          layout: { visibility: band === bandRef.current ? 'visible' : 'none' },
          paint: {
            'line-color': [
              'case',
              ['>', ['coalesce', ['feature-state', 'ratio'], 0], 1],
              '#ff5233',
              FAINT_LINE,
            ],
            'line-width': [
              'case',
              ['>', ['coalesce', ['feature-state', 'ratio'], 0], 1],
              1.3,
              0.5,
            ],
          },
        })
        map.addLayer({
          id: `sec-hover-${band}`,
          type: 'fill',
          source: src,
          layout: { visibility: band === bandRef.current ? 'visible' : 'none' },
          filter: ['==', ['get', 'name'], '__none__'],
          paint: { 'fill-color': '#cfe0ff', 'fill-opacity': 0.06 },
        })
        map.addLayer({
          id: `sec-sel-${band}`,
          type: 'line',
          source: src,
          layout: { visibility: band === bandRef.current ? 'visible' : 'none' },
          filter: ['==', ['get', 'name'], '__none__'],
          paint: { 'line-color': '#ffb000', 'line-width': 1.6, 'line-opacity': 0.95 },
        })
      }

      // --- selected flight route ---
      map.addSource('sel-route', { type: 'geojson', data: emptyFC() })
      map.addLayer({
        id: 'sel-route-line',
        type: 'line',
        source: 'sel-route',
        paint: { 'line-color': '#ffb000', 'line-width': 1.4, 'line-opacity': 0.9, 'line-dasharray': [2, 1.5] },
      })

      // --- airports (circles colored + sized by busyness score) ---
      map.addSource('airports', {
        type: 'geojson',
        data: airportsFC(scenarioRef.current),
        promoteId: 'icao',
      })
      const score = ['coalesce', ['feature-state', 'score'], -1] as unknown as maplibregl.ExpressionSpecification
      map.addLayer({
        id: 'airport-dot',
        type: 'circle',
        source: 'airports',
        paint: {
          'circle-radius': [
            'interpolate', ['linear'], score,
            -1, ['case', ['get', 'core'], 4.5, 3],
            0, ['case', ['get', 'core'], 4.5, 3],
            60, 6.5,
            110, 9.5,
          ],
          // score < 0 means "not loaded yet" -> neutral dark fill
          'circle-color': [
            'interpolate', ['linear'], score,
            -1, '#0a0e14',
            1, '#59e6c3',
            40, '#8fd66b',
            65, '#ffb000',
            90, '#ff8a3d',
            110, '#ff5233',
          ],
          'circle-stroke-color': ['case', ['get', 'core'], '#eaf1fb', '#7d8aa0'],
          'circle-stroke-width': ['case', ['get', 'core'], 1.6, 1],
        },
      })
      map.addLayer({
        id: 'airport-sel',
        type: 'circle',
        source: 'airports',
        filter: ['==', ['get', 'icao'], '__none__'],
        paint: {
          'circle-radius': 9,
          'circle-color': 'rgba(255,176,0,0)',
          'circle-stroke-color': '#ffb000',
          'circle-stroke-width': 1.6,
        },
      })
      map.addLayer({
        id: 'airport-label',
        type: 'symbol',
        source: 'airports',
        layout: {
          'text-field': ['get', 'icao'],
          'text-font': ['Noto Sans Regular'],
          'text-size': ['case', ['get', 'core'], 12, 10],
          'text-offset': [0, -1.2],
          'text-letter-spacing': 0.12,
          'text-anchor': 'bottom',
        },
        paint: {
          'text-color': ['case', ['get', 'core'], '#eaf1fb', '#9aa6ba'],
          'text-halo-color': '#04060a',
          'text-halo-width': 1.6,
        },
      })

      // --- matrix capture for the WebGPU overlay ---
      map.addLayer({
        id: 'flight-capture',
        type: 'custom',
        renderingMode: '2d',
        onAdd() {},
        render(_gl: WebGLRenderingContext, args: any) {
          const m = args?.defaultProjectionData?.mainMatrix
          if (!m) return
          if (!matrixRef.current) matrixRef.current = new Float32Array(16)
          matrixRef.current.set(m)
        },
      } as maplibregl.CustomLayerInterface)
    })

    // hover highlight on the active band
    map.on('mousemove', (e) => {
      const layer = `sec-fill-${bandRef.current}`
      if (!map.getLayer(layer)) return
      const f = map.queryRenderedFeatures(e.point, { layers: [layer] })[0]
      const name = (f?.properties as any)?.name ?? '__none__'
      map.setFilter(`sec-hover-${bandRef.current}`, ['==', ['get', 'name'], name])
      map.getCanvas().style.cursor = f ? 'crosshair' : ''
    })

    // unified click selection: nearest aircraft, then airport, then sector
    map.on('click', (e) => {
      const pick = pickFlight(e.point.x, e.point.y)
      if (pick >= 0) {
        onSelect({ kind: 'flight', idx: pick })
        return
      }
      const ap = map.queryRenderedFeatures(e.point, { layers: ['airport-dot'] })[0]
      if (ap) {
        onSelect({ kind: 'airport', icao: (ap.properties as any).icao })
        return
      }
      const layer = `sec-fill-${bandRef.current}`
      const sec = map.getLayer(layer) ? map.queryRenderedFeatures(e.point, { layers: [layer] })[0] : null
      if (sec) {
        onSelect({ kind: 'sector', name: (sec.properties as any).name })
        return
      }
      onSelect(null)
    })

    // --- overlay renderer + render loop ---
    let raf = 0
    let disposed = false
    const scratch: FlightSample = { active: false, x: 0, y: 0, dx: 0, dy: 1, progress: 0 }

    createFlightRenderer(overlayRef.current!)
      .then((r) => {
        if (disposed) {
          r.destroy()
          return
        }
        rendererRef.current = r
        onBackend(r.backend)
        syncSize()
        loop()
      })
      .catch((err) => console.error('[flight-renderer] failed to initialize', err))

    function loop() {
      raf = requestAnimationFrame(loop)
      const now = performance.now()
      fpsTracker.record(now)
      simClock.advance(now)
      const r = rendererRef.current
      const m = matrixRef.current
      if (!r || !m) return

      const s = scenarioRef.current
      const flights = s.flights
      const need = flights.length * INSTANCE_FLOATS
      if (instancesRef.current.length < need) instancesRef.current = new Float32Array(need)
      const inst = instancesRef.current

      const t = simClock.t
      const b = bucketAt(s, t)
      const over = new Set<string>()
      for (const a of s.airports) if (rollingHour(a.arrivalBuckets, b) > a.capacity) over.add(a.icao)

      const sel = selectionRef.current
      const selIdx = sel?.kind === 'flight' ? sel.idx : -1
      const core = s.coreIcaos
      const metro = s.metroIcaos

      let count = 0
      for (let i = 0; i < flights.length; i++) {
        const f = flights[i]
        sampleFlight(f, t, scratch)
        if (!scratch.active) continue
        let cat: number
        if (f.idx === selIdx) cat = 3
        else if (over.has(f.dest)) cat = 4
        else if (core.includes(f.dest)) cat = 0
        else if (metro.includes(f.dest)) cat = 1
        else cat = 2
        const size = cat === 3 ? 15 : cat === 4 ? 11 : cat === 0 ? 10 : 8.5
        const o = count * INSTANCE_FLOATS
        inst[o] = scratch.x
        inst[o + 1] = scratch.y
        inst[o + 2] = scratch.dx
        inst[o + 3] = scratch.dy
        inst[o + 4] = cat
        inst[o + 5] = size
        count++
      }
      r.frame({ matrix: m, instances: inst, count, timeSec: now / 1000 })
    }

    function pickFlight(px: number, py: number): number {
      const m = matrixRef.current
      if (!m) return -1
      const { w, h } = sizeRef.current
      const s = scenarioRef.current
      const t = simClock.t
      const scratch2: FlightSample = { active: false, x: 0, y: 0, dx: 0, dy: 1, progress: 0 }
      let best = -1
      let bestD = 12 * 12
      for (const f of s.flights) {
        sampleFlight(f, t, scratch2)
        if (!scratch2.active) continue
        const cx = m[0] * scratch2.x + m[4] * scratch2.y + m[12]
        const cw = m[3] * scratch2.x + m[7] * scratch2.y + m[15]
        if (cw <= 0) continue
        const cy = m[1] * scratch2.x + m[5] * scratch2.y + m[13]
        const sx = (cx / cw * 0.5 + 0.5) * w
        const sy = (1 - (cy / cw * 0.5 + 0.5)) * h
        const dx = sx - px
        const dy = sy - py
        const d = dx * dx + dy * dy
        if (d < bestD) {
          bestD = d
          best = f.idx
        }
      }
      return best
    }

    function syncSize() {
      const el = containerRef.current
      const r = rendererRef.current
      if (!el || !r) return
      const w = el.clientWidth
      const h = el.clientHeight
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      sizeRef.current = { w, h }
      r.resize(w, h, dpr)
    }

    const ro = new ResizeObserver(() => {
      map.resize()
      syncSize()
    })
    ro.observe(containerRef.current)

    return () => {
      disposed = true
      cancelAnimationFrame(raf)
      ro.disconnect()
      rendererRef.current?.destroy()
      rendererRef.current = null
      map.remove()
      mapRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // --- airports source follows the scenario (day) ----------------------------
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const apply = () => {
      const src = map.getSource('airports') as maplibregl.GeoJSONSource | undefined
      if (src) src.setData(airportsFC(scenario))
    }
    if (map.isStyleLoaded()) apply()
    else map.once('idle', apply)
  }, [scenario])

  // --- band visibility toggle ------------------------------------------------
  useEffect(() => {
    const map = mapRef.current
    if (!map || !map.isStyleLoaded()) return
    for (const band of BANDS) {
      const vis = band === sectorBand ? 'visible' : 'none'
      for (const kind of ['fill', 'line', 'hover', 'sel']) {
        const id = `sec-${kind}-${band}`
        if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', vis)
      }
    }
  }, [sectorBand])

  // --- population choropleth via feature-state -------------------------------
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const apply = () => {
      const src = `sec-${sectorBand}`
      if (!map.getSource(src)) return
      map.removeFeatureState({ source: src })
      if (population) {
        for (const row of population) {
          map.setFeatureState({ source: src, id: row.name }, { ratio: row.ratio, count: row.count })
        }
      }
    }
    if (map.isStyleLoaded()) apply()
    else map.once('idle', apply)
  }, [population, sectorBand])

  // --- color airport circles by busyness score (baseline / optimized) --------
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const apply = () => {
      if (!map.getSource('airports')) return
      map.removeFeatureState({ source: 'airports' })
      if (airportScores) {
        for (const [icao, score] of Object.entries(airportScores)) {
          map.setFeatureState({ source: 'airports', id: icao }, { score })
        }
      }
    }
    if (map.isStyleLoaded()) apply()
    else map.once('idle', apply)
  }, [airportScores])

  // --- reflect selection on the map ------------------------------------------
  useEffect(() => {
    const map = mapRef.current
    if (!map || !map.isStyleLoaded()) return
    const secName = selection?.kind === 'sector' ? selection.name : '__none__'
    const apIcao = selection?.kind === 'airport' ? selection.icao : '__none__'
    for (const band of BANDS) {
      const id = `sec-sel-${band}`
      if (map.getLayer(id)) map.setFilter(id, ['==', ['get', 'name'], secName])
    }
    if (map.getLayer('airport-sel')) map.setFilter('airport-sel', ['==', ['get', 'icao'], apIcao])

    const route = map.getSource('sel-route') as maplibregl.GeoJSONSource | undefined
    if (route) {
      if (selection?.kind === 'flight') {
        const f = scenario.flights[selection.idx]
        const coords: [number, number][] = []
        for (let i = 0; i < f.mx.length; i++) coords.push(mercatorToLngLat(f.mx[i], f.my[i]))
        route.setData({
          type: 'FeatureCollection',
          features: [{ type: 'Feature', geometry: { type: 'LineString', coordinates: coords }, properties: {} }],
        })
      } else {
        route.setData(emptyFC())
      }
    }
  }, [selection, scenario])

  // --- fly the camera to a selected airport ----------------------------------
  // Picking an airport (from the load board on the left, or a dot on the map)
  // centers it. Read the scenario off the ref so switching days — which clears
  // the selection — doesn't trigger a stray flight to the previous airport.
  useEffect(() => {
    const map = mapRef.current
    if (!map || selection?.kind !== 'airport') return
    const ap = scenarioRef.current.airportByIcao.get(selection.icao)
    if (!ap) return
    map.flyTo({
      center: [ap.lng, ap.lat],
      zoom: Math.max(map.getZoom(), 9), // zoom in to focus, but never zoom back out
      duration: 900,
      essential: true,
    })
  }, [selection])

  return (
    <div className="map-wrap">
      <div ref={containerRef} className="map-canvas" />
      <canvas ref={overlayRef} className="flight-overlay" />
    </div>
  )
}

function emptyFC(): GeoJSON.FeatureCollection {
  return { type: 'FeatureCollection', features: [] }
}

function airportsFC(s: Scenario): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: s.airports.map((a) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [a.lng, a.lat] },
      properties: { icao: a.icao, core: a.isCore, arrivals: a.arrivalsTotal },
    })),
  }
}
