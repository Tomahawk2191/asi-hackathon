// A tiny imperative simulation clock shared between the WebGPU render loop and
// the React UI. The render loop is the single driver: it calls `advance()` once
// per animation frame. React reads the time through `useClock`, which samples
// at a throttled rate so panels update smoothly without re-rendering at 120fps.

export interface ClockState {
  t: number // current sim time, epoch ms
  start: number
  end: number
  playing: boolean
  speed: number // sim-seconds per real-second
}

type Listener = () => void

class SimClock {
  start = 0
  end = 1
  t = 0
  playing = true
  speed = 180
  private listeners = new Set<Listener>()
  private lastNow: number | null = null

  setWindow(start: number, end: number) {
    this.start = start
    this.end = end
    if (this.t < start || this.t > end) this.t = start
    this.emit()
  }

  // Called once per render frame with the high-res timestamp.
  advance(nowMs: number) {
    if (this.lastNow == null) {
      this.lastNow = nowMs
      return
    }
    const dt = (nowMs - this.lastNow) / 1000
    this.lastNow = nowMs
    if (!this.playing) return
    this.t += dt * this.speed * 1000
    if (this.t >= this.end) this.t = this.start + ((this.t - this.start) % (this.end - this.start))
  }

  setPlaying(p: boolean) {
    this.playing = p
    this.emit()
  }
  toggle() {
    this.setPlaying(!this.playing)
  }
  setSpeed(s: number) {
    this.speed = s
    this.emit()
  }
  seek(t: number) {
    this.t = Math.min(this.end, Math.max(this.start, t))
    this.emit()
  }
  // 0..1 progress through the window
  setProgress(p: number) {
    this.seek(this.start + p * (this.end - this.start))
  }
  progress(): number {
    return this.end > this.start ? (this.t - this.start) / (this.end - this.start) : 0
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn)
    return () => this.listeners.delete(fn)
  }
  private emit() {
    this.listeners.forEach((l) => l())
  }
}

export const simClock = new SimClock()
