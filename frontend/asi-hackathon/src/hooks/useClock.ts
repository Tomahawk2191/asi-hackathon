// Samples the imperative simClock into React state at a throttled rate so
// panels (clock readout, load bars, timeline playhead) update smoothly without
// re-rendering on every animation frame. Also re-renders on explicit clock
// changes (play/pause/seek/speed) via the clock's subscription.

import { useEffect, useState } from 'react'
import { simClock } from '../lib/simClock'

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
