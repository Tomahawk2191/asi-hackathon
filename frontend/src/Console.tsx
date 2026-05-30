import { useEffect, useMemo, useState } from 'react'
import FlightMap from './components/FlightMap'
import TopBar from './components/TopBar'
import LoadBoard from './components/LoadBoard'
import Timeline from './components/Timeline'
import SelectionPanel from './components/SelectionPanel'
import MapControls from './components/MapControls'
import RerouteAdvisor from './components/RerouteAdvisor'
import {
  useArrivals,
  useScenarios,
  useSnapshot,
  useSectorGeoJson,
  useSectorPopulation,
} from './hooks/useFlights'
import { useBucketTime } from './hooks/useClock'
import { deriveScenario, deriveScenarioFromDb, parseLowSectors } from './lib/data'
import { metroById, METROS, DEFAULT_METRO } from './lib/metros'
import { simClock } from './lib/simClock'
import type { Selection } from './lib/types'
import './console.css'

const PREFERRED = '2025-08-21' // summer convective day — heaviest traffic

export default function Console() {
  const [scenarioId, setScenarioId] = useState<string | null>(null)
  const [metroId, setMetroId] = useState(DEFAULT_METRO)
  const [selection, setSelection] = useState<Selection>(null)
  const [backend, setBackend] = useState<'webgpu' | 'canvas2d' | null>(null)
  const [band, setBand] = useState<'LOW' | 'HIGH'>('LOW')

  // Resolve the active metro once; it drives which data source we read from.
  const metro = useMemo(() => metroById(metroId), [metroId])

  // --- backend data via TanStack Query ---
  const scenariosQ = useScenarios()
  const snapshotQ = useSnapshot(scenarioId) // NYC: animated JSON tracks
  const arrivalsQ = useArrivals(metro.day ?? null, metro.source === 'db') // others: DB counts
  const sectorsLowQ = useSectorGeoJson('LOW')
  const sectorsHighQ = useSectorGeoJson('HIGH')
  const bucketTime = useBucketTime()
  const populationQ = useSectorPopulation(scenarioId, bucketTime, band)

  // pick the default scenario once the list arrives
  useEffect(() => {
    if (scenarioId || !scenariosQ.data) return
    const list = scenariosQ.data.scenarios
    const pick = list.includes(PREFERRED) ? PREFERRED : list[0] ?? scenariosQ.data.default
    if (pick) setScenarioId(pick)
  }, [scenariosQ.data, scenarioId])

  // derive render-ready structures off the render loop. NYC reads animated
  // tracks from the JSON snapshot; every other metro reads aggregated arrival
  // counts from the DB (no route geometry, so flights[] stays empty).
  const scenario = useMemo(() => {
    if (metro.source === 'db')
      return arrivalsQ.data ? deriveScenarioFromDb(arrivalsQ.data.rows, metro) : null
    return snapshotQ.data ? deriveScenario(snapshotQ.data, metro) : null
  }, [metro, snapshotQ.data, arrivalsQ.data])
  const lowSectors = useMemo(
    () => (sectorsLowQ.data ? parseLowSectors(sectorsLowQ.data) : []),
    [sectorsLowQ.data],
  )

  // sync the sim clock to each scenario's window
  useEffect(() => {
    if (!scenario) return
    simClock.setWindow(scenario.windowStart, scenario.windowEnd)
    simClock.seek(scenario.windowStart)
    setSelection(null)
  }, [scenario])

  const onSelectDay = (date: string) => {
    if (date !== scenarioId) setScenarioId(date)
  }

  const error = scenariosQ.error || snapshotQ.error || arrivalsQ.error || sectorsLowQ.error
  if (error) {
    return (
      <div className="boot boot-err">
        <div className="boot-mark">ASI · AIRPORT LOAD</div>
        <div className="boot-msg">BACKEND UNREACHABLE</div>
        <pre className="boot-detail">
          {String((error as Error).message ?? error)}
          {'\n\n'}Start the API: cd backend && ./venv/bin/python -m uvicorn main:app --port 8000
        </pre>
      </div>
    )
  }

  const ready = scenario && sectorsLowQ.data && sectorsHighQ.data
  const population = populationQ.data?.sectors ?? null
  // Loading/fetching reflects whichever source the active metro reads from.
  const scenarioLoading = metro.source === 'db' ? arrivalsQ.isLoading : snapshotQ.isLoading
  const scenarioFetching = metro.source === 'db' ? arrivalsQ.isFetching : snapshotQ.isFetching

  return (
    <div className="console">
      <TopBar
        scenarios={scenariosQ.data?.scenarios ?? []}
        date={scenarioId ?? ''}
        onSelectDay={onSelectDay}
        scenario={scenario}
        backend={backend}
        loading={scenarioFetching}
        metros={METROS}
        metroId={metroId}
        onSelectMetro={setMetroId}
      />

      <main className="stage">
        {ready ? (
          <FlightMap
            scenario={scenario}
            metro={metro}
            sectorsLow={sectorsLowQ.data}
            sectorsHigh={sectorsHighQ.data}
            sectorBand={band}
            population={population}
            selection={selection}
            onSelect={setSelection}
            onBackend={setBackend}
          />
        ) : (
          <div className="boot">
            <div className="boot-mark">ASI · AIRPORT LOAD</div>
            <div className="boot-msg">
              {scenarioLoading || scenariosQ.isLoading
                ? 'FETCHING TELEMETRY FROM /scenarios…'
                : 'INITIALIZING…'}
            </div>
          </div>
        )}

        {ready && (
          <>
            <MapControls
              band={band}
              onBand={setBand}
              occupied={populationQ.data?.occupied ?? null}
              total={populationQ.data?.total ?? null}
            />
            <LoadBoard scenario={scenario} selection={selection} onSelect={setSelection} />
            <SelectionPanel
              scenario={scenario}
              sectors={lowSectors}
              scenarioId={scenarioId}
              population={population}
              selection={selection}
              onSelect={setSelection}
            />
            <RerouteAdvisor />
          </>
        )}
      </main>

      {ready && <Timeline scenario={scenario} />}
    </div>
  )
}
