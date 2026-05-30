#!/usr/bin/env bash
# Start backend (FastAPI on :8765) and frontend (Vite on :5173) together.
# Ctrl-C stops both cleanly. Logs are tee'd to .logs/.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
mkdir -p .logs

# --- Preflight ---
need() { command -v "$1" >/dev/null 2>&1 || { echo "missing: $1" >&2; exit 1; }; }
need uv
need node
need npm

if ! command -v codes_info >/dev/null 2>&1 && ! brew list eccodes >/dev/null 2>&1; then
  echo "eccodes (live HRRR grib2 decoding) not detected. Installing via Homebrew..."
  need brew
  brew install eccodes
fi

if [[ ! -f .env ]]; then
  echo "WARN: .env not found. Copy .env.example to .env and fill in OpenSky creds for live traffic." >&2
fi

# --- Sync deps ---
echo "[1/3] backend deps (uv sync)…"
(cd backend && uv sync --quiet)
echo "[2/3] frontend deps (npm install)…"
(cd frontend && npm install --silent --no-fund --no-audit)

# --- Spawn ---
cleanup() {
  echo
  echo "stopping…"
  jobs -p | xargs -r kill 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "[3/3] starting servers…"
(
  cd backend
  uv run uvicorn app.main:app --host 127.0.0.1 --port 8765 --reload 2>&1 | tee "$ROOT/.logs/backend.log" \
    | sed -u 's/^/[backend] /'
) &
BACKEND_PID=$!

(
  cd frontend
  npm run dev -- --port 5173 --strictPort 2>&1 | tee "$ROOT/.logs/frontend.log" \
    | sed -u 's/^/[frontend] /'
) &
FRONTEND_PID=$!

# Wait briefly, then print the URL once both are listening.
sleep 2
echo
echo "  Backend : http://127.0.0.1:8765"
echo "  Frontend: http://localhost:5173"
echo "  Logs    : .logs/{backend,frontend}.log"
echo "  Ctrl-C to stop both."
echo

wait $BACKEND_PID $FRONTEND_PID
