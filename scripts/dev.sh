#!/usr/bin/env bash
# Start the HEATBEAT backend (API, port 8000) and frontend (map, port 5173) together.
#
#   ./scripts/dev.sh            from the repo folder
#
# First run installs what is missing (Python packages into .venv, npm packages into frontend/).
# Stop both with Ctrl+C.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

# Python: use the repo .venv, create it if missing
if [ ! -x "$ROOT/.venv/bin/python" ]; then
  echo "==> Creating Python environment .venv"
  python3 -m venv "$ROOT/.venv"
fi
PY="$ROOT/.venv/bin/python"
if ! "$PY" -c "import fastapi, uvicorn, pandas, pyarrow, yaml" >/dev/null 2>&1; then
  echo "==> Installing Python packages (one time)"
  "$PY" -m pip install -q --upgrade pip
  "$PY" -m pip install -q -r requirements.txt -r requirements-api.txt
fi

# Frontend packages
if [ ! -d "$ROOT/frontend/node_modules" ]; then
  echo "==> Installing frontend packages (one time)"
  (cd "$ROOT/frontend" && npm install --no-fund --no-audit)
fi

API_PORT="${API_PORT:-8000}"
echo "==> Starting API on http://127.0.0.1:$API_PORT (docs: http://127.0.0.1:$API_PORT/docs)"
"$PY" -m uvicorn heatbeat_api.app:app --port "$API_PORT" --reload --reload-dir heatbeat_api &
API_PID=$!
trap 'echo; echo "==> Stopping"; kill $API_PID 2>/dev/null || true' EXIT INT TERM

# wait until the API answers (first start builds the SQLite database, a few seconds)
for _ in $(seq 1 60); do
  if curl -fs "http://127.0.0.1:$API_PORT/api/health" >/dev/null 2>&1; then break; fi
  sleep 1
done

echo "==> Starting frontend on http://localhost:5173"
cd "$ROOT/frontend"
HEATBEAT_API="http://127.0.0.1:$API_PORT" npm run dev -- --open
