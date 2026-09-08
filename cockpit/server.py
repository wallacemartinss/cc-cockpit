"""Local dashboard. Serves web/index.html and the JSON API on 127.0.0.1."""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import accounts, config, panel, stats
from .stats import summary

# inside the package, so it survives a wheel install
WEB_DIR = Path(__file__).resolve().parent / "web"
# one entry per account, plus one for the combined view: a tab switch must not
# invalidate the tab the user just came from
_CACHE: dict[str, dict] = {}
_LOCK = threading.Lock()


def cached_summary(account_id: str | None = None, max_age: float = 5.0) -> dict:
    cfg = config.load()
    if account_id in ("all", stats.ALL_ID):
        key, build = stats.ALL_ID, lambda: stats.combined(cfg)
    else:
        account = accounts.resolve(account_id, cfg)   # raises on an unknown id
        key = account.id
        build = lambda: summary(cfg=cfg, account=account)   # noqa: E731
    with _LOCK:
        entry = _CACHE.get(key)
        if entry is None or time.time() - entry["at"] > max_age:
            entry = {"at": time.time(), "data": build()}
            _CACHE[key] = entry
        return entry["data"]


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
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        try:
            if path == "/api/summary":
                wanted = (query.get("account") or [None])[0]
                try:
                    body = json.dumps(cached_summary(wanted)).encode()
                except ValueError as exc:      # unknown account id in the query
                    self._send(404, str(exc).encode(), "text/plain; charset=utf-8")
                    return
                self._send(200, body, "application/json")
            elif path == "/api/history":
                wanted = (query.get("account") or [None])[0]
                try:
                    account = accounts.resolve(
                        None if wanted in ("all", stats.ALL_ID) else wanted)
                except ValueError as exc:
                    self._send(404, str(exc).encode(), "text/plain; charset=utf-8")
                    return
                days = float((query.get("days") or ["7"])[0] or 7)
                rows = panel.history(account, since=time.time() - days * 86400)
                self._send(200, json.dumps(rows).encode(), "application/json")
            elif path == "/api/accounts":
                self._send(200, json.dumps(stats.overview()).encode(), "application/json")
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
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as exc:
        # the tray runs this in a daemon thread, where an unhandled error is a
        # traceback nobody asked for and an indicator whose dashboard is dead
        print(f"cc-cockpit: port {port} is not available ({exc.strerror or exc}). "
              f"Another instance may already be serving it.")
        return
    url = f"http://127.0.0.1:{port}/"
    print(f"cc-cockpit at {url}  (ctrl-c to stop)")
    if open_browser:
        import webbrowser
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
