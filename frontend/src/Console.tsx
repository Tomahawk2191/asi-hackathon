import { useEffect, useMemo, useRef, useState } from 'react'
import FlightMap from './components/FlightMap'
import TopBar from './components/TopBar'
import Timeline from './components/Timeline'
import SelectionPanel from './components/SelectionPanel'
import MapControls from './components/MapControls'
import RerouteAdvisor from './components/RerouteAdvisor'
import LoadSidebar from './components/LoadSidebar'
import {
  useScenarios,
  useSnapshot,
  useSectorGeoJson,
  useSectorPopulation,
  useDemandDays,
  useRebalance,
} from './hooks/useFlights'
import { useBucketTime } from './hooks/useClock'
import { deriveScenario, parseLowSectors } from './lib/data'
import { simClock } from './lib/simClock'
import type { Selection } from './lib/types'
import './console.css'

const CHRISTMAS = '2025-12-25'
const DEFAULT_DAY = '2025-08-21' // start on a rich animated NYC day

export default function Console() {
  const [dayId, setDayId] = useState<string | null>(null)
  const [selection, setSelection] = useState<Selection>(null)
  const [band, setBand] = useState<'LOW' | 'HIGH'>('LOW')
  const [scope, setScope] = useState('all')
  const [view, setView] = useState<'baseline' | 'optimized'>('baseline')

  // --- backend data via TanStack Query ---
  const scenariosQ = useScenarios()
  const demandDaysQ = useDemandDays()
  const isSnapshot = !!(dayId && scenariosQ.data?.scenarios.includes(dayId))
  const snapshotQ = useSnapshot(isSnapshot ? dayId : null)
  const sectorsLowQ = useSectorGeoJson('LOW')
  const sectorsHighQ = useSectorGeoJson('HIGH')
  const bucketTime = useBucketTime()
  const populationQ = useSectorPopulation(isSnapshot ? dayId : null, bucketTime, band)
  const rebalanceQ = useRebalance(dayId, bucketTime, scope)

  // day tabs: the snapshot scenarios + a CHRISTMAS tab (demand-only multi-metro)
  const tabs = useMemo(() => {
    const t = (scenariosQ.data?.scenarios ?? []).map((d) => ({ id: d, label: d }))
    const days = demandDaysQ.data?.days?.map((d) => d.day) ?? []
    if (days.includes(CHRISTMAS) && !t.some((x) => x.id === CHRISTMAS)) {
      t.push({ id: CHRISTMAS, label: 'CHRISTMAS' })
    }
    return t
  }, [scenariosQ.data, demandDaysQ.data])

  // metros available for the current day (for the sidebar's focus picker)
  const dayMetros = useMemo(
    () => demandDaysQ.data?.days?.find((d) => d.day === dayId)?.metros ?? [],
    [demandDaysQ.data, dayId],
  )

  // pick a default day once the lists arrive
  useEffect(() => {
    if (dayId || !scenariosQ.data) return
    const list = scenariosQ.data.scenarios
    setDayId(list.includes(DEFAULT_DAY) ? DEFAULT_DAY : list[0] ?? scenariosQ.data.default)
  }, [scenariosQ.data, dayId])

  const scenario = useMemo(
    () => (snapshotQ.data ? deriveScenario(snapshotQ.data) : null),
    [snapshotQ.data],
  )
  const lowSectors = useMemo(
    () => (sectorsLowQ.data ? parseLowSectors(sectorsLowQ.data) : []),
    [sectorsLowQ.data],
  )

  // NYC airport ICAO -> utilization*100 for the active view, to color map circles.
  const airportScores = useMemo(() => {
    const nyc = rebalanceQ.data?.metros.find((m) => m.metro === 'nyc')
    if (!nyc) return null
    const key = view === 'baseline' ? 'util_before' : 'util_after'
    return Object.fromEntries(nyc.airports.map((a) => [a.airport, a[key] * 100])) as Record<string, number>
  }, [rebalanceQ.data, view])

  // sim clock window: snapshot window for live days, demand window otherwise.
  const windowStart = isSnapshot && scenario ? scenario.windowStart : rebalanceQ.data ? Date.parse(rebalanceQ.data.window.start) : null
  const windowEnd = isSnapshot && scenario ? scenario.windowEnd : rebalanceQ.data ? Date.parse(rebalanceQ.data.window.end) : null
  const lastWindow = useRef<string>('')
  useEffect(() => {
    if (windowStart == null || windowEnd == null) return
    const key = `${windowStart}-${windowEnd}`
    if (key === lastWindow.current) return // only reseek on an actual day/window change
    lastWindow.current = key
    simClock.setWindow(windowStart, windowEnd)
    simClock.seek(windowStart)
    setSelection(null)
  }, [windowStart, windowEnd])

  // reset focus scope when the day changes
  useEffect(() => {
    setScope('all')
  }, [dayId])

  const error = scenariosQ.error || snapshotQ.error || sectorsLowQ.error || rebalanceQ.error
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

  const mapReady = isSnapshot && scenario && sectorsLowQ.data && sectorsHighQ.data
  const hasDay = !!dayId
  const population = populationQ.data?.sectors ?? null

  return (
    <div className="console">
      <TopBar
        tabs={tabs}
        activeId={dayId ?? ''}
        onSelectDay={setDayId}
        scenario={scenario}
      />

      <main className="stage">
        {hasDay && (
          <aside className="rail">
            <LoadSidebar
              data={rebalanceQ.data}
              loading={rebalanceQ.isFetching}
              scope={scope}
              metros={dayMetros}
              onScope={setScope}
              view={view}
              onView={setView}
            />
            {isSnapshot && (
              <MapControls
                band={band}
                onBand={setBand}
                occupied={populationQ.data?.occupied ?? null}
                total={populationQ.data?.total ?? null}
              />
            )}
            <RerouteAdvisor />
          </aside>
        )}

        <div className="map-region">
          {mapReady ? (
            <FlightMap
              scenario={scenario}
              sectorsLow={sectorsLowQ.data}
              sectorsHigh={sectorsHighQ.data}
              sectorBand={band}
              population={population}
              airportScores={airportScores}
              selection={selection}
              onSelect={setSelection}
              onBackend={() => {}}
            />
          ) : !isSnapshot && hasDay ? (
            <DemandMode day={dayId} metros={dayMetros.length} />
          ) : (
            <div className="boot">
              <div className="boot-mark">ASI · AIRPORT LOAD</div>
              <div className="boot-msg">
                {scenariosQ.isLoading ? 'FETCHING TELEMETRY FROM /scenarios…' : 'INITIALIZING…'}
              </div>
            </div>
          )}

          {mapReady && (
            <SelectionPanel
              scenario={scenario}
              sectors={lowSectors}
              scenarioId={dayId}
              population={population}
              selection={selection}
              onSelect={setSelection}
            />
          )}
        </div>
      </main>

      {hasDay && windowStart != null && (
        <Timeline
          buckets={isSnapshot && scenario ? scenario.totalArrivalBuckets : undefined}
          bucketMs={scenario?.bucketMs}
        />
      )}
    </div>
  )
}

// Shown for demand-only days (e.g. Christmas) that have no flight-geometry
// snapshot — the load balancing happens in the sidebar.
function DemandMode({ day, metros }: { day: string; metros: number }) {
  return (
    <div className="boot demand-mode">
      <div className="boot-mark">DEMAND MODE · {day === CHRISTMAS ? 'CHRISTMAS 2025' : day}</div>
      <div className="demand-msg">
        {metros} METRO {metros === 1 ? 'AREA' : 'AREAS'} · {metros > 1 ? 'NATIONWIDE ARRIVAL DEMAND' : 'ARRIVAL DEMAND'}
      </div>
      <div className="demand-sub">
        No live flight tracks for this day — it's an arrivals-demand dataset.
        <br />
        Airport load balancing (baseline → optimized) is in the left sidebar; scrub time below.
      </div>
    </div>
  )
}
