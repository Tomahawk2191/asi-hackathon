import { useRef } from 'react'
import { useClock } from '../hooks/useClock'
import { simClock } from '../lib/simClock'
import { bucketAt, fmtClock } from '../lib/analysis'
import type { Scenario } from '../lib/types'

interface Props {
  scenario: Scenario
}

export default function Timeline({ scenario }: Props) {
  const clock = useClock(20)
  const trackRef = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)

  const buckets = scenario.totalArrivalBuckets
  const n = buckets.length
  let max = 1
  for (let i = 0; i < n; i++) if (buckets[i] > max) max = buckets[i]
  const cur = bucketAt(scenario, clock.t)

  const seekTo = (clientX: number) => {
    const el = trackRef.current
    if (!el) return
    const r = el.getBoundingClientRect()
    const p = Math.min(1, Math.max(0, (clientX - r.left) / r.width))
    simClock.setProgress(p)
  }

  return (
    <footer className="timeline panel">
      <div className="timeline-meta">
        <span className="tl-label">DEMAND TIMELINE</span>
        <span className="tl-window">
          {fmtClock(scenario.windowStart)} → {fmtClock(scenario.windowEnd)}
        </span>
        <span className="tl-label">ARR / 5MIN · PEAK {max}</span>
      </div>
      <div
        ref={trackRef}
        className="tl-track"
        onPointerDown={(e) => {
          dragging.current = true
          ;(e.target as Element).setPointerCapture(e.pointerId)
          seekTo(e.clientX)
        }}
        onPointerMove={(e) => dragging.current && seekTo(e.clientX)}
        onPointerUp={() => (dragging.current = false)}
      >
        <div className="tl-bars">
          {Array.from({ length: n }, (_, i) => (
            <div
              key={i}
              className="tl-bar"
              data-cur={i === cur}
              style={{ height: `${(buckets[i] / max) * 100}%` }}
            />
          ))}
        </div>
        <div className="tl-playhead" style={{ left: `${clock.progress * 100}%` }} />
      </div>
    </footer>
  )
}
