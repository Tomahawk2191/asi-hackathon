from pathlib import Path
import os

# Load env from project-root .env (one directory above backend/) if present.
try:
    from dotenv import load_dotenv  # type: ignore
    _root_env = Path(__file__).resolve().parents[2] / ".env"
    if _root_env.is_file():
        load_dotenv(_root_env, override=False)
    _backend_env = Path(__file__).resolve().parents[1] / ".env"
    if _backend_env.is_file():
        load_dotenv(_backend_env, override=False)
except Exception:
    pass

BUNDLE_DIR = Path(os.environ.get(
    "ASI_BUNDLE_DIR",
    "/Users/rohan/Downloads/hackathon_data_bundle",
))
SECTORS_PATH = BUNDLE_DIR / "sectors.geojson"
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
CACHE_DIR.mkdir(exist_ok=True)

# Weather grid (matches the bundle's .npz files exactly).
LAT_MIN, LAT_MAX = 21.943, 55.7765
LON_MIN, LON_MAX = -135.0, -67.5
ROWS, COLS = 256, 358

# Nodata sentinels.
REFC_NODATA = -50.0
RETOP_NODATA = 0.0  # docs say `< 0`, but treat anything <= 0 as missing.

# Sector altitude bands.
HIGH_FLOOR_FT = 35000
HIGH_CEIL_FT = 60000
LOW_FLOOR_FT = 0
LOW_CEIL_FT = 35000
