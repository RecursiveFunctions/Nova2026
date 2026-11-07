#!/usr/bin/env bash
# One-time setup on the deploy host (1mhzmb4-1).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"
APPS="${NOVA_APPS:-$HOME/apps/nova2026}"

mkdir -p "$UNIT_DIR" "$APPS/previews"
echo '{}' > "$APPS/previews/routes.json"

cp "$ROOT/deploy/nova-display.service" "$UNIT_DIR/"
cp "$ROOT/deploy/nova-preview-router.service" "$UNIT_DIR/"

# Allow user services without an interactive login
loginctl enable-linger "$USER" || true

systemctl --user daemon-reload
systemctl --user enable --now nova-display.service
systemctl --user enable --now nova-preview-router.service

echo "installed:"
systemctl --user --no-pager --full status nova-display.service nova-preview-router.service || true
