#!/usr/bin/env bash
# Runs the NOVA box display on novabox.recursivefunctions.dev.
#
#   ./display/serve.sh            -> http://localhost:8081 + tunnel to the quick (trycloudflare) hostname
#   NOVABOX_HOSTNAME=novabox.recursivefunctions.dev ./display/serve.sh
#                                     -> tunnel to the real hostname (named tunnel, needs cloudflared login as owner)
#
# The phone display opens http://localhost:8081 locally, or the public hostname once the tunnel is up.
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8081}"
HOSTNAME_TARGET="${NOVABOX_HOSTNAME:-}"

python3 app.py "$PORT" &
WEB_PID=$!
trap 'kill $WEB_PID 2>/dev/null || true' EXIT

if [[ "$WEB_PID" == "" ]]; then :; fi  # keep shellcheck quiet

if [[ -n "$HOSTNAME_TARGET" ]]; then
  echo "Starting cloudflared tunnel -> $HOSTNAME_TARGET (web on :$PORT)"
  cloudflared tunnel --no-autoupdate \
    --url "http://localhost:$PORT" \
    --hostname "$HOSTNAME_TARGET"
else
  echo "Starting cloudflared quick tunnel (web on :$PORT). Set NOVABOX_HOSTNAME for the fixed hostname."
  cloudflared tunnel --no-autoupdate --url "http://localhost:$PORT"
fi