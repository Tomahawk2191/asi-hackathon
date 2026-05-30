import { useClock } from '../hooks/useClock'
import { airportLoads, bucketAt } from '../lib/analysis'
import type { Scenario, Selection } from '../lib/types'

interface Props {
  scenario: Scenario
  selection: Selection
  onSelect: (s: Selection) => void
}

// Mini arrivals-per-5min sparkline with a playhead at the current bucket.
function Sparkline({ buckets, cur }: { buckets: Int32Array; cur: number }) {
  const n = buckets.length
  let max = 1
  for (let i = 0; i < n; i++) if (buckets[i] > max) max = buckets[i]
  const W = 132
  const H = 22
  const pts: string[] = []
  for (let i = 0; i < n; i++) {
    const x = (i / (n - 1)) * W
    const y = H - (buckets[i] / max) * H
    pts.push(`${x.toFixed(1)},${y.toFixed(1)}`)
  }
  const px = (cur / (n - 1)) * W
  return (
    <svg className="spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
      <polyline points={pts.join(' ')} className="spark-line" />
      <line x1={px} y1={0} x2={px} y2={H} className="spark-head" />
    </svg>
  )
}

export default function LoadBoard({ scenario, selection, onSelect }: Props) {
  const clock = useClock()
  const loads = airportLoads(scenario, clock.t)
  const cur = bucketAt(scenario, clock.t)
  const selIcao = selection?.kind === 'airport' ? selection.icao : null

  return (
    <aside className="loadboard panel">
      <div className="panel-head">
        <span>AIRPORT LOAD</span>
        <span className="panel-head-sub">ARR / 60MIN · CAP</span>
      </div>
      <div className="load-rows">
        {loads.map((l) => {
          const ap = scenario.airportByIcao.get(l.icao)!
          const pct = Math.min(1, l.ratio)
          return (
            <button
              key={l.icao}
              className="load-row"
              data-over={l.over}
              data-sel={l.icao === selIcao}
              data-core={ap.isCore}
              onClick={() => onSelect({ kind: 'airport', icao: l.icao })}
            >
              <div className="load-row-top">
                <span className="load-icao">{l.icao}</span>
                <span className="load-count">
                  {l.rolling}
                  <span className="load-cap">/{l.capacity}</span>
                </span>
              </div>
              <div className="load-bar">
                <div
                  className="load-bar-fill"
                  style={{ width: `${pct * 100}%` }}
                  data-over={l.over}
                />
                <div className="load-bar-cap" />
              </div>
              <Sparkline buckets={ap.arrivalBuckets} cur={cur} />
            </button>
          )
        })}
      </div>
    </aside>
  )
}
