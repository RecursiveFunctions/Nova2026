#!/usr/bin/env bash
# Deploy main → https://novabox.recursivefunctions.dev
set -euo pipefail

ROOT="${NOVA_ROOT:-/home/ray/code/Nova2026}"
BRANCH="${NOVA_BRANCH:-main}"
REMOTE="${NOVA_REMOTE:-origin}"

cd "$ROOT"
git fetch --prune "$REMOTE"
git checkout "$BRANCH"
git reset --hard "$REMOTE/$BRANCH"

if systemctl --user is-enabled nova-display.service >/dev/null 2>&1; then
  systemctl --user restart nova-display.service
else
  echo "nova-display.service not enabled; run deploy/install-host.sh"
  exit 1
fi

# Wait until healthy
for i in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:8081/health" >/dev/null 2>&1; then
    echo "deployed $(git rev-parse --short HEAD) → https://novabox.recursivefunctions.dev"
    exit 0
  fi
  sleep 0.5
done
echo "service did not become healthy" >&2
systemctl --user status nova-display.service --no-pager >&2 || true
exit 1
