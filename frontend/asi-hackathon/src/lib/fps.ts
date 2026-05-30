// Lightweight FPS + frame-time tracker. The render loop calls `record(now)`
// every frame; UI samples `fps` / `frameMs` at a low rate. Uses an exponential
// moving average so the readout is stable rather than jittery.

class FpsTracker {
  private last = 0
  fps = 0
  frameMs = 0

  record(now: number) {
    if (this.last === 0) {
      this.last = now
      return
    }
    const dt = now - this.last
    this.last = now
    if (dt <= 0) return
    const inst = 1000 / dt
    // EMA
    this.fps = this.fps === 0 ? inst : this.fps * 0.9 + inst * 0.1
    this.frameMs = this.frameMs === 0 ? dt : this.frameMs * 0.9 + dt * 0.1
  }
}

export const fpsTracker = new FpsTracker()
