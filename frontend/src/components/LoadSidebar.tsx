// Airport load board (demand-based). For the selected day + time, shows each
// airport's rolling-60-min arrival demand vs its capacity (AAR) as a
// utilization bar, alongside what our balancing algorithm would make it —
// baseline → optimized — grouped by metro. Works for every day, and for the
// multi-metro Christmas demand. Scope picks ALL metros or one.

import type { RebalanceResponse } from '../api/types'

const METRO_LABEL: Record<string, string> = {
  nyc: 'NEW YORK',
  lax: 'LOS ANGELES',
  sfba: 'SF BAY AREA',
  chicago: 'CHICAGO',
  dallas: 'DALLAS',
  miami: 'MIAMI',
  atlanta: 'ATLANTA',
  denver: 'DENVER',
  boston: 'BOSTON',
  phoenix: 'PHOENIX',
  seattle: 'SEATTLE',
}

interface Props {
  data: RebalanceResponse | undefined
  loading: boolean
  scope: string
  metros: string[] // metros available this day (for the picker)
  onScope: (s: string) => void
  view: 'baseline' | 'optimized'
  onView: (v: 'baseline' | 'optimized') => void
}

// utilization (arrivals / AAR) -> color. <0.5 calm, ~0.85 busy, >1 over capacity.
function utilColor(u: number): string {
  if (u >= 1) return 'var(--alert)'
  if (u >= 0.85) return '#ff8a3d'
  if (u >= 0.6) return 'var(--accent)'
  if (u >= 0.35) return '#8fd66b'
  return 'var(--good)'
}

const pct = (u: number) => `${Math.round(u * 100)}%`

export default function LoadSidebar({ data, loading, scope, metros, onScope, view, onView }: Props) {
  const shown = data?.metros ?? []
  const peakBefore = Math.max(0, ...shown.map((m) => m.peak_before))
  const peakAfter = Math.max(0, ...shown.map((m) => m.peak_after))
  const totalMoved = shown.reduce((s, m) => s + m.moved, 0)

  return (
    <aside className="loadsb panel">
      <div className="panel-head">
        <span>AIRPORT LOAD</span>
        <span className="panel-head-sub">ARR·60M / AAR · BASE→OPT</span>
      </div>

      {/* scope picker */}
      <div className="loadsb-scope">
        <button className="seg-btn" data-active={scope === 'all'} onClick={() => onScope('all')}>
          ALL METROS
        </button>
        <select
          className="loadsb-select"
          value={scope === 'all' ? '' : scope}
          onChange={(e) => onScope(e.target.value || 'all')}
        >
          <option value="">FOCUS METRO…</option>
          {metros.map((m) => (
            <option key={m} value={m}>
              {METRO_LABEL[m] ?? m.toUpperCase()}
            </option>
          ))}
        </select>
      </div>

      <div className="loadsb-body">
        {!data && loading && <div className="empty">COMPUTING /rebalance…</div>}
        {!data && !loading && <div className="empty">NO LOAD DATA</div>}

        {data && (
          <>
            <div className="loadsb-headline">
              <div className="score-head-stat">
                <span className="score-head-lab">PEAK LOAD</span>
                <span className="score-head-val">
                  <b style={{ color: utilColor(peakBefore) }}>{pct(peakBefore)}</b>
                  <span className="score-arrow">→</span>
                  <b style={{ color: utilColor(peakAfter) }}>{pct(peakAfter)}</b>
                </span>
              </div>
              <div className="score-head-stat">
                <span className="score-head-lab">REROUTED</span>
                <span className="score-head-val">{totalMoved}</span>
              </div>
            </div>

            <div className="loadsb-metros">
              {shown.map((m) => (
                <div key={m.metro} className="loadsb-metro">
                  {shown.length > 1 && (
                    <div className="loadsb-metro-head">
                      <span>{METRO_LABEL[m.metro] ?? m.metro.toUpperCase()}</span>
                      <span className="loadsb-metro-peak">
                        {pct(m.peak_before)} → {pct(m.peak_after)}
                      </span>
                    </div>
                  )}
                  {m.airports.map((a) => {
                    const ub = a.util_before
                    const ua = a.util_after
                    const d = a.arrivals_after - a.arrivals_before
                    return (
                      <div key={a.airport} className="score-row">
                        <div className="score-row-top">
                          <span className="score-icao">{a.airport}</span>
                          <span className="score-vals">
                            <span style={{ color: utilColor(ub) }}>{pct(ub)}</span>
                            <span className="score-arrow">→</span>
                            <span style={{ color: utilColor(ua) }}>{pct(ua)}</span>
                            {d !== 0 && (
                              <span className="score-delta" data-down={d < 0} data-up={d > 0}>
                                {d > 0 ? `+${d}` : d}
                              </span>
                            )}
                          </span>
                        </div>
                        <div className="score-bars">
                          <div className="score-bar">
                            <div
                              className="score-bar-fill base"
                              style={{ width: `${Math.min(1, ub) * 100}%`, background: utilColor(ub) }}
                            />
                          </div>
                          <div className="score-bar">
                            <div
                              className="score-bar-fill"
                              style={{ width: `${Math.min(1, ua) * 100}%`, background: utilColor(ua) }}
                            />
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              ))}
            </div>

            <div className="score-toggle">
              <span className="score-toggle-lab">MAP CIRCLES</span>
              <div className="seg">
                {(['baseline', 'optimized'] as const).map((v) => (
                  <button key={v} className="seg-btn" data-active={v === view} onClick={() => onView(v)}>
                    {v === 'baseline' ? 'BASELINE' : 'OPTIMIZED'}
                  </button>
                ))}
              </div>
            </div>
          </>
        )}
      </div>
    </aside>
  )
}
