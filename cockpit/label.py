"""The text beside the tray icon.

No GTK here: the tray paints it, Settings previews every format with the same
function, and both can be tested without a display.

A panel is the most crowded strip on the screen - GNOME ellipsises an indicator
label as soon as the right-hand side fills up - so every format is a choice of
what earns its place there. Whatever a format asks for and the data does not
have (no reset yet, no forecast) simply drops out instead of printing a zero.
"""
from __future__ import annotations

from .i18n import duration, money, number, t

# in the order Settings offers them
FORMATS = ("pct", "pct_cost", "pct_cost_short", "pct_reset", "pct_reset_cost_short",
           "pct_eta", "block_week", "reset", "cost_short", "icon")

# what each format shows, from the window picked in Settings
_PIECES = {
    "pct": ("pct",),
    "pct_cost": ("pct", "cost"),
    "pct_cost_short": ("pct", "cost_short"),
    "pct_reset": ("pct", "reset"),
    "pct_reset_cost_short": ("pct", "reset", "cost_short"),
    "pct_eta": ("pct", "eta"),
    "reset": ("reset",),
    "cost_short": ("cost_short",),
    "icon": (),
}

SEP = " · "


def format_of(cfg: dict) -> str:
    """The chosen format. Until one is picked, the old show-cost switch decides,
    so an upgrade leaves the panel exactly as it was."""
    chosen = cfg.get("tray_label")
    if chosen in FORMATS:
        return chosen
    return "pct_cost" if cfg.get("tray_show_cost", True) else "pct"


def compact_money(usd: float, cfg: dict) -> str:
    """No cents and k past a thousand: $24, $1.2k - or the local currency."""
    local = cfg.get("local_currency") or {}
    value, symbol = usd, "$"
    if local.get("rate") and local.get("symbol"):
        value, symbol = usd * float(local["rate"]), f"{local['symbol']} "
    if value >= 1000:
        return f"{symbol}{number(value / 1000, 1)}k"
    return f"{symbol}{number(round(value))}"


def _pct(window: dict | None) -> str | None:
    pct = (window or {}).get("pct")
    return None if pct is None else f"{pct:.0f}%"


def _hits_first(window: dict) -> bool:
    """A forecast only means something when the ceiling comes before the reset."""
    eta, reset = window.get("eta_limit_s"), window.get("remaining_s")
    return bool(eta) and (not reset or eta < reset)


def compose(fmt: str, metric: str, face: dict, multi: bool = False, cfg: dict | None = None) -> str:
    """The label for one account's summary. '' means no text, only the ring."""
    cfg = cfg or {}
    if metric == "none" or fmt == "icon":
        return ""
    if fmt == "block_week":
        # both windows side by side, so the picked one does not apply
        text = f"{_pct(face.get('block')) or '—'} │ {_pct(face.get('week')) or '—'}"
    else:
        window = {"block": face.get("block"), "week": face.get("week"),
                  "today": face.get("today_gauge")}.get(metric) or {}
        bits = []
        for piece in _PIECES.get(fmt, _PIECES["pct_cost"]):
            if piece == "pct":
                bit = _pct(window)
            elif piece == "cost":
                bit = money(window["usd"]) if window.get("usd") is not None else None
            elif piece == "cost_short":
                bit = compact_money(window["usd"], cfg) if window.get("usd") is not None else None
            elif piece == "reset":
                bit = duration(window["remaining_s"]) if window.get("remaining_s") else None
            else:   # eta: when the limit is reached at the current pace
                bit = ("→ " + duration(window["eta_limit_s"])) if _hits_first(window) else None
            if bit:
                bits.append(bit)
        # the arrow reads as a continuation, not as a separate item
        text = SEP.join(bits).replace(f"{SEP}→ ", " → ") or "—"
    if multi:
        text += SEP + face["account"]["label"][:8].strip()
    return text


def title(fmt: str) -> str:
    """The name Settings shows for a format."""
    return t("label_" + fmt)
