"""Local dashboard. Serves web/index.html and the JSON API on 127.0.0.1."""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config
from .stats import summary

# inside the package, so it survives a wheel install
WEB_DIR = Path(__file__).resolve().parent / "web"
_CACHE: dict = {"at": 0.0, "data": None}
_LOCK = threading.Lock()


def cached_summary(max_age: float = 5.0) -> dict:
    with _LOCK:
        if _CACHE["data"] is None or time.time() - _CACHE["at"] > max_age:
            _CACHE["data"] = summary(cfg=config.load())
            _CACHE["at"] = time.time()
        return _CACHE["data"]


class Handler(BaseHTTPRequestHandler):
    server_version = "cc-cockpit"

    def log_message(self, *args) -> None:  # silence the per-request log
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        try:
            if path == "/api/summary":
                self._send(200, json.dumps(cached_summary()).encode(), "application/json")
            elif path == "/api/config":
                self._send(200, json.dumps(config.load()).encode(), "application/json")
            elif path in ("/", "/index.html"):
                body = (WEB_DIR / "index.html").read_bytes()
                self._send(200, body, "text/html; charset=utf-8")
            else:
                self._send(404, b"not found", "text/plain; charset=utf-8")
        except Exception as exc:
            # an unhandled error used to drop the connection with no response,
            # which looks like "server is down" instead of "server is broken"
            message = f"cc-cockpit: {type(exc).__name__}: {exc}"
            self._send(500, message.encode(), "text/plain; charset=utf-8")


def serve(port: int | None = None, open_browser: bool = False) -> None:
    cfg = config.ensure()
    port = port or int(cfg.get("dashboard_port") or 8765)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"cc-cockpit at {url}  (ctrl-c to stop)")
    if open_browser:
        import webbrowser
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
