"""Official rate-limit numbers, captured from Claude Code's statusline payload.

Claude Code pipes a JSON document into the statusline command on every render,
and it carries the real subscription windows:

    "rate_limits": {
      "five_hour": {"used_percentage": number, "resets_at": epoch},
      "seven_day": {"used_percentage": number, "resets_at": epoch}
    }

Reading it here means no token, no undocumented endpoint and no guessing:
these are the same numbers the plan panel shows, including whatever was consumed
in the Claude app, which never touches the local transcripts.

The snapshot only refreshes while a CLI session is rendering. That is enough:
what is not running cannot be consuming, and `resets_at` stays valid on its own.

These numbers belong to one account. With two accounts on the machine a single
snapshot file would mean the last CLI to render wins, and the tray would show a
percentage from the wrong subscription with nothing to reveal the swap - so the
snapshot lives under the account, and `cc-cockpit statusline --account` says
which one is talking.
"""
from __future__ import annotations

import json
import time

from .accounts import Account, primary

WINDOWS = {"block": "five_hour", "week": "seven_day"}


def _account(account: Account | None) -> Account:
    return account if account is not None else primary()


def snapshot_path(account: Account | None = None):
    return _account(account).path("panel.json")


def history_path(account: Account | None = None):
    return _account(account).path("panel-history.ndjson")


def load(account: Account | None = None) -> dict:
    try:
        return json.loads(snapshot_path(account).read_text())
    except (OSError, ValueError):
        return {}


def window(name: str, now: float | None = None, snapshot: dict | None = None,
           account: Account | None = None) -> dict | None:
    """Official data for 'block' or 'week', or None when absent or expired."""
    now = now or time.time()
    snap = snapshot if snapshot is not None else load(account)
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


def history(account: Account | None = None, since: float | None = None) -> list[dict]:
    """The official percentages over time, oldest first.

    Samples land only while a CLI is rendering a statusline, so the series is
    sparse by nature - a gap means nothing was running, which is also when
    nothing was being consumed.

    Each row carries the window it belongs to. A window that resets starts over
    at zero, and joining across that boundary would draw a fall that never
    happened, so the reader is given `block_resets_at` to break the line on.
    """
    rows: list[dict] = []
    try:
        with history_path(account).open(errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and (since is None or row.get("at", 0) >= since):
                    rows.append(row)
    except OSError:
        return []
    rows.sort(key=lambda r: r.get("at", 0))
    return rows


def contexts(snapshot: dict | None = None, account: Account | None = None) -> dict:
    snap = snapshot if snapshot is not None else load(account)
    return snap.get("sessions") or {}


def record(payload: dict, account: Account | None = None) -> dict:
    """Stores one statusline payload for an account. Returns the merged snapshot."""
    acct = _account(account)
    acct.data_dir.mkdir(parents=True, exist_ok=True)
    now = time.time()
    snap = load(acct)
    limits = payload.get("rate_limits") or {}
    if limits:
        snap["rate_limits"] = limits
        snap["at"] = now
        _append_history(acct, now, limits)

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

    path = snapshot_path(acct)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(snap))
    tmp.replace(path)
    return snap


def _append_history(acct: Account, now: float, limits: dict) -> None:
    """One line per change, so the official curve can be plotted later."""
    history = history_path(acct)
    row = {"at": round(now, 1)}
    for key, source in WINDOWS.items():
        data = limits.get(source) or {}
        if data:
            row[key] = round(float(data.get("used_percentage") or 0), 2)
            row[f"{key}_resets_at"] = data.get("resets_at")
    if len(row) == 1:
        return
    try:
        with history.open() as fh:
            last = None
            for line in fh:
                last = line
        if last:
            prev = json.loads(last)
            if all(prev.get(k) == row.get(k) for k in ("block", "week")):
                return   # nothing changed
    except (OSError, ValueError):
        pass
    with history.open("a") as fh:
        fh.write(json.dumps(row, separators=(",", ":")) + "\n")
