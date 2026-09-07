"""Official rate-limit numbers, captured from Claude Code's statusline payload.

Claude Code pipes a JSON document into the statusline command on every render,
and it carries the real subscription windows:

    "rate_limits": {
      "five_hour": {"used_percentage": number, "resets_at": epoch},
      "seven_day": {"used_percentage": number, "resets_at": epoch}
    }

Reading it here means no credentials, no undocumented endpoint and no guessing:
these are the same numbers the plan panel shows, including whatever was consumed
in the Claude app, which never touches the local transcripts.

The snapshot only refreshes while a CLI session is rendering. That is enough:
what is not running cannot be consuming, and `resets_at` stays valid on its own.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .collector import DATA_DIR

SNAPSHOT = DATA_DIR / "panel.json"
HISTORY = DATA_DIR / "panel-history.ndjson"
WINDOWS = {"block": "five_hour", "week": "seven_day"}


def load() -> dict:
    try:
        return json.loads(SNAPSHOT.read_text())
    except (OSError, ValueError):
        return {}


def window(name: str, now: float | None = None, snapshot: dict | None = None) -> dict | None:
    """Official data for 'block' or 'week', or None when absent or expired."""
    now = now or time.time()
    snap = snapshot if snapshot is not None else load()
    data = (snap.get("rate_limits") or {}).get(WINDOWS.get(name, name))
    if not data:
        return None
    resets_at = data.get("resets_at")
    if not resets_at or resets_at <= now:
        return None
    return {
        "pct": float(data.get("used_percentage") or 0.0),
        "resets_at": float(resets_at),
        "captured_at": snap.get("at", 0.0),
        "age_s": max(0.0, now - snap.get("at", 0.0)),
    }


def contexts(snapshot: dict | None = None) -> dict:
    snap = snapshot if snapshot is not None else load()
    return snap.get("sessions") or {}


def record(payload: dict) -> dict:
    """Stores one statusline payload. Returns the merged snapshot."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    now = time.time()
    snap = load()
    limits = payload.get("rate_limits") or {}
    if limits:
        snap["rate_limits"] = limits
        snap["at"] = now
        _append_history(now, limits)

    session_id = payload.get("session_id")
    if session_id:
        ctx = payload.get("context_window") or {}
        sessions = snap.setdefault("sessions", {})
        sessions[session_id] = {
            "at": now,
            "model": (payload.get("model") or {}).get("display_name") or "",
            "context_pct": ctx.get("used_percentage"),
            "context_size": ctx.get("context_window_size"),
            "input_tokens": ctx.get("total_input_tokens"),
            "cwd": payload.get("cwd") or "",
            "version": payload.get("version") or "",
        }
        cutoff = now - 24 * 3600
        snap["sessions"] = {k: v for k, v in sessions.items() if v.get("at", 0) > cutoff}

    tmp = SNAPSHOT.with_suffix(".tmp")
    tmp.write_text(json.dumps(snap))
    tmp.replace(SNAPSHOT)
    return snap


def _append_history(now: float, limits: dict) -> None:
    """One line per change, so the official curve can be plotted later."""
    row = {"at": round(now, 1)}
    for key, source in WINDOWS.items():
        data = limits.get(source) or {}
        if data:
            row[key] = round(float(data.get("used_percentage") or 0), 2)
            row[f"{key}_resets_at"] = data.get("resets_at")
    if len(row) == 1:
        return
    try:
        with HISTORY.open() as fh:
            last = None
            for line in fh:
                last = line
        if last:
            prev = json.loads(last)
            if all(prev.get(k) == row.get(k) for k in ("block", "week")):
                return   # nothing changed
    except (OSError, ValueError):
        pass
    with HISTORY.open("a") as fh:
        fh.write(json.dumps(row, separators=(",", ":")) + "\n")
