"""Claude Code sessions that are alive right now.

Each CLI instance writes <account>/sessions/<pid>.json. The file survives a
kill -9, so every entry is validated against /proc: the pid must exist AND its
starttime must match, which rules out a recycled pid.

A session belongs to the account whose directory it was found in - that is the
only way to tell a company CLI from a personal one, since the process itself
looks identical.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .accounts import Account, primary


def _proc_starttime(pid: int) -> str | None:
    try:
        stat = Path(f"/proc/{pid}/stat").read_bytes()
    except OSError:
        return None
    # field 22 (starttime) comes after the parenthesised comm, which may hold spaces
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


def live_sessions(account: Account | None = None) -> list[dict]:
    acct = account if account is not None else primary()
    sessions_dir = acct.sessions_dir
    out: list[dict] = []
    if not sessions_dir.exists():
        return out
    now = time.time()
    for path in sessions_dir.glob("*.json"):
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
            continue  # pid recycled by another process
        if "claude" not in _cmdline(pid):
            continue
        started = (d.get("startedAt") or 0) / 1000
        updated = (d.get("statusUpdatedAt") or d.get("updatedAt") or 0) / 1000
        out.append({
            "account": acct.id,
            "account_label": acct.title,
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
