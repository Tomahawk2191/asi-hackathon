// WebGPU flight renderer.
//
// Draws every active aircraft as an instanced delta/chevron with an additive
// motion-streak trail, on a transparent canvas overlaid exactly on the
// MapLibre map. The camera comes from MapLibre's own mercator->clip matrix
// (captured by a no-op custom layer), so the overlay stays pixel-locked to the
// basemap through any pan / zoom / rotate.
//
// Two pipelines share one instance buffer:
//   - trails  : additive, tapered streaks (the glow)
//   - chevrons: premultiplied-alpha arrowheads (the aircraft)
//
// 4x MSAA, no depth buffer (everything is a flat 2D overlay), and the whole
// thing is driven by a decoupled rAF so it runs at the display's full refresh
// rate independent of how often the map repaints.

// 6 floats per instance: posX, posY (mercator), dirX, dirY (heading), color, size
export const INSTANCE_FLOATS = 6
export const INSTANCE_STRIDE = INSTANCE_FLOATS * 4

export interface FrameInput {
  matrix: Float32Array // mat4 mercator(0..1) -> clip space
  instances: Float32Array // packed, length >= count * INSTANCE_FLOATS
  count: number
  timeSec: number
}

export interface IFlightRenderer {
  resize(cssW: number, cssH: number, dpr: number): void
  frame(input: FrameInput): void
  destroy(): void
  readonly backend: 'webgpu' | 'canvas2d'
}

const SHADER = /* wgsl */ `
struct Uniforms {
  mvp      : mat4x4<f32>,
  viewport : vec2<f32>,   // physical pixels
  dpr      : f32,
  time     : f32,
};
@group(0) @binding(0) var<uniform> U : Uniforms;

struct VSOut {
  @builtin(position) pos : vec4<f32>,
  @location(0) color     : vec4<f32>,
  @location(1) edge      : f32,   // for trail taper / chevron core
};

// category -> rgba
fn palette(c : f32) -> vec4<f32> {
  // Opaque fills (a=1): the plane silhouette is several overlapping triangles,
  // so brightness — not alpha — encodes the category to avoid blend seams.
  let k = i32(c + 0.5);
  if (k == 0) { return vec4<f32>(0.95, 0.97, 1.00, 1.0); } // core arrival (white)
  if (k == 1) { return vec4<f32>(0.62, 0.70, 0.82, 1.0); } // metro arrival
  if (k == 2) { return vec4<f32>(0.34, 0.41, 0.52, 1.0); } // departure / transit
  if (k == 3) { return vec4<f32>(1.00, 0.69, 0.00, 1.0); } // selected (amber)
  return vec4<f32>(1.00, 0.34, 0.22, 1.0);                 // alert (over capacity)
}

// Build a screen-space basis (forward / right, in physical px) from the
// instance heading by projecting the centre and a nudged point.
fn screenBasis(iPos : vec2<f32>, iDir : vec2<f32>, c0 : vec4<f32>) -> mat2x2<f32> {
  let eps = 0.0006;
  let c1 = U.mvp * vec4<f32>(iPos + iDir * eps, 0.0, 1.0);
  let s0 = c0.xy / c0.w;
  let s1 = c1.xy / c1.w;
  var d = (s1 - s0) * U.viewport;          // clip delta -> px delta
  let len = max(length(d), 1e-5);
  let fwd = d / len;
  let right = vec2<f32>(fwd.y, -fwd.x);
  return mat2x2<f32>(right, fwd);
}

fn place(c0 : vec4<f32>, basis : mat2x2<f32>, local : vec2<f32>, sizeCss : f32) -> vec4<f32> {
  let px = basis * (local * sizeCss * U.dpr);              // physical px offset
  let ndc = px / U.viewport * 2.0 * c0.w;                  // -> clip, w-corrected
  return vec4<f32>(c0.xy + ndc, 0.0, c0.w);                // z=0 keeps WebGPU clip happy
}

// ---- plane / aircraft ----
@vertex
fn vsChevron(
  @location(0) local : vec2<f32>,
  @location(1) iPos  : vec2<f32>,
  @location(2) iDir  : vec2<f32>,
  @location(3) iCol  : f32,
  @location(4) iSize : f32,
) -> VSOut {
  var out : VSOut;
  let c0 = U.mvp * vec4<f32>(iPos, 0.0, 1.0);
  let basis = screenBasis(iPos, iDir, c0);
  out.pos = place(c0, basis, local, iSize);
  var col = palette(iCol);
  let k = i32(iCol + 0.5);
  if (k == 3 || k == 4) {
    let pulse = 0.65 + 0.35 * sin(U.time * 6.0);           // selected/alert pulse
    col = vec4<f32>(col.rgb * pulse, 1.0);                 // modulate brightness, stay opaque
  }
  out.color = col;
  out.edge = 0.0;
  return out;
}

// ---- trail / streak ----
@vertex
fn vsTrail(
  @location(0) local : vec2<f32>,   // x in [-0.5,0.5], y in [-1,0] (behind)
  @location(1) iPos  : vec2<f32>,
  @location(2) iDir  : vec2<f32>,
  @location(3) iCol  : f32,
  @location(4) iSize : f32,
) -> VSOut {
  var out : VSOut;
  let c0 = U.mvp * vec4<f32>(iPos, 0.0, 1.0);
  let basis = screenBasis(iPos, iDir, c0);
  // streak: wide-ish near the aircraft, long tail behind
  let scaled = vec2<f32>(local.x * (iSize * 0.55), local.y * (iSize * 4.2));
  let px = basis * (scaled * U.dpr);
  let ndc = px / U.viewport * 2.0 * c0.w;
  out.pos = vec4<f32>(c0.xy + ndc, 0.0, c0.w);
  out.color = palette(iCol);
  out.edge = 1.0 + local.y;   // 1 at head, 0 at tail
  return out;
}

@fragment
fn fsChevron(in : VSOut) -> @location(0) vec4<f32> {
  return vec4<f32>(in.color.rgb * in.color.a, in.color.a); // premultiplied
}

@fragment
fn fsTrail(in : VSOut) -> @location(0) vec4<f32> {
  let t = clamp(in.edge, 0.0, 1.0);
  let a = t * t * 0.5 * in.color.a;        // fade to nothing at the tail
  return vec4<f32>(in.color.rgb * a, a);   // additive glow
}
`

// minimalist top-down plane silhouette (local units, +y forward): fuselage +
// swept wings + tailplane, as 7 non-overlapping triangles (21 vertices).
const PLANE = new Float32Array([
  // fuselage: nose
  0.0, 1.5, 0.1, 0.4, -0.1, 0.4,
  // fuselage: body (two triangles)
  0.1, 0.4, 0.09, -1.3, -0.1, 0.4,
  0.09, -1.3, -0.09, -1.3, -0.1, 0.4,
  // right wing
  0.1, 0.42, 1.4, -0.4, 0.08, -0.1,
  // left wing
  -0.1, 0.42, -0.08, -0.1, -1.4, -0.4,
  // right tailplane
  0.08, -1.0, 0.55, -1.36, 0.06, -1.26,
  // left tailplane
  -0.08, -1.0, -0.06, -1.26, -0.55, -1.36,
])
const PLANE_VERTS = PLANE.length / 2
// trail quad: x in [-0.5,0.5], y in [-1,0]
const TRAIL = new Float32Array([
  -0.5, 0.0, 0.5, 0.0, -0.5, -1.0,
  0.5, 0.0, 0.5, -1.0, -0.5, -1.0,
])

const SAMPLE_COUNT = 4

export class WebGPUFlightRenderer implements IFlightRenderer {
  readonly backend = 'webgpu' as const
  private device!: GPUDevice
  private ctx!: GPUCanvasContext
  private format!: GPUTextureFormat
  private uniformBuf!: GPUBuffer
  private instanceBuf!: GPUBuffer
  private chevronGeo!: GPUBuffer
  private trailGeo!: GPUBuffer
  private chevronPipe!: GPURenderPipeline
  private trailPipe!: GPURenderPipeline
  private bindGroup!: GPUBindGroup
  private msaa: GPUTexture | null = null
  private uniformData = new Float32Array(20) // mat4(16) + vec2 + f32 + f32
  private instanceCapacity = 0
  private w = 1
  private h = 1
  private dpr = 1

  static async create(canvas: HTMLCanvasElement): Promise<WebGPUFlightRenderer | null> {
    if (!('gpu' in navigator)) return null
    try {
      const adapter = await navigator.gpu.requestAdapter({ powerPreference: 'high-performance' })
      if (!adapter) return null
      const device = await adapter.requestDevice()
      const r = new WebGPUFlightRenderer()
      r.init(canvas, device)
      return r
    } catch (e) {
      console.warn('[webgpu] init failed, falling back', e)
      return null
    }
  }

  private init(canvas: HTMLCanvasElement, device: GPUDevice) {
    this.device = device
    const ctx = canvas.getContext('webgpu')
    if (!ctx) throw new Error('no webgpu context')
    this.ctx = ctx
    this.format = navigator.gpu.getPreferredCanvasFormat()
    ctx.configure({ device, format: this.format, alphaMode: 'premultiplied' })

    const module = device.createShaderModule({ code: SHADER })

    this.uniformBuf = device.createBuffer({
      size: this.uniformData.byteLength,
      usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
    })
    this.chevronGeo = this.makeVertexBuffer(PLANE)
    this.trailGeo = this.makeVertexBuffer(TRAIL)
    this.growInstances(2048)

    const bgl = device.createBindGroupLayout({
      entries: [{ binding: 0, visibility: GPUShaderStage.VERTEX, buffer: { type: 'uniform' } }],
    })
    this.bindGroup = device.createBindGroup({
      layout: bgl,
      entries: [{ binding: 0, resource: { buffer: this.uniformBuf } }],
    })
    const layout = device.createPipelineLayout({ bindGroupLayouts: [bgl] })

    const geoLayout: GPUVertexBufferLayout = {
      arrayStride: 8,
      stepMode: 'vertex',
      attributes: [{ shaderLocation: 0, offset: 0, format: 'float32x2' }],
    }
    const instLayout: GPUVertexBufferLayout = {
      arrayStride: INSTANCE_STRIDE,
      stepMode: 'instance',
      attributes: [
        { shaderLocation: 1, offset: 0, format: 'float32x2' },
        { shaderLocation: 2, offset: 8, format: 'float32x2' },
        { shaderLocation: 3, offset: 16, format: 'float32' },
        { shaderLocation: 4, offset: 20, format: 'float32' },
      ],
    }

    const premultBlend: GPUBlendState = {
      color: { srcFactor: 'one', dstFactor: 'one-minus-src-alpha', operation: 'add' },
      alpha: { srcFactor: 'one', dstFactor: 'one-minus-src-alpha', operation: 'add' },
    }
    const additiveBlend: GPUBlendState = {
      color: { srcFactor: 'one', dstFactor: 'one', operation: 'add' },
      alpha: { srcFactor: 'one', dstFactor: 'one', operation: 'add' },
    }

    this.trailPipe = device.createRenderPipeline({
      layout,
      vertex: { module, entryPoint: 'vsTrail', buffers: [geoLayout, instLayout] },
      fragment: { module, entryPoint: 'fsTrail', targets: [{ format: this.format, blend: additiveBlend }] },
      primitive: { topology: 'triangle-list' },
      multisample: { count: SAMPLE_COUNT },
    })
    this.chevronPipe = device.createRenderPipeline({
      layout,
      vertex: { module, entryPoint: 'vsChevron', buffers: [geoLayout, instLayout] },
      fragment: { module, entryPoint: 'fsChevron', targets: [{ format: this.format, blend: premultBlend }] },
      primitive: { topology: 'triangle-list' },
      multisample: { count: SAMPLE_COUNT },
    })
  }

  private makeVertexBuffer(data: Float32Array): GPUBuffer {
    const buf = this.device.createBuffer({
      size: data.byteLength,
      usage: GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST,
    })
    this.device.queue.writeBuffer(buf, 0, data)
    return buf
  }

  private growInstances(capacity: number) {
    if (capacity <= this.instanceCapacity) return
    this.instanceCapacity = capacity
    this.instanceBuf?.destroy()
    this.instanceBuf = this.device.createBuffer({
      size: capacity * INSTANCE_STRIDE,
      usage: GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST,
    })
  }

  resize(cssW: number, cssH: number, dpr: number) {
    this.dpr = dpr
    this.w = Math.max(1, Math.round(cssW * dpr))
    this.h = Math.max(1, Math.round(cssH * dpr))
    const canvas = this.ctx.canvas as HTMLCanvasElement
    canvas.width = this.w
    canvas.height = this.h
    this.msaa?.destroy()
    this.msaa = this.device.createTexture({
      size: [this.w, this.h],
      sampleCount: SAMPLE_COUNT,
      format: this.format,
      usage: GPUTextureUsage.RENDER_ATTACHMENT,
    })
  }

  frame({ matrix, instances, count, timeSec }: FrameInput) {
    if (!this.msaa) return
    if (count > this.instanceCapacity) this.growInstances(Math.ceil(count * 1.5))

    this.uniformData.set(matrix, 0)
    this.uniformData[16] = this.w
    this.uniformData[17] = this.h
    this.uniformData[18] = this.dpr
    this.uniformData[19] = timeSec
    this.device.queue.writeBuffer(this.uniformBuf, 0, this.uniformData)

    if (count > 0) {
      this.device.queue.writeBuffer(
        this.instanceBuf,
        0,
        instances.buffer,
        instances.byteOffset,
        count * INSTANCE_STRIDE,
      )
    }

    const encoder = this.device.createCommandEncoder()
    const pass = encoder.beginRenderPass({
      colorAttachments: [
        {
          view: this.msaa!.createView(),
          resolveTarget: this.ctx.getCurrentTexture().createView(),
          clearValue: { r: 0, g: 0, b: 0, a: 0 },
          loadOp: 'clear',
          storeOp: 'store',
        },
      ],
    })
    if (count > 0) {
      pass.setBindGroup(0, this.bindGroup)
      pass.setVertexBuffer(1, this.instanceBuf)
      // trails first (under), then planes
      pass.setPipeline(this.trailPipe)
      pass.setVertexBuffer(0, this.trailGeo)
      pass.draw(6, count)
      pass.setPipeline(this.chevronPipe)
      pass.setVertexBuffer(0, this.chevronGeo)
      pass.draw(PLANE_VERTS, count)
    }
    pass.end()
    this.device.queue.submit([encoder.finish()])
  }

  destroy() {
    this.msaa?.destroy()
    this.instanceBuf?.destroy()
    this.uniformBuf?.destroy()
    this.chevronGeo?.destroy()
    this.trailGeo?.destroy()
  }
}
