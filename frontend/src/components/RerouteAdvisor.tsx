import { useState } from 'react'
import { useRecommendation } from '../hooks/useFlights'
import type { AirportLoad, RecommendRequest } from '../api/types'

// Days available in the DB (ASI dataset + BTS Christmas 2025).
const AVAILABLE_DAYS = [
  { label: 'Aug 21 2025 (summer peak)', value: '2025-08-21', defaultUtc: '19:50' },
  { label: 'Dec 25 2025 (Christmas)', value: '2025-12-25', defaultUtc: '20:00' },
  { label: 'Jan 13 2026', value: '2026-01-13', defaultUtc: '20:00' },
  { label: 'Mar 04 2026', value: '2026-03-04', defaultUtc: '20:00' },
  { label: 'Apr 08 2026', value: '2026-04-08', defaultUtc: '20:00' },
]

const NYC_AIRPORTS = ['KJFK', 'KLGA', 'KEWR']

function CapBar({ load }: { load: AirportLoad }) {
  const pct = Math.min(1, load.utilization)
  const over = load.is_overloaded
  const warn = !over && load.utilization >= 0.95
  return (
    <div className="rr-cap-bar-wrap">
      <div className="rr-cap-bar-bg">
        <div
          className="rr-cap-bar-fill"
          style={{ width: `${pct * 100}%` }}
          data-over={over}
          data-warn={warn}
        />
        <div className="rr-cap-bar-line" />
      </div>
      <div className="rr-cap-nums">
        <span data-over={over} data-warn={warn}>
          {load.rolling_arrivals}/{load.aar}
        </span>
        <span className="rr-util">{(load.utilization * 100).toFixed(0)}%</span>
      </div>
    </div>
  )
}

export default function RerouteAdvisor() {
  const defaultDay = AVAILABLE_DAYS[0]
  const [day, setDay] = useState(defaultDay.value)
  const [utcTime, setUtcTime] = useState(defaultDay.defaultUtc)
  const [airport, setAirport] = useState('KLGA')
  const [req, setReq] = useState<RecommendRequest | null>(null)

  const dayEntry = AVAILABLE_DAYS.find((d) => d.value === day) ?? AVAILABLE_DAYS[0]

  const { data, isLoading, isError } = useRecommendation(req)

  function handleCheck() {
    const iso = `${day}T${utcTime}:00Z`
    setReq({ airport, time: iso, day })
  }

  function handleDayChange(v: string) {
    setDay(v)
    const entry = AVAILABLE_DAYS.find((d) => d.value === v) ?? AVAILABLE_DAYS[0]
    setUtcTime(entry.defaultUtc)
    setReq(null)
  }

  return (
    <aside className="rr-panel panel">
      <div className="panel-head">
        <span>REROUTE ADVISOR</span>
        <span className="panel-head-sub">DEMAND · AAR</span>
      </div>

      <div className="rr-form">
        <div className="rr-field">
          <label className="rr-label">DAY</label>
          <select
            className="rr-select"
            value={day}
            onChange={(e) => handleDayChange(e.target.value)}
          >
            {AVAILABLE_DAYS.map((d) => (
              <option key={d.value} value={d.value}>
                {d.label}
              </option>
            ))}
          </select>
        </div>

        <div className="rr-field">
          <label className="rr-label">ARRIVAL UTC</label>
          <input
            type="time"
            className="rr-input"
            value={utcTime}
            onChange={(e) => setUtcTime(e.target.value)}
          />
        </div>

        <div className="rr-field">
          <label className="rr-label">AIRPORT</label>
          <div className="seg">
            {NYC_AIRPORTS.map((ap) => (
              <button
                key={ap}
                className="seg-btn"
                data-active={airport === ap}
                onClick={() => setAirport(ap)}
              >
                {ap.slice(1)}
              </button>
            ))}
          </div>
        </div>

        <button className="rr-check-btn" onClick={handleCheck}>
          {isLoading ? 'CHECKING…' : 'CHECK CAPACITY'}
        </button>
      </div>

      {isError && (
        <div className="rr-error">No data for {dayEntry.label}. Seed the DB first.</div>
      )}

      {data && (
        <div className="rr-results">
          <div className="rr-section-label">TARGET</div>
          <div className="rr-airport-row" data-recommended={false}>
            <span className="rr-icao">{data.target.airport.slice(1)}</span>
            <CapBar load={data.target} />
          </div>

          <div className="rr-section-label" style={{ marginTop: 10 }}>
            ALTERNATIVES
          </div>
          {data.alternatives.map((alt) => (
            <div
              key={alt.airport}
              className="rr-airport-row"
              data-recommended={alt.airport === data.recommendation}
            >
              <span className="rr-icao">{alt.airport.slice(1)}</span>
              <CapBar load={alt} />
              {alt.airport === data.recommendation && (
                <span className="rr-badge">BEST</span>
              )}
            </div>
          ))}

          {data.recommendation ? (
            <div className="rr-verdict rr-verdict--reroute">
              REROUTE TO {data.recommendation.slice(1)} ·{' '}
              {data.alternatives.find((a) => a.airport === data.recommendation)!.available_capacity}{' '}
              SLOTS AVAIL
            </div>
          ) : (
            <div className="rr-verdict rr-verdict--ok">
              {data.target.airport.slice(1)} HAS CAPACITY ·{' '}
              {data.target.available_capacity} SLOTS AVAIL
            </div>
          )}
        </div>
      )}
    </aside>
  )
}
