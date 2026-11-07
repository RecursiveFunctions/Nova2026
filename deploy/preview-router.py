#!/usr/bin/env python3
"""Path-based reverse proxy for NOVA production + branch previews.

Listens on :8090 for novabox.recursivefunctions.dev:
  /                 -> production (:8081)
  /p/<slug>/...     -> branch preview port from routes.json (prefix stripped)
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
PREFIX = "/p/"

_routes: dict = {}


def load_routes(_signum=None, _frame=None) -> None:
    global _routes
    if ROUTES_PATH.is_file():
        _routes = json.loads(ROUTES_PATH.read_text())
    else:
        _routes = {}
    print(f"preview-router: loaded {len(_routes)} routes from {ROUTES_PATH}", flush=True)


def resolve_upstream(path: str) -> tuple[int, str]:
    """Return (port, rewritten_path)."""
    if path.startswith(PREFIX):
        rest = path[len(PREFIX) :]
        slug, _, remainder = rest.partition("/")
        if slug and slug in _routes:
            rewritten = "/" + remainder if remainder or path.endswith("/") or remainder == "" else "/"
            if remainder == "" and not path.endswith("/"):
                # /p/slug with no trailing slash -> treat as /
                rewritten = "/"
            elif remainder == "" and path.endswith("/"):
                rewritten = "/"
            else:
                rewritten = "/" + remainder
            return int(_routes[slug]["port"]), rewritten
    return PROD_PORT, path


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)

    def _proxy(self):
        parts = urlsplit(self.path)
        port, rewritten = resolve_upstream(parts.path)
        # Redirect /p/<slug> -> /p/<slug>/
        if parts.path.startswith(PREFIX):
            rest = parts.path[len(PREFIX) :]
            slug, sep, rem = rest.partition("/")
            if slug and slug in _routes and sep == "" and rem == "":
                loc = f"{PREFIX}{slug}/"
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
