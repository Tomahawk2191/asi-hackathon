// Samples the imperative simClock into React state at a throttled rate so
// panels (clock readout, load bars, timeline playhead) update smoothly without
// re-rendering on every animation frame. Also re-renders on explicit clock
// changes (play/pause/seek/speed) via the clock's subscription.

import { useEffect, useState } from 'react'
import { simClock } from '../lib/simClock'

// Returns the ISO timestamp of the current 5-minute bucket start, updating only
// when the sim clock crosses into a new bucket. Used to throttle the live
// sector-population query so it refetches per bucket, not per frame.
export function useBucketTime(bucketMs = 5 * 60 * 1000): string | null {
  const [iso, setIso] = useState<string | null>(null)
  useEffect(() => {
    let last = Number.NaN
    const tick = () => {
      if (!(simClock.end > simClock.start)) return
      const b = Math.floor((simClock.t - simClock.start) / bucketMs)
      if (b !== last) {
        last = b
        setIso(new Date(simClock.start + b * bucketMs).toISOString())
      }
    }
    tick()
    const id = window.setInterval(tick, 250)
    const unsub = simClock.subscribe(tick)
    return () => {
      window.clearInterval(id)
      unsub()
    }
  }, [bucketMs])
  return iso
}

export function useClock(sampleHz = 12) {
  const [, force] = useState(0)
  useEffect(() => {
    const unsub = simClock.subscribe(() => force((n) => n + 1))
    const id = window.setInterval(() => force((n) => n + 1), 1000 / sampleHz)
    return () => {
      unsub()
      window.clearInterval(id)
    }
  }, [sampleHz])
  return {
    t: simClock.t,
    playing: simClock.playing,
    speed: simClock.speed,
    start: simClock.start,
    end: simClock.end,
    progress: simClock.progress(),
  }
}
