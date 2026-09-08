"""Window anchors taken from Claude Code's own usage panel.

Two things cannot be derived from local transcripts:

  1. The limit belongs to the account, not to the CLI. Anything consumed in the
     Claude app counts against the same window and leaves nothing on disk, so a
     window can start before the first local request.
  2. The weekly limit is a fixed window with its own reset time, not the rolling
     7 days a local reader would assume.

So the panel's "resets in ..." is recorded here and used as the source of truth
while it lasts. A block anchor simply expires; a weekly anchor rolls forward in
7-day steps, since the reset time repeats.
"""
from __future__ import annotations

import json
import re
import time

from .accounts import Account, primary

WEEK = 7 * 86400.0

_DURATION = re.compile(r"(\d+(?:[.,]\d+)?)\s*([dhms])", re.I)
_UNITS = {"d": 86400.0, "h": 3600.0, "m": 60.0, "s": 1.0}


def parse_duration(text: str) -> float:
    """Accepts '1h55', '1 h 55 min', '115m', '2h', '90'. Returns seconds."""
    text = text.strip().lower().replace("min", "m")
    parts = _DURATION.findall(text)
    if parts:
        total = sum(float(v.replace(",", ".")) * _UNITS[u] for v, u in parts)
        # '1h55' -> the trailing number has no unit and means minutes
        tail = re.search(r"(\d+)\s*$", text)
        if tail and not re.search(r"[dhms]\s*$", text):
            total += float(tail.group(1)) * 60
        return total
    if text.replace(".", "").isdigit():
        return float(text) * 60      # a bare number is minutes
    raise ValueError(f"could not read the duration: {text!r}")


def _file(account: Account | None):
    return (account if account is not None else primary()).path("anchors.json")


def load(account: Account | None = None) -> dict:
    try:
        return json.loads(_file(account).read_text())
    except (OSError, ValueError):
        return {}


def save(data: dict, account: Account | None = None) -> None:
    path = _file(account)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def set_block_end(epoch: float, account: Account | None = None) -> None:
    data = load(account)
    data["block_end"] = epoch
    data["block_set_at"] = time.time()
    save(data, account)


def set_week_end(epoch: float, account: Account | None = None) -> None:
    data = load(account)
    data["week_end"] = epoch
    data["week_set_at"] = time.time()
    save(data, account)


def block_end(now: float | None = None, account: Account | None = None) -> float | None:
    """End of the anchored block, or None once it has passed."""
    now = now or time.time()
    end = load(account).get("block_end")
    return end if end and end > now else None


def week_window(now: float | None = None,
                account: Account | None = None) -> tuple[float, float] | None:
    """Current weekly window, rolled forward from the anchored reset."""
    now = now or time.time()
    end = load(account).get("week_end")
    if not end:
        return None
    while end <= now:
        end += WEEK
    return end - WEEK, end


def clear(which: str | None = None, account: Account | None = None) -> None:
    data = load(account)
    for key in (("block", "week") if which is None else (which,)):
        data.pop(f"{key}_end", None)
        data.pop(f"{key}_set_at", None)
    save(data, account)
