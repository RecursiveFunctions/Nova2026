#!/usr/bin/env bash
# Create/update/destroy a branch preview at https://novabox.recursivefunctions.dev/p/<slug>/
# Usage:
#   deploy-preview.sh upsert <git-ref> [slug]
#   deploy-preview.sh destroy <slug>
set -euo pipefail

ACTION="${1:?action required (upsert|destroy)}"
APPS="${NOVA_APPS:-/home/ray/apps/nova2026}"
PREVIEWS="$APPS/previews"
SRC_REPO="${NOVA_ROOT:-/home/ray/code/Nova2026}"
PORT_BASE="${NOVA_PREVIEW_PORT_BASE:-8200}"
PORT_SPAN="${NOVA_PREVIEW_PORT_SPAN:-80}"
ROUTER_PORT="${NOVA_PREVIEW_ROUTER_PORT:-8090}"
DOMAIN="${NOVA_PREVIEW_DOMAIN:-novabox.recursivefunctions.dev}"
RESERVED="main master p boxes pickup orders demo health docs script.js style.css index.html order_qr.png favicon.ico api static assets"

slugify() {
  echo "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//; s/-+/-/g' | cut -c1-48
}

port_for_slug() {
  local slug="$1" h=0 c
  while IFS= read -r -n1 c; do
    [[ -z "$c" ]] && continue
    printf -v o '%d' "'$c"
    h=$(( (h * 33 + o) % PORT_SPAN ))
  done <<< "$slug"
  echo $((PORT_BASE + h))
}

ensure_routes() {
  python3 - <<'PY'
import json
from pathlib import Path
root = Path("/home/ray/apps/nova2026/previews")
routes = {}
for meta in root.glob("*/meta.json"):
    data = json.loads(meta.read_text())
    if data.get("port") and data.get("slug"):
        routes[data["slug"]] = {"port": data["port"], "ref": data.get("ref", ""), "updated": data.get("updated", "")}
(root / "routes.json").write_text(json.dumps(routes, indent=2) + "\n")
print(f"routes={len(routes)}")
PY
  if systemctl --user is-active nova-preview-router.service >/dev/null 2>&1; then
    systemctl --user kill -s HUP nova-preview-router.service || true
  fi
}

stop_preview() {
  local dir="$1"
  if [[ -f "$dir/preview.pid" ]]; then
    kill "$(cat "$dir/preview.pid")" 2>/dev/null || true
    rm -f "$dir/preview.pid"
  fi
}

if [[ "$ACTION" == "destroy" ]]; then
  SLUG="$(slugify "${2:?slug required}")"
  DIR="$PREVIEWS/$SLUG"
  stop_preview "$DIR"
  rm -rf "$DIR"
  ensure_routes
  echo "destroyed https://$DOMAIN/p/$SLUG/"
  exit 0
fi

if [[ "$ACTION" != "upsert" ]]; then
  echo "unknown action: $ACTION" >&2
  exit 2
fi

REF="${2:?git ref required}"
SLUG="$(slugify "${3:-$REF}")"
if [[ -z "$SLUG" ]]; then
  echo "empty slug" >&2
  exit 2
fi
for r in $RESERVED; do
  if [[ "$SLUG" == "$r" ]]; then
    echo "refusing reserved slug='$SLUG'" >&2
    exit 2
  fi
done

DIR="$PREVIEWS/$SLUG"
PORT="$(port_for_slug "$SLUG")"
mkdir -p "$DIR"

if [[ ! -d "$DIR/repo/.git" ]]; then
  git clone --shared "$SRC_REPO" "$DIR/repo"
fi

cd "$DIR/repo"
git fetch --prune origin
git checkout --force "$REF" 2>/dev/null || git checkout --force -B "$SLUG" "origin/$REF" 2>/dev/null || git checkout --force "origin/$REF"
git reset --hard FETCH_HEAD 2>/dev/null || git reset --hard "origin/$REF" 2>/dev/null || git reset --hard HEAD
if git rev-parse --verify "$REF^{commit}" >/dev/null 2>&1; then
  git checkout --force "$REF"
fi

stop_preview "$DIR"

export DATABASE_PATH="$DIR/pickup_box.db"
export CORS_ORIGINS="*"

nohup uv run --with fastapi --with uvicorn python display/app.py "$PORT" \
  >"$DIR/preview.log" 2>&1 &
echo $! >"$DIR/preview.pid"

python3 - <<PY
import json, time
from pathlib import Path
meta = {
  "slug": "$SLUG",
  "ref": "$REF",
  "sha": "$(git rev-parse HEAD)",
  "port": $PORT,
  "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
  "url": "https://$DOMAIN/p/$SLUG/",
}
Path("$DIR/meta.json").write_text(json.dumps(meta, indent=2) + "\n")
print(json.dumps(meta))
PY

for i in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done

ensure_routes
echo "preview https://$DOMAIN/p/$SLUG/ (port $PORT, router :$ROUTER_PORT)"
