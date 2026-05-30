import { useEffect, useState } from 'react'
import { useClock } from '../hooks/useClock'
import { simClock } from '../lib/simClock'
import { fpsTracker } from '../lib/fps'
import { countActive, fmtClock } from '../lib/analysis'
import type { Scenario } from '../lib/types'

const SPEEDS = [1, 60, 180, 600]

interface Props {
  scenarios: string[]
  date: string
  onSelectDay: (date: string) => void
  scenario: Scenario | null
  backend: 'webgpu' | 'canvas2d' | null
  loading?: boolean
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

export default function TopBar({ scenarios, date, onSelectDay, scenario, backend, loading }: Props) {
  const clock = useClock()
  const active = scenario ? countActive(scenario, clock.t) : 0

  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark">ASI</span>
        <span className="brand-name">AIRPORT LOAD</span>
        <span className="brand-sub">/ NYC METRO · ARRIVAL DEMAND</span>
      </div>

      <div className="topbar-controls">
        <div className="seg">
          {scenarios.map((d) => (
            <button
              key={d}
              className="seg-btn"
              data-active={d === date}
              onClick={() => onSelectDay(d)}
            >
              {d}
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
          <span className="hud-sub">{date}</span>
        </div>
        <div className="hud-stat">
          <span className="hud-label">AIRBORNE</span>
          <span className="hud-val">{active}</span>
          <span className="hud-sub">tracks</span>
        </div>
        <Fps />
        <div className="hud-stat">
          <span className="hud-label">RENDER</span>
          <span className="hud-val" data-good={backend === 'webgpu'}>
            {backend === 'webgpu' ? 'WebGPU' : backend === 'canvas2d' ? 'Canvas2D' : '…'}
          </span>
          <span className="hud-sub">{backend === 'webgpu' ? 'MSAA·4' : 'fallback'}</span>
        </div>
        <div className="hud-stat">
          <span className="hud-label">API LINK</span>
          <span className="hud-val" data-good={!loading}>
            {loading ? 'SYNC' : 'LIVE'}
          </span>
          <span className="hud-sub">:8000</span>
        </div>
      </div>
    </header>
  )
}
