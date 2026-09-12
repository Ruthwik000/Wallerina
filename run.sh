#!/usr/bin/env bash
# Run Wallerina backend (FastAPI) + frontend (Next.js) together.
#
# Usage:
#   ./run.sh                    # run both
#   ./run.sh --backend-only      # run only FastAPI on :8000
#   ./run.sh --frontend-only     # run only Next.js on :3000
#   ./run.sh --install           # install deps first, then run both
#   FRESH=true ./run.sh            # also wipe frontend/.next cache first
#   BACKEND_PORT=8001 FRONTEND_PORT=3001 ./run.sh   # custom ports
#
# run.sh kills whatever is already LISTENing on its ports before starting.

set -u
set -o pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
export NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-http://localhost:$BACKEND_PORT}"

RUN_BACKEND=true
RUN_FRONTEND=true
DO_INSTALL=false

for arg in "$@"; do
  case "$arg" in
    --backend-only)  RUN_FRONTEND=false ;;
    --frontend-only) RUN_BACKEND=false ;;
    --install)       DO_INSTALL=true ;;
    -h|--help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown option: $arg (try --help)" >&2
      exit 1
      ;;
  esac
done

log()  { printf '\033[1;34m[run.sh]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[run.sh]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[run.sh]\033[0m %s\n' "$*" >&2; exit 1; }

# PIDs listening on a TCP port (LISTEN state only — ignores browser tabs
# merely connected to the dev server).
listeners_on() {
  lsof -tiTCP:"$1" -sTCP:LISTEN 2>/dev/null || true
}

# Free a port by killing whatever is listening on it.
free_port() {
  local port="$1" pids
  pids="$(listeners_on "$port")"
  [ -z "$pids" ] && return 0
  # shellcheck disable=SC2086
  log "Port $port is busy (pids: $(echo $pids)) — stopping those processes..."
  # shellcheck disable=SC2086
  kill $pids 2>/dev/null || true
  for _ in $(seq 1 25); do
    [ -z "$(listeners_on "$port")" ] && return 0
    sleep 0.2
  done
  # shellcheck disable=SC2086
  kill -9 $pids 2>/dev/null || true
  sleep 1
  [ -z "$(listeners_on "$port")" ] && return 0
  die "Could not free port $port. Stop that process or set a different port (e.g. BACKEND_PORT=8001 ./run.sh)."
}

command -v lsof >/dev/null 2>&1 && {
  $RUN_BACKEND  && free_port "$BACKEND_PORT"
  $RUN_FRONTEND && free_port "$FRONTEND_PORT"
}

# Clear a stale/corrupt Next.js build cache (causes "Cannot find module './*.js'").
if $RUN_FRONTEND && [ -d "$FRONTEND_DIR/.next" ] && [ "${FRESH:-false}" = "true" ]; then
  log "FRESH=true — clearing frontend/.next cache..."
  rm -rf "$FRONTEND_DIR/.next"
fi

# --- prerequisites -----------------------------------------------------------
$RUN_BACKEND && command -v uv >/dev/null 2>&1 || {
  $RUN_BACKEND || true
  if $RUN_BACKEND; then die "'uv' not found. Install it: https://docs.astral.sh/uv/"; fi
}
$RUN_FRONTEND && command -v npm >/dev/null 2>&1 || {
  if $RUN_FRONTEND; then die "'npm' not found. Install Node.js 18+: https://nodejs.org/"; fi
}

[ -d "$BACKEND_DIR" ]  || die "backend/ not found at $BACKEND_DIR"
[ -d "$FRONTEND_DIR" ] || die "frontend/ not found at $FRONTEND_DIR"

# --- backend env -------------------------------------------------------------
if $RUN_BACKEND && [ ! -f "$BACKEND_DIR/.env" ]; then
  if [ -f "$BACKEND_DIR/.env.example" ]; then
    warn "backend/.env missing — copy it and add your keys: cp backend/.env.example backend/.env"
  else
    warn "backend/.env missing."
  fi
fi

# --- install deps ------------------------------------------------------------
if $DO_INSTALL; then
  $RUN_BACKEND  && { log "Installing backend deps (uv sync)..."; (cd "$BACKEND_DIR" && uv sync) || die "uv sync failed"; }
  $RUN_FRONTEND && { log "Installing frontend deps (npm install)..."; (cd "$FRONTEND_DIR" && npm install) || die "npm install failed"; }
else
  $RUN_FRONTEND && [ ! -d "$FRONTEND_DIR/node_modules" ] && {
    log "node_modules missing — running npm install..."
    (cd "$FRONTEND_DIR" && npm install) || die "npm install failed"
  }
fi

# --- cleanup -----------------------------------------------------------------
PIDS=""
cleanup() {
  log "Shutting down..."
  # shellcheck disable=SC2086
  [ -n "$PIDS" ] && kill $PIDS 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

# --- run ---------------------------------------------------------------------
$RUN_BACKEND && {
  log "Starting backend  → http://localhost:$BACKEND_PORT (docs: http://localhost:$BACKEND_PORT/docs)"
  (cd "$BACKEND_DIR" && uv run uvicorn backend.main:app --reload --host 0.0.0.0 --port "$BACKEND_PORT") &
  PIDS="$PIDS $!"
}

$RUN_FRONTEND && {
  log "Starting frontend → http://localhost:$FRONTEND_PORT (API: $NEXT_PUBLIC_API_URL)"
  (cd "$FRONTEND_DIR" && PORT="$FRONTEND_PORT" npm run dev -- --port "$FRONTEND_PORT") &
  PIDS="$PIDS $!"
}

[ -z "$PIDS" ] && die "Nothing to run."

log "Both processes running. Press Ctrl+C to stop."
# shellcheck disable=SC2086
wait $PIDS
