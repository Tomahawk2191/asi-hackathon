"""Render a (ROWS, COLS) weather matrix to an RGBA PNG with a turbo-ish ramp."""
from __future__ import annotations

import io

import numpy as np
from PIL import Image

# Discrete reflectivity color stops in dBZ — close to NWS reflectivity palette.
REFC_STOPS = [
    (5,   (4, 233, 231, 110)),
    (10,  (1, 159, 244, 140)),
    (15,  (3, 0, 244, 160)),
    (20,  (2, 253, 2, 175)),
    (25,  (1, 197, 1, 190)),
    (30,  (0, 142, 0, 205)),
    (35,  (253, 248, 2, 220)),
    (40,  (229, 188, 0, 230)),
    (45,  (253, 149, 0, 240)),
    (50,  (253, 0, 0, 245)),
    (55,  (212, 0, 0, 250)),
    (60,  (188, 0, 0, 250)),
    (65,  (248, 0, 253, 255)),
    (70,  (152, 84, 198, 255)),
]


def _refc_color(v: float) -> tuple[int, int, int, int]:
    if not np.isfinite(v) or v < REFC_STOPS[0][0]:
        return (0, 0, 0, 0)
    for thresh, color in REFC_STOPS:
        if v < thresh:
            return color
    return REFC_STOPS[-1][1]


def _retop_color(v: float) -> tuple[int, int, int, int]:
    if not np.isfinite(v) or v <= 0:
        return (0, 0, 0, 0)
    # Map 0..60_000 ft to a blue→white ramp.
    t = max(0.0, min(1.0, v / 60_000.0))
    g = int(120 + 130 * t)
    b = 255
    r = int(60 + 180 * t)
    return (r, g, b, int(140 + 80 * t))


def matrix_to_png(matrix: np.ndarray, field: str) -> bytes:
    rows, cols = matrix.shape
    img = np.zeros((rows, cols, 4), dtype=np.uint8)
    color_fn = _refc_color if field == "refc" else _retop_color
    # Vectorize-ish: walk thresholds for refc, simple ramp for retop.
    if field == "refc":
        mask_invalid = ~np.isfinite(matrix) | (matrix < REFC_STOPS[0][0])
        for thresh, color in REFC_STOPS:
            sel = (~mask_invalid) & (matrix < thresh) & (img[..., 3] == 0)
            img[sel] = color
        sel = (~mask_invalid) & (img[..., 3] == 0)
        img[sel] = REFC_STOPS[-1][1]
    else:
        valid = np.isfinite(matrix) & (matrix > 0)
        t = np.clip(matrix / 60_000.0, 0, 1)
        img[..., 0] = np.where(valid, (60 + 180 * t).astype(np.uint8), 0)
        img[..., 1] = np.where(valid, (120 + 130 * t).astype(np.uint8), 0)
        img[..., 2] = np.where(valid, 255, 0)
        img[..., 3] = np.where(valid, (140 + 80 * t).astype(np.uint8), 0)
    buf = io.BytesIO()
    Image.fromarray(img, mode="RGBA").save(buf, format="PNG", optimize=False)
    return buf.getvalue()
