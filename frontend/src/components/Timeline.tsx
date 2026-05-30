import { useRef } from 'react'
import { useClock } from '../hooks/useClock'
import { simClock } from '../lib/simClock'
import { fmtClock } from '../lib/analysis'

interface Props {
  buckets?: Int32Array // optional arrivals-per-bucket histogram (snapshot days)
  bucketMs?: number
}

export default function Timeline({ buckets, bucketMs }: Props) {
  const clock = useClock(20)
  const trackRef = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)

  const n = buckets?.length ?? 0
  let max = 1
  if (buckets) for (let i = 0; i < n; i++) if (buckets[i] > max) max = buckets[i]
  // current bucket from the clock window (works with or without a histogram)
  const span = clock.end - clock.start
  const cur = bucketMs && span > 0 ? Math.floor((clock.t - clock.start) / bucketMs) : -1

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
          {fmtClock(clock.start)} → {fmtClock(clock.end)}
        </span>
        <span className="tl-label">{buckets ? `ARR / 5MIN · PEAK ${max}` : 'SCRUB TIME'}</span>
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
        {buckets && (
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
        )}
        <div className="tl-playhead" style={{ left: `${clock.progress * 100}%` }} />
      </div>
    </footer>
  )
}
