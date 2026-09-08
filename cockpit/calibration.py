"""Calibrating the reference ceiling against the percentage Claude Code reports.

Anthropic does not publish the plan limit, and the weighting behind its
percentage is not documented. But the CLI does show a percentage, so one sample
of (consumption now, percentage now) implies a ceiling. Several samples, and the
median of them, absorb the noise of typing the number a moment later.

The implied ceiling is only as stable as the weighting: it holds while the model
mix stays roughly the same, which is the usual case for one person's workflow.

Samples are strictly per account. A Max plan and a Pro plan imply ceilings an
order of magnitude apart, and one median over both would be wrong for each.
"""
from __future__ import annotations

import json
import time
from statistics import median

from .accounts import Account, primary

KEEP = 20
WINDOWS = ("block", "week")


def _file(account: Account | None):
    return (account if account is not None else primary()).path("calibration.json")


def load(account: Account | None = None) -> dict:
    try:
        data = json.loads(_file(account).read_text())
    except (OSError, ValueError):
        return {w: [] for w in WINDOWS}
    return {w: list(data.get(w, [])) for w in WINDOWS}


def save(data: dict, account: Account | None = None) -> None:
    path = _file(account)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def add(window: str, usd: float, pct: float, account: Account | None = None) -> float:
    """Records a sample and returns the newly implied ceiling."""
    if window not in WINDOWS:
        raise ValueError(f"window must be one of {WINDOWS}")
    if not 0 < pct <= 100:
        raise ValueError("the percentage must be between 0 and 100")
    data = load(account)
    implied = usd / (pct / 100)
    data[window].append({"at": time.time(), "usd": round(usd, 4),
                         "pct": pct, "implied": round(implied, 2)})
    data[window] = data[window][-KEEP:]
    save(data, account)
    return ceiling(window, data)


def ceiling(window: str, data: dict | None = None,
            account: Account | None = None) -> float | None:
    data = data if data is not None else load(account)
    values = [s["implied"] for s in data.get(window, []) if s.get("implied")]
    return round(median(values), 2) if values else None


def clear(window: str | None = None, account: Account | None = None) -> None:
    data = load(account)
    for w in (WINDOWS if window is None else (window,)):
        data[w] = []
    save(data, account)
