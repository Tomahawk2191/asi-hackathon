/** Generate plane icons at runtime so we don't need an external sprite.
 *  Returns ImageData ready for map.addImage(). One tinted icon per altitude band.
 */
const SIZE = 36; // px

function drawPlane(color: string): ImageData {
  const c = document.createElement("canvas");
  c.width = c.height = SIZE;
  const ctx = c.getContext("2d")!;
  const s = SIZE / 40;
  ctx.clearRect(0, 0, SIZE, SIZE);
  ctx.translate(SIZE / 2, SIZE / 2);
  // Top-down plane silhouette (nose pointing up = heading 0)
  ctx.beginPath();
  ctx.moveTo(0, -18 * s);                // nose
  ctx.bezierCurveTo(2 * s, -16 * s,  3 * s, -8 * s,  3 * s, -4 * s);
  ctx.lineTo(18 * s, 2 * s);             // right wing tip
  ctx.lineTo(18 * s, 5 * s);
  ctx.lineTo(3 * s,  3 * s);
  ctx.lineTo(3 * s,  10 * s);
  ctx.lineTo(8 * s,  14 * s);            // right tailplane
  ctx.lineTo(8 * s,  16 * s);
  ctx.lineTo(0,      14 * s);            // tail center
  ctx.lineTo(-8 * s, 16 * s);
  ctx.lineTo(-8 * s, 14 * s);
  ctx.lineTo(-3 * s, 10 * s);
  ctx.lineTo(-3 * s,  3 * s);
  ctx.lineTo(-18 * s, 5 * s);
  ctx.lineTo(-18 * s, 2 * s);
  ctx.lineTo(-3 * s, -4 * s);
  ctx.bezierCurveTo(-3 * s, -8 * s, -2 * s, -16 * s, 0, -18 * s);
  ctx.closePath();
  ctx.fillStyle = color;
  ctx.fill();
  ctx.lineWidth = 1.3;
  ctx.strokeStyle = "rgba(15,18,30,0.85)";
  ctx.stroke();
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  return ctx.getImageData(0, 0, SIZE, SIZE);
}

export const PLANE_ICONS: Record<string, () => ImageData> = {
  "plane-vlow": () => drawPlane("#9ca3af"),
  "plane-low":  () => drawPlane("#60a5fa"),
  "plane-mid":  () => drawPlane("#a3e635"),
  "plane-high": () => drawPlane("#fbbf24"),
};

export function registerPlaneIcons(map: maplibregl.Map) {
  for (const [id, mk] of Object.entries(PLANE_ICONS)) {
    if (!map.hasImage(id)) map.addImage(id, mk(), { pixelRatio: 2 });
  }
}

// Type-only import so this file works without a runtime dep on maplibre.
import type maplibregl from "maplibre-gl";
