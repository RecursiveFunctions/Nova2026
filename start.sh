#!/usr/bin/env bash
# One-command startup (macOS / Linux):  ./start.sh
# Installs what is missing, runs backend (port 8000) and frontend (port 5173); Ctrl+C stops both.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
PY="$ROOT/backend/.venv/bin/python"

if [ ! -x "$PY" ]; then
  echo "Creating backend virtual environment..."
  python3 -m venv "$ROOT/backend/.venv"
fi
echo "Checking backend packages..."
"$PY" -m pip install -q --disable-pip-version-check -r "$ROOT/backend/requirements.txt"

if [ ! -d "$ROOT/frontend/node_modules" ]; then
  echo "Installing frontend packages..."
  (cd "$ROOT/frontend" && npm install)
fi
[ -f "$ROOT/backend/.env" ] || echo "WARNING: backend/.env not found, using defaults (copy backend/.env.example)."

(cd "$ROOT/backend" && exec "$PY" -m uvicorn main:app --host 0.0.0.0 --port 8000) &
BACKEND=$!
(cd "$ROOT/frontend" && exec npm run dev) &
FRONTEND=$!
trap 'kill $BACKEND $FRONTEND 2>/dev/null' EXIT INT TERM

IP="$( (ipconfig getifaddr en0 || hostname -I | awk '{print $1}') 2>/dev/null || true)"
IP="${IP:-<this-laptop-LAN-IP>}"
sleep 2
echo
echo "Running (Ctrl+C stops both)."
echo "  On this laptop:   http://127.0.0.1:5173/          (links to everything)"
echo "  Simulator:        http://$IP:5173/simulator"
echo "  Courier codes:    http://127.0.0.1:5173/courier   (demo only)"
echo "  Box screens:      http://$IP:5173/screen/BOX-01  and  /screen/BOX-02"
echo "  NFC/QR (local):   http://$IP:5173/pickup/BOX-01  and  /pickup/BOX-02"
echo "  NFC/QR (public):  https://novabox.recursivefunctions.dev/pickup/BOX-01"
echo "  Branch demo:      https://novabox.recursivefunctions.dev/<branch>/pickup/BOX-01"
echo "  API docs:         http://$IP:8000/docs"
echo "  Bridge:           export API_BASE_URL=https://novabox.recursivefunctions.dev"
echo "                    export PUBLIC_URL=https://novabox.recursivefunctions.dev"
wait
