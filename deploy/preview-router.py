#!/usr/bin/env python3
"""Path-based reverse proxy for NOVA production + branch previews.

Listens on :8090 for novabox.recursivefunctions.dev:
  /                      -> production (:8081)
  /<slug>/...            -> branch preview (prefix stripped)
  /p/<slug>/...          -> legacy alias (308 to /<slug>/...)
"""
from __future__ import annotations

import json
import os
import signal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

ROUTES_PATH = Path(os.environ.get("NOVA_ROUTES", "/home/ray/apps/nova2026/previews/routes.json"))
LISTEN_HOST = os.environ.get("NOVA_PREVIEW_ROUTER_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("NOVA_PREVIEW_ROUTER_PORT", "8090"))
PROD_PORT = int(os.environ.get("NOVA_PROD_PORT", "8081"))

# First path segments that always belong to production (never a branch slug).
RESERVED = frozenset({
    "boxes", "pickup", "orders", "demo", "health", "docs", "openapi.json",
    "screen", "simulator", "courier", "customer", "assets", "api", "static",
    "favicon.ico", "script.js", "style.css", "index.html", "order_qr.png", "p",
})

_routes: dict = {}


def load_routes(_signum=None, _frame=None) -> None:
    global _routes
    if ROUTES_PATH.is_file():
        _routes = json.loads(ROUTES_PATH.read_text())
    else:
        _routes = {}
    print(f"preview-router: loaded {len(_routes)} routes from {ROUTES_PATH}", flush=True)


def match_preview(path: str) -> tuple[str, str] | None:
    """Return (slug, remainder_path) if path targets a known preview."""
    if path.startswith("/p/"):
        rest = path[3:]
        slug, _, remainder = rest.partition("/")
        if slug and slug in _routes:
            return slug, ("/" + remainder if remainder else "/")
        return None
    if not path.startswith("/") or path == "/":
        return None
    first, _, remainder = path[1:].partition("/")
    if not first or first in RESERVED or first not in _routes:
        return None
    return first, ("/" + remainder if remainder else "/")


def resolve_upstream(path: str) -> tuple[int, str, str | None]:
    """Return (port, rewritten_path, branch_slug_or_None)."""
    hit = match_preview(path)
    if hit:
        slug, rewritten = hit
        return int(_routes[slug]["port"]), rewritten, slug
    return PROD_PORT, path, None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)

    def _proxy(self):
        parts = urlsplit(self.path)
        path = parts.path or "/"

        # Legacy /p/<slug> -> /<slug>/
        if path.startswith("/p/"):
            rest = path[3:]
            slug, sep, rem = rest.partition("/")
            if slug and slug in _routes:
                loc = f"/{slug}/" + rem
                if not rem and not path.endswith("/"):
                    loc = f"/{slug}/"
                if parts.query:
                    loc += "?" + parts.query
                self.send_response(308)
                self.send_header("Location", loc)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

        port, rewritten, slug = resolve_upstream(path)

        # Unknown /<maybe-slug>/... that isn't reserved and isn't a route -> 404
        if path.startswith("/") and path != "/":
            first = path[1:].split("/", 1)[0]
            if first and first not in RESERVED and first not in _routes and slug is None:
                # Could be a missing preview, or a prod deep link we don't know.
                # Only 404 when it looks like /something/pickup/... or a bare /something/
                rest = path[1 + len(first):]
                if rest.startswith("/pickup") or rest in ("", "/"):
                    body = ("unknown preview: /%s\n" % first).encode()
                    self.send_response(404)
                    self.send_header("Content-Type", "text/plain")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

        # Redirect /<slug> -> /<slug>/
        if slug and (path == f"/{slug}"):
            loc = f"/{slug}/"
            if parts.query:
                loc += "?" + parts.query
            self.send_response(308)
            self.send_header("Location", loc)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        new_path = urlunsplit(("", "", rewritten, parts.query, parts.fragment))
        url = f"http://127.0.0.1:{port}{new_path}"
        length = int(self.headers.get("Content-Length", "0") or 0)
        payload = self.rfile.read(length) if length else None
        headers = {
            k: v
            for k, v in self.headers.items()
            if k.lower() not in {"host", "content-length", "connection", "transfer-encoding"}
        }
        headers["Host"] = f"127.0.0.1:{port}"
        if slug:
            headers["X-Forwarded-Prefix"] = f"/{slug}"
        req = Request(url, data=payload, headers=headers, method=self.command)
        try:
            with urlopen(req, timeout=60) as resp:
                data = resp.read()
                self.send_response(resp.status)
                for k, v in resp.headers.items():
                    if k.lower() in {"transfer-encoding", "connection", "content-encoding"}:
                        continue
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(data)
        except HTTPError as exc:
            data = exc.read()
            self.send_response(exc.code)
            self.send_header("Content-Type", exc.headers.get("Content-Type", "text/plain"))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)
        except URLError as exc:
            body = ("upstream down: %s\n" % exc).encode()
            self.send_response(502)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

    def do_GET(self):
        self._proxy()

    def do_POST(self):
        self._proxy()

    def do_PUT(self):
        self._proxy()

    def do_PATCH(self):
        self._proxy()

    def do_DELETE(self):
        self._proxy()

    def do_OPTIONS(self):
        self._proxy()

    def do_HEAD(self):
        self._proxy()


def main() -> None:
    load_routes()
    signal.signal(signal.SIGHUP, load_routes)
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler)
    print(f"preview-router listening on {LISTEN_HOST}:{LISTEN_PORT} (prod :{PROD_PORT})", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
