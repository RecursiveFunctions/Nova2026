#!/usr/bin/env bash
# Create/update/destroy a branch preview at https://novabox.recursivefunctions.dev/<slug>/
set -euo pipefail

ACTION="${1:?action required (upsert|destroy)}"
APPS="${NOVA_APPS:-/home/ray/apps/nova2026}"
PREVIEWS="$APPS/previews"
GIT_URL="${NOVA_GIT_URL:-https://github.com/RecursiveFunctions/Nova2026.git}"
UV="${UV:-$HOME/.local/bin/uv}"
PORT_BASE="${NOVA_PREVIEW_PORT_BASE:-8200}"
PORT_SPAN="${NOVA_PREVIEW_PORT_SPAN:-80}"
ROUTER_PORT="${NOVA_PREVIEW_ROUTER_PORT:-8090}"
DOMAIN="${NOVA_PREVIEW_DOMAIN:-novabox.recursivefunctions.dev}"
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"

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
    local pid; pid="$(cat "$dir/preview.pid")"
    kill "$pid" 2>/dev/null || true
    pkill -P "$pid" 2>/dev/null || true
    rm -f "$dir/preview.pid"
  fi
  if [[ -f "$dir/meta.json" ]]; then
    local port
    port="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("port",""))' "$dir/meta.json" 2>/dev/null || true)"
    if [[ -n "$port" ]]; then fuser -k "${port}/tcp" 2>/dev/null || true; fi
  fi
}

if [[ "$ACTION" == "destroy" ]]; then
  SLUG="$(slugify "${2:?slug required}")"
  DIR="$PREVIEWS/$SLUG"
  stop_preview "$DIR"
  rm -rf "$DIR"
  ensure_routes
  echo "destroyed https://$DOMAIN/$SLUG/"
  exit 0
fi

if [[ "$ACTION" != "upsert" ]]; then
  echo "unknown action: $ACTION" >&2
  exit 2
fi

REF="${2:?git ref required}"
REF="${REF#origin/}"
SLUG="$(slugify "${3:-$REF}")"
if [[ -z "$SLUG" || "$SLUG" == "main" || "$SLUG" == "master" ]]; then
  echo "refusing slug='$SLUG'" >&2
  exit 2
fi

DIR="$PREVIEWS/$SLUG"
PORT="$(port_for_slug "$SLUG")"
mkdir -p "$DIR"

if [[ ! -d "$DIR/repo/.git" ]]; then
  git clone "$GIT_URL" "$DIR/repo"
fi

cd "$DIR/repo"
git remote set-url origin "$GIT_URL"
git fetch --prune origin
if git rev-parse --verify "${REF}^{commit}" >/dev/null 2>&1; then
  git checkout --force "$REF"
elif git rev-parse --verify "origin/${REF}^{commit}" >/dev/null 2>&1; then
  git checkout --force -B "$SLUG" "origin/$REF"
else
  echo "ref not found: $REF" >&2
  exit 1
fi
git reset --hard HEAD

stop_preview "$DIR"
fuser -k "${PORT}/tcp" 2>/dev/null || true
export DATABASE_PATH="$DIR/pickup_box.db"
export CORS_ORIGINS="*"
export PUBLIC_BASE_URL="https://$DOMAIN"
export PUBLIC_PATH_PREFIX="/$SLUG"
export PUBLIC_URL="https://$DOMAIN/$SLUG"

if [[ -f display/app.py && -d backend ]]; then
  nohup "$UV" run --with fastapi --with uvicorn --with qrcode --with pillow python display/app.py "$PORT" >"$DIR/preview.log" 2>&1 &
elif [[ -f backend/main.py && -f frontend/package.json ]]; then
  (cd frontend && npm install --silent && npm run build)
  cat > "$DIR/run.py" <<PY
import os, sys
from pathlib import Path
repo = Path("$DIR/repo")
os.environ.setdefault("DATABASE_PATH", "$DIR/pickup_box.db")
os.environ.setdefault("CORS_ORIGINS", "*")
os.environ.setdefault("PUBLIC_BASE_URL", "https://$DOMAIN")
os.environ.setdefault("PUBLIC_PATH_PREFIX", "/$SLUG")
os.chdir(repo / "backend")
sys.path.insert(0, str(repo / "backend"))
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import main as backend_main
app = backend_main.app
app.router.routes[:] = [
    r for r in app.router.routes
    if not (getattr(r, "path", None) == "/" and getattr(r, "methods", None) == {"GET"})
]
dist = repo / "frontend" / "dist"
@app.get("/", include_in_schema=False)
def spa_index():
    return FileResponse(dist / "index.html")
app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")
import uvicorn
uvicorn.run(app, host="0.0.0.0", port=$PORT)
PY
  nohup "$UV" run --with fastapi --with uvicorn --with python-multipart python "$DIR/run.py" >"$DIR/preview.log" 2>&1 &
elif [[ -d display ]]; then
  nohup python3 -m http.server "$PORT" --directory display >"$DIR/preview.log" 2>&1 &
elif [[ -d interface ]]; then
  nohup python3 -m http.server "$PORT" --directory interface >"$DIR/preview.log" 2>&1 &
elif [[ -d frontend ]]; then
  (cd frontend && npm install --silent && npm run build)
  nohup python3 -m http.server "$PORT" --directory frontend/dist >"$DIR/preview.log" 2>&1 &
else
  nohup python3 -m http.server "$PORT" --directory . >"$DIR/preview.log" 2>&1 &
fi
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
  "url": "https://$DOMAIN/$SLUG/",
}
Path("$DIR/meta.json").write_text(json.dumps(meta, indent=2) + "\n")
print(json.dumps(meta))
PY

ok=0
for i in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$PORT/" >/dev/null 2>&1 || curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    ok=1; break
  fi
  sleep 0.5
done
if [[ "$ok" != "1" ]]; then
  echo "preview failed to become ready; last log:" >&2
  tail -n 40 "$DIR/preview.log" >&2 || true
  exit 1
fi

ensure_routes
echo "preview https://$DOMAIN/$SLUG/ (pickup https://$DOMAIN/$SLUG/pickup/BOX-01)" 
