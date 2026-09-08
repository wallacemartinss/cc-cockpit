"""Calibrating the reference ceiling against the percentage Claude Code reports.

Anthropic does not publish the plan limit, and the weighting behind its
percentage is not documented. But the CLI does show a percentage, so one sample
of (consumption now, percentage now) implies a ceiling. Several samples, and the
median of them, absorb the noise of typing the number a moment later.

The implied ceiling is only as stable as the weighting: it holds while the model
mix stays roughly the same, which is the usual case for one person's workflow.

The official panel reports **whole** percentages, and that is the dominant error
here. Reading "7%" means the truth is somewhere in [6.5, 7.5), so one reading
pins the ceiling only to within ±0.5/7 - about ±7%. At 2% it is ±25%. Two
instances of this tool, on the same consumption, printed ceilings $447 apart
because one had sampled a percentage point earlier.

Two consequences, both handled here: readings below MIN_PCT are too coarse to
store at all, and what survives is reported with `precision()` so nobody prints
centavos on a number that is uncertain by hundreds.

Samples are strictly per account. A Max plan and a Pro plan imply ceilings an
order of magnitude apart, and one median over both would be wrong for each.
"""
from __future__ import annotations

import json
import time

from .accounts import Account, primary

KEEP = 20
WINDOWS = ("block", "week")
# Below this the whole-percentage rounding swamps the estimate: at 5% a reading
# pins the ceiling to ±10%, at 2% to ±25%. Not worth remembering.
MIN_PCT = 5.0


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
    # written from summary() now, which the tray and the dashboard both call:
    # a torn file would be read back as "no samples at all"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


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
    """Weighted median of the implied ceilings, weighted by percentage.

    A plain median treats every sample alike, and they are not alike: a reading
    at 23% pins the ceiling eight times tighter than one at 3%. Measured on real
    data, the unweighted median let a stale 3% sample drag the weekly figure
    from $2,723 to $4,200 - worse than the single instantaneous reading it was
    meant to improve on. Weighting by percentage is exactly the "trust the
    sharper reading" rule, and it keeps the median's resistance to one outlier.
    """
    samples = [s for s in data_for(window, data, account)
               if s.get("implied") and s.get("pct")]
    if not samples:
        return None
    samples.sort(key=lambda s: s["implied"])
    half = sum(s["pct"] for s in samples) / 2
    running = 0.0
    for sample in samples:
        running += sample["pct"]
        if running >= half:
            return round(sample["implied"], 2)
    return round(samples[-1]["implied"], 2)


def data_for(window: str, data: dict | None = None,
             account: Account | None = None) -> list:
    return (data if data is not None else load(account)).get(window, [])


def clear(window: str | None = None, account: Account | None = None) -> None:
    data = load(account)
    for w in (WINDOWS if window is None else (window,)):
        data[w] = []
    save(data, account)


def observe(window: str, usd: float, pct: float, window_end: float,
            account: Account | None = None) -> None:
    """Records what the official panel is reporting right now, once per reading.

    The manual `sync` path exists because someone had to read a percentage off
    the CLI and type it in. The statusline hands us the same pair for free on
    every render - so the samples that were being watched go by and discarded
    are simply kept.

    Deduplicated on (percentage, window): the panel holds a reading for a while,
    and storing it a hundred times would let one moment outvote every other.
    """
    pct = round(pct, 1)          # the payload carries 7.000000000000001
    if window not in WINDOWS or pct < MIN_PCT or usd <= 0:
        return
    data = load(account)
    for sample in data.get(window, []):
        # round both sides: samples written before the payload noise was trimmed
        # still hold 7.000000000000001, and must not read as a different reading
        if (round(sample.get("pct") or 0, 1) == pct
                and sample.get("window_end") == window_end):
            return
    data[window].append({"at": time.time(), "usd": round(usd, 4), "pct": pct,
                         "implied": round(usd / (pct / 100), 2),
                         "window_end": window_end, "auto": True})
    data[window] = data[window][-KEEP:]
    save(data, account)


def precision(window: str, data: dict | None = None,
              account: Account | None = None) -> float | None:
    """How wrong the ceiling can be, as a fraction, from the best sample held.

    Whole-percentage rounding gives each reading a relative error of 0.5/pct.
    """
    data = data if data is not None else load(account)
    samples = [s for s in data.get(window, []) if s.get("pct") and s.get("implied")]
    if not samples:
        return None
    chosen = ceiling(window, data)
    if chosen is None:
        return None
    # the reading the weighted median actually landed on is the one whose error
    # the figure inherits - quoting the sharpest sample would flatter it
    nearest = min(samples, key=lambda s: abs(s["implied"] - chosen))
    return 0.5 / nearest["pct"]


def rounded(value: float, relative_error: float | None) -> float:
    """Drops the digits the estimate does not actually have.

    "$2,675.52" claims centavos on a number uncertain by $385. Rounding to the
    magnitude of its own error says $2,700, which is the honest reading.
    """
    if not value or not relative_error:
        return round(value, 2)
    import math
    step = 10 ** math.floor(math.log10(abs(value) * relative_error))
    return round(round(value / step) * step, 2)
