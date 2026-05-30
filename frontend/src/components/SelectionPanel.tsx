import { useClock } from '../hooks/useClock'
import { useLandings } from '../hooks/useFlights'
import { sampleFlight } from '../lib/flightModel'
import { airportLoads, fmtClock } from '../lib/analysis'
import type { LandingsResponse } from '../api/types'
import type { Scenario, SectorFeature, Selection } from '../lib/types'

interface Props {
  scenario: Scenario
  sectors: SectorFeature[]
  scenarioId: string | null
  selection: Selection
  onSelect: (s: Selection) => void
}

export default function SelectionPanel({
  scenario,
  sectors,
  scenarioId,
  selection,
  onSelect,
}: Props) {
  const clock = useClock()

  // Live /landings query — dormant unless a sector is selected. Hooks run
  // unconditionally (before any early return).
  const sectorName = selection?.kind === 'sector' ? selection.name : null
  const landingsQ = useLandings(
    sectorName && scenarioId ? { sector_names: [sectorName], scenario: scenarioId } : null,
  )

  if (!selection) return <LegendPanel />

  if (selection.kind === 'flight') {
    const f = scenario.flights[selection.idx]
    const s = sampleFlight(f, clock.t)
    const prog = Math.max(0, Math.min(1, s.progress))
    return (
      <Panel title="FLIGHT" id={f.number} onClose={() => onSelect(null)}>
        <Row k="ROUTE" v={`${f.origin} → ${f.dest}`} />
        <Row k="STATUS" v={s.active ? phase(prog) : prog < 0 ? 'SCHEDULED' : 'ARRIVED'} accent={s.active} />
        <Row k="DEPART" v={fmtClock(f.t0)} />
        <Row k="ARRIVE" v={fmtClock(f.t1)} />
        <Row k="CRUISE ALT" v={`${f.cruiseAltFt.toLocaleString()} ft`} />
        <Row k="CRUISE SPD" v={`${f.cruiseSpeedKt} kt`} />
        <div className="prog">
          <div className="prog-bar" style={{ width: `${prog * 100}%` }} />
        </div>
        <div className="prog-label">{(prog * 100).toFixed(0)}% COMPLETE</div>
      </Panel>
    )
  }

  if (selection.kind === 'airport') {
    const a = scenario.airportByIcao.get(selection.icao)
    if (!a) return <LegendPanel />
    const load = airportLoads(scenario, clock.t).find((l) => l.icao === a.icao)!
    let peak = 0
    let peakIdx = 0
    a.arrivalBuckets.forEach((v, i) => {
      if (v > peak) {
        peak = v
        peakIdx = i
      }
    })
    const peakT = scenario.windowStart + peakIdx * scenario.bucketMs
    return (
      <Panel title={a.isCore ? 'CORE AIRPORT' : 'METRO AIRPORT'} id={a.icao} onClose={() => onSelect(null)}>
        <Row k="ARRIVALS / DAY" v={`${a.arrivalsTotal}`} />
        <Row k="NOW / 60MIN" v={`${load.rolling} / ${a.capacity}`} accent={load.over} />
        <Row k="LOAD" v={`${(load.ratio * 100).toFixed(0)}%`} accent={load.over} />
        <Row k="PEAK BANK" v={`${peak} @ ${fmtClock(peakT)}`} />
        <div className="prog">
          <div className="prog-bar" style={{ width: `${Math.min(1, load.ratio) * 100}%` }} data-over={load.over} />
        </div>
        <div className="prog-label" data-over={load.over}>
          {load.over ? 'OVER CAPACITY' : 'WITHIN CAPACITY'}
        </div>
      </Panel>
    )
  }

  // sector — landings come live from the backend /landings endpoint
  const sec = sectors.find((s) => s.name === selection.name)
  return (
    <SectorPanel
      sec={sec}
      data={landingsQ.data}
      loading={landingsQ.isFetching}
      error={!!landingsQ.error}
      onSelect={onSelect}
    />
  )
}

function SectorPanel({
  sec,
  data,
  loading,
  error,
  onSelect,
}: {
  sec: SectorFeature | undefined
  data: LandingsResponse | undefined
  loading: boolean
  error: boolean
  onSelect: (s: Selection) => void
}) {
  if (!sec) return <LegendPanel />
  const perAirport = data
    ? Object.entries(data.per_airport).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    : []
  const maxC = perAirport.length ? perAirport[0][1] : 1
  return (
    <Panel title="SECTOR" id={sec.name} onClose={() => onSelect(null)}>
      <Row k="BAND" v={`${sec.altFrom.toLocaleString()}–${sec.altTo.toLocaleString()} ft`} />
      <Row k="CAPACITY" v={`${sec.capacity}`} />
      <Row k="LANDINGS" v={`${data?.total_flights ?? '—'}`} accent={(data?.total_flights ?? 0) > 0} />
      <div className="panel-subhead">PER AIRPORT · GET /landings</div>
      {error ? (
        <div className="empty">/landings REQUEST FAILED</div>
      ) : loading && !data ? (
        <div className="empty">QUERYING /landings…</div>
      ) : perAirport.length ? (
        <div className="bars">
          {perAirport.map(([icao, n]) => (
            <div key={icao} className="bar-row" onClick={() => onSelect({ kind: 'airport', icao })}>
              <span className="bar-icao">{icao}</span>
              <div className="bar-track">
                <div className="bar-fill" style={{ width: `${(n / maxC) * 100}%` }} />
              </div>
              <span className="bar-num">{n}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="empty">NO LANDINGS IN THIS SECTOR</div>
      )}
    </Panel>
  )
}

function phase(p: number): string {
  if (p < 0.12) return 'CLIMB'
  if (p > 0.82) return 'DESCENT'
  return 'CRUISE'
}

function Panel({
  title,
  id,
  onClose,
  children,
}: {
  title: string
  id: string
  onClose: () => void
  children: React.ReactNode
}) {
  return (
    <aside className="selpanel panel">
      <div className="panel-head">
        <span>{title}</span>
        <button className="x" onClick={onClose}>
          ✕
        </button>
      </div>
      <div className="sel-id">{id}</div>
      <div className="sel-body">{children}</div>
    </aside>
  )
}

function Row({ k, v, accent }: { k: string; v: string; accent?: boolean }) {
  return (
    <div className="krow">
      <span className="krow-k">{k}</span>
      <span className="krow-v" data-accent={!!accent}>
        {v}
      </span>
    </div>
  )
}

function LegendPanel() {
  return (
    <aside className="selpanel panel">
      <div className="panel-head">
        <span>LEGEND</span>
      </div>
      <div className="sel-body">
        <div className="legend-row">
          <i className="dot core" /> CORE ARRIVAL · KJFK / KLGA / KEWR
        </div>
        <div className="legend-row">
          <i className="dot metro" /> METRO ARRIVAL · RELIEVER FIELDS
        </div>
        <div className="legend-row">
          <i className="dot dep" /> DEPARTURE / TRANSIT
        </div>
        <div className="legend-row">
          <i className="dot alert" /> INBOUND TO OVER-CAPACITY FIELD
        </div>
        <div className="legend-hint">
          SELECT AN AIRCRAFT, AIRPORT, OR SECTOR ON THE MAP. SECTORS REPORT LANDINGS PER AIRPORT — A LIVE
          REPLICA OF THE /landings ENDPOINT.
        </div>
      </div>
    </aside>
  )
}
