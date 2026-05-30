// Canvas2D fallback for browsers without WebGPU. Same interface as the WebGPU
// renderer; projects mercator points through MapLibre's matrix on the CPU and
// draws plane silhouettes + short trails. Caps fidelity, not correctness.

import type { FrameInput, IFlightRenderer } from './FlightRenderer'
import { INSTANCE_FLOATS, WebGPUFlightRenderer } from './FlightRenderer'

const COLORS = [
  'rgb(243,248,255)', // core arrival
  'rgb(158,179,209)', // metro arrival
  'rgb(87,105,133)', // departure / transit
  'rgb(255,176,0)', // selected
  'rgb(255,87,56)', // alert
]

// plane silhouette outline (local units, +y forward), matching the WebGPU mesh
const PLANE_OUTLINE: [number, number][] = [
  [0, 1.5],
  [0.1, 0.42],
  [1.4, -0.4],
  [0.08, -0.1],
  [0.09, -0.95],
  [0.55, -1.36],
  [0.06, -1.26],
  [0.09, -1.3],
  [-0.09, -1.3],
  [-0.06, -1.26],
  [-0.55, -1.36],
  [-0.09, -0.95],
  [-0.08, -0.1],
  [-1.4, -0.4],
  [-0.1, 0.42],
]

export class Canvas2DFlightRenderer implements IFlightRenderer {
  readonly backend = 'canvas2d' as const
  private ctx: CanvasRenderingContext2D
  private canvas: HTMLCanvasElement
  private w = 1
  private h = 1
  private dpr = 1

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('no 2d context')
    this.ctx = ctx
  }

  resize(cssW: number, cssH: number, dpr: number) {
    this.dpr = dpr
    this.w = Math.max(1, Math.round(cssW * dpr))
    this.h = Math.max(1, Math.round(cssH * dpr))
    this.canvas.width = this.w
    this.canvas.height = this.h
  }

  private project(m: Float32Array, x: number, y: number, out: [number, number]): boolean {
    // column-major mat4 * (x, y, 0, 1)
    const cx = m[0] * x + m[4] * y + m[12]
    const cy = m[1] * x + m[5] * y + m[13]
    const cw = m[3] * x + m[7] * y + m[15]
    if (cw <= 0) return false
    out[0] = (cx / cw * 0.5 + 0.5) * this.w
    out[1] = (1 - (cy / cw * 0.5 + 0.5)) * this.h
    return true
  }

  frame({ matrix, instances, count, timeSec }: FrameInput) {
    const ctx = this.ctx
    ctx.clearRect(0, 0, this.w, this.h)
    const p: [number, number] = [0, 0]
    const q: [number, number] = [0, 0]
    const pulse = 0.6 + 0.4 * Math.sin(timeSec * 6)
    for (let k = 0; k < count; k++) {
      const o = k * INSTANCE_FLOATS
      const x = instances[o]
      const y = instances[o + 1]
      const dx = instances[o + 2]
      const dy = instances[o + 3]
      const cat = instances[o + 4] | 0
      const size = instances[o + 5] * this.dpr
      if (!this.project(matrix, x, y, p)) continue
      const eps = 0.0006
      const haveDir = this.project(matrix, x + dx * eps, y + dy * eps, q)
      let ang = -Math.PI / 2
      if (haveDir) ang = Math.atan2(q[1] - p[1], q[0] - p[0])

      ctx.save()
      ctx.translate(p[0], p[1])
      ctx.rotate(ang + Math.PI / 2) // mesh forward (+y) maps to screen-up (-y)
      const color = COLORS[cat] ?? COLORS[2]
      const alert = cat === 3 || cat === 4

      // trail (behind the aircraft, i.e. +y in canvas)
      ctx.strokeStyle = color
      ctx.globalAlpha = (alert ? pulse : 1) * 0.35
      ctx.lineWidth = size * 0.7
      ctx.beginPath()
      ctx.moveTo(0, size * 0.4)
      ctx.lineTo(0, size * 4.2)
      ctx.stroke()

      // plane silhouette
      ctx.globalAlpha = alert ? pulse : 1
      ctx.fillStyle = color
      ctx.beginPath()
      for (let i = 0; i < PLANE_OUTLINE.length; i++) {
        const [lx, ly] = PLANE_OUTLINE[i]
        const sx = lx * size
        const sy = -ly * size // negate: mesh +y forward -> canvas -y up
        if (i === 0) ctx.moveTo(sx, sy)
        else ctx.lineTo(sx, sy)
      }
      ctx.closePath()
      ctx.fill()
      ctx.restore()
    }
    ctx.globalAlpha = 1
  }

  destroy() {}
}

export async function createFlightRenderer(canvas: HTMLCanvasElement): Promise<IFlightRenderer> {
  const gpu = await WebGPUFlightRenderer.create(canvas)
  if (gpu) return gpu
  return new Canvas2DFlightRenderer(canvas)
}
