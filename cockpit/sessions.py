"""Sessoes do Claude Code vivas neste momento.

~/.claude/sessions/<pid>.json e escrito por cada instancia do CLI. O arquivo
sobrevive a um kill -9, entao cada entrada e validada contra /proc: o pid tem
que existir E o starttime tem que bater (evita pid reciclado).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .collector import CLAUDE_DIR

SESSIONS_DIR = CLAUDE_DIR / "sessions"


def _proc_starttime(pid: int) -> str | None:
    try:
        stat = Path(f"/proc/{pid}/stat").read_bytes()
    except OSError:
        return None
    # o campo 22 (starttime) vem depois do comm entre parenteses, que pode ter espacos
    tail = stat[stat.rfind(b")") + 2 :].split()
    try:
        return tail[19].decode()
    except IndexError:
        return None


def _cmdline(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="replace").strip()
    except OSError:
        return ""


def _rss_mb(pid: int) -> float:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0.0


def live_sessions() -> list[dict]:
    out: list[dict] = []
    if not SESSIONS_DIR.exists():
        return out
    now = time.time()
    for path in SESSIONS_DIR.glob("*.json"):
        try:
            d = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        pid = d.get("pid")
        if not isinstance(pid, int):
            continue
        st = _proc_starttime(pid)
        if st is None:
            continue
        want = str(d.get("procStart") or "")
        if want and st != want:
            continue  # pid reciclado por outro processo
        if "claude" not in _cmdline(pid):
            continue
        started = (d.get("startedAt") or 0) / 1000
        updated = (d.get("statusUpdatedAt") or d.get("updatedAt") or 0) / 1000
        out.append({
            "pid": pid,
            "session_id": d.get("sessionId") or "",
            "name": d.get("name") or f"pid {pid}",
            "cwd": d.get("cwd") or "",
            "status": d.get("status") or "?",
            "kind": d.get("kind") or "",
            "entrypoint": d.get("entrypoint") or "",
            "version": d.get("version") or "",
            "started_at": started,
            "uptime_s": max(0.0, now - started) if started else 0.0,
            "idle_s": max(0.0, now - updated) if updated else 0.0,
            "rss_mb": round(_rss_mb(pid), 1),
        })
    out.sort(key=lambda s: s["started_at"])
    return out
