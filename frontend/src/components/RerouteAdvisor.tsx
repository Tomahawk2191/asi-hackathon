import { useState } from 'react'
import { useRecommendation } from '../hooks/useFlights'
import type { AirportLoad, RecommendRequest } from '../api/types'

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

// All airports in each metro, in display order.
const METRO_AIRPORTS: Record<string, string[]> = {
  nyc: ['KJFK', 'KLGA', 'KEWR'],
  lax: ['KLAX', 'KBUR', 'KLGB', 'KONT', 'KSNA'],
  sfba: ['KSFO', 'KOAK', 'KSJC'],
  chicago: ['KORD', 'KMDW'],
  dallas: ['KDFW', 'KDAL'],
  miami: ['KMIA', 'KFLL'],
  atlanta: ['KATL'],
  denver: ['KDEN'],
  boston: ['KBOS'],
  phoenix: ['KPHX'],
  seattle: ['KSEA'],
}

const ALL_METROS = Object.keys(METRO_AIRPORTS)

type DayEntry = {
  label: string
  value: string
  defaultUtc: string
  hasTracks: boolean
  metros: string[]
  defaultAirport: string
}

// hasTracks = true → matching ASI scenario on map (live flight animation)
// hasTracks = false → BTS historical data only; capacity analysis works, no map routes
const AVAILABLE_DAYS: DayEntry[] = [
  { label: 'Aug 21 2025  (summer peak)', value: '2025-08-21', defaultUtc: '19:50', hasTracks: true,  metros: ['nyc'],       defaultAirport: 'KLGA' },
  { label: 'Jan 13 2026',                value: '2026-01-13', defaultUtc: '20:00', hasTracks: true,  metros: ['nyc'],       defaultAirport: 'KLGA' },
  { label: 'Mar 04 2026',                value: '2026-03-04', defaultUtc: '20:00', hasTracks: true,  metros: ['nyc'],       defaultAirport: 'KLGA' },
  { label: 'Apr 08 2026',                value: '2026-04-08', defaultUtc: '20:00', hasTracks: true,  metros: ['nyc'],       defaultAirport: 'KLGA' },
  { label: 'Dec 25 2025  (Christmas)',   value: '2025-12-25', defaultUtc: '20:00', hasTracks: false, metros: ALL_METROS,   defaultAirport: 'KLGA' },
]

// Returns the metro peers of an airport (i.e. alternatives to route to).
// Returns [] if the airport is in a single-airport metro (no viable alternatives).
function metroAlternatives(airport: string, metros: string[]): string[] {
  for (const metro of metros) {
    const aps = METRO_AIRPORTS[metro] ?? []
    if (aps.includes(airport)) {
      return aps.filter((a) => a !== airport)
    }
  }
  return []
}

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
  const [airport, setAirport] = useState(defaultDay.defaultAirport)
  const [req, setReq] = useState<RecommendRequest | null>(null)

  const dayEntry = AVAILABLE_DAYS.find((d) => d.value === day) ?? AVAILABLE_DAYS[0]

  const { data, isLoading, isError } = useRecommendation(req)

  function handleCheck() {
    const iso = `${day}T${utcTime}:00Z`
    const alternatives = metroAlternatives(airport, dayEntry.metros)
    setReq({ airport, time: iso, day, alternatives })
  }

  function handleDayChange(v: string) {
    setDay(v)
    const entry = AVAILABLE_DAYS.find((d) => d.value === v) ?? AVAILABLE_DAYS[0]
    setUtcTime(entry.defaultUtc)
    // Reset to first airport in the first available metro for this day
    const firstAp = METRO_AIRPORTS[entry.metros[0]]?.[0] ?? entry.defaultAirport
    setAirport(firstAp)
    setReq(null)
  }

  function handleAirportChange(v: string) {
    setAirport(v)
    setReq(null)
  }

  const alternatives = metroAlternatives(airport, dayEntry.metros)
  const singleAirportMetro = alternatives.length === 0

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
          <div className="rr-day-badge" data-tracks={dayEntry.hasTracks}>
            {dayEntry.hasTracks ? '● LIVE TRACKS ON MAP' : '○ HISTORICAL DATA · NO MAP TRACKS'}
          </div>
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
          <select
            className="rr-select"
            value={airport}
            onChange={(e) => handleAirportChange(e.target.value)}
          >
            {dayEntry.metros.map((metro) => {
              const aps = METRO_AIRPORTS[metro]
              if (!aps) return null
              if (dayEntry.metros.length === 1) {
                // Single metro: flat list, no optgroup needed
                return aps.map((ap) => (
                  <option key={ap} value={ap}>{ap}</option>
                ))
              }
              return (
                <optgroup key={metro} label={METRO_LABEL[metro] ?? metro.toUpperCase()}>
                  {aps.map((ap) => (
                    <option key={ap} value={ap}>{ap}</option>
                  ))}
                </optgroup>
              )
            })}
          </select>
          {singleAirportMetro && (
            <div className="rr-day-badge" style={{ paddingTop: 3 }}>
              SOLE AIRPORT IN METRO — CAPACITY ONLY
            </div>
          )}
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
            <span className="rr-icao">{data.target.airport}</span>
            <CapBar load={data.target} />
          </div>

          {data.alternatives.length > 0 && (
            <>
              <div className="rr-section-label" style={{ marginTop: 10 }}>
                ALTERNATIVES
              </div>
              {data.alternatives.map((alt) => (
                <div
                  key={alt.airport}
                  className="rr-airport-row"
                  data-recommended={alt.airport === data.recommendation}
                >
                  <span className="rr-icao">{alt.airport}</span>
                  <CapBar load={alt} />
                  {alt.airport === data.recommendation && (
                    <span className="rr-badge">BEST</span>
                  )}
                </div>
              ))}
            </>
          )}

          {data.recommendation ? (
            <div className="rr-verdict rr-verdict--reroute">
              REROUTE TO {data.recommendation} ·{' '}
              {data.alternatives.find((a) => a.airport === data.recommendation)!.available_capacity}{' '}
              SLOTS AVAIL
            </div>
          ) : (
            <div className="rr-verdict rr-verdict--ok">
              {data.target.airport} HAS CAPACITY ·{' '}
              {data.target.available_capacity} SLOTS AVAIL
            </div>
          )}
        </div>
      )}
    </aside>
  )
}
