import { useEffect, useState } from 'react'
import { useClock } from '../hooks/useClock'
import { simClock } from '../lib/simClock'
import { fpsTracker } from '../lib/fps'
import { countActive, fmtClock } from '../lib/analysis'
import type { Scenario } from '../lib/types'

const SPEEDS = [1, 60, 180, 600]

interface Tab {
  id: string
  label: string
}

interface Props {
  tabs: Tab[]
  activeId: string
  onSelectDay: (id: string) => void
  scenario: Scenario | null
}

function Fps() {
  const [v, setV] = useState({ fps: 0, ms: 0 })
  useEffect(() => {
    const id = setInterval(() => setV({ fps: fpsTracker.fps, ms: fpsTracker.frameMs }), 250)
    return () => clearInterval(id)
  }, [])
  const good = v.fps >= 110
  return (
    <div className="hud-stat">
      <span className="hud-label">FPS</span>
      <span className="hud-val" data-good={good}>
        {v.fps ? v.fps.toFixed(0) : '—'}
      </span>
      <span className="hud-sub">{v.ms ? v.ms.toFixed(1) : '—'}ms</span>
    </div>
  )
}

export default function TopBar({ tabs, activeId, onSelectDay, scenario }: Props) {
  const clock = useClock()
  const active = scenario ? countActive(scenario, clock.t) : null

  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark">ASI</span>
        <span className="brand-name">AIRPORT LOAD</span>
        <span className="brand-sub">/ MULTI-METRO · ARRIVAL DEMAND</span>
      </div>

      <div className="topbar-controls">
        <div className="seg">
          {tabs.map((t) => (
            <button
              key={t.id}
              className="seg-btn"
              data-active={t.id === activeId}
              data-feature={t.label === 'CHRISTMAS'}
              onClick={() => onSelectDay(t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>

        <div className="transport">
          <button className="play" onClick={() => simClock.toggle()}>
            {clock.playing ? '❚❚' : '▶'}
          </button>
          <div className="seg">
            {SPEEDS.map((s) => (
              <button
                key={s}
                className="seg-btn"
                data-active={clock.speed === s}
                onClick={() => simClock.setSpeed(s)}
              >
                {s}×
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="topbar-readout">
        <div className="hud-stat">
          <span className="hud-label">SIM CLOCK</span>
          <span className="hud-val mono-lg">{fmtClock(clock.t)}</span>
          <span className="hud-sub">{activeId}</span>
        </div>
        <div className="hud-stat">
          <span className="hud-label">AIRBORNE</span>
          <span className="hud-val">{active ?? '—'}</span>
          <span className="hud-sub">tracks</span>
        </div>
        <Fps />
      </div>
    </header>
  )
}
