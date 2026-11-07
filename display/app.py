"""Serve the box display frontend together with the backend API on ONE port.

The phone display opens https://novabox.recursivefunctions.dev/ and must reach both the
static files (index.html/script.js/style.css) and the API (/boxes/{id}, /pickup/{id}),
so this single server mounts the display directory at / and the FastAPI app under it.

Run (deps resolved by uv, from backend/ or anywhere):
    uv run --with fastapi --with uvicorn python display/app.py

Display URL:            http://localhost:8081/  (add ?box=BOX-02 for the second box)
API (same origin):      http://localhost:8081/boxes/BOX-01
Public (via tunnel):    https://novabox.recursivefunctions.dev/  (see display/serve.sh)
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent          # <repo>/display
REPO_DIR = BASE_DIR.parent
BACKEND_DIR = REPO_DIR / "backend"
DEFAULT_PORT = 8081


def _init_backend() -> None:
    os.chdir(BACKEND_DIR)                # config.py/.env/data resolve relative to backend/
    sys.path.insert(0, str(BACKEND_DIR))
    import db
    import logic
    db.init_db()
    with db.write_tx() as conn:
        logic.seed_defaults(conn)
        logic.allocate_boxes(conn)


def build_app():
    _init_backend()
    import main as backend_main          # backend FastAPI app (imported after chdir/sys.path)
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    app = backend_main.app

    # backend main.py registers GET / as JSON; drop it so phones get the display shell.
    app.router.routes[:] = [
        r for r in app.router.routes
        if not (getattr(r, "path", None) == "/" and getattr(r, "methods", None) == {"GET"})
    ]

    @app.get("/", include_in_schema=False)
    def display_index():
        return FileResponse(BASE_DIR / "index.html")

    # API routes stay authoritative; static assets are the fallback mount at /.
    app.mount("/", StaticFiles(directory=str(BASE_DIR), html=True), name="display")
    return app


def main() -> None:
    import uvicorn
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    print(f"NOVA display + API: http://0.0.0.0:{port}/ (display={BASE_DIR}, api=/boxes,/pickup,/orders)", flush=True)
    uvicorn.run(build_app(), host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()