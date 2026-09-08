"""The character bars drawn in the tray menu.

The menu font is proportional, so a pair whose glyphs have different advance
widths comes out ragged - the bar wobbles as it fills. Every pair offered here
was measured with Pango in the panel font first; `◼◻` and `▮▯` were dropped for
failing that, and `▰▱` for being slanted even though its widths do match.

Emoji are roughly 1.6x the width of a text glyph, so the coloured styles get
fewer cells for the same visual length - see `cells()`.
"""
from __future__ import annotations

# "full" is used for every state; a style that names states instead paints the
# fill with the state's own colour. "partial" opts into fractional fill: the
# eighth-block glyphs share one advance width, so the last cell can carry eight
# steps of resolution without the bar changing length.
STYLES: dict[str, dict] = {
    "blocks":       {"empty": "░", "full": "█"},
    "shade":        {"empty": "░", "full": "▓"},
    "fine":         {"empty": "░", "full": "█", "partial": "▏▎▍▌▋▊▉"},
    "dots":         {"empty": "○", "full": "●"},
    "squares":      {"empty": "□", "full": "■"},
    "line":         {"empty": "┄", "full": "━"},
    "braille":      {"empty": "⣀", "full": "⣿"},
    "color_blocks": {"empty": "⬛", "ok": "🟩", "warn": "🟨", "crit": "🟥", "idle": "⬛"},
    "color_dots":   {"empty": "⚫", "ok": "🟢", "warn": "🟡", "crit": "🔴", "idle": "⚫"},
}

ORDER = tuple(STYLES)
# the name the coloured blocks had before there was more than one coloured style
ALIASES = {"emoji": "color_blocks"}
WIDE = ("color_blocks", "color_dots")
DEFAULT = "blocks"


def canonical(style: str | None) -> str:
    """The style actually stored, resolving an old name or an unknown one."""
    name = ALIASES.get(style or "", style or "")
    return name if name in STYLES else DEFAULT


def cells(style: str | None, wide: int = 10, narrow: int = 18) -> int:
    """How many characters wide a bar should be in this style."""
    return wide if canonical(style) in WIDE else narrow


def render(pct: float | None, width: int, style: str | None, state: str = "ok") -> str:
    spec = STYLES[canonical(style)]
    empty = spec["empty"]
    if pct is None:
        return empty * width
    full = spec.get(state) or spec.get("full") or spec["ok"]
    exact = min(max(pct, 0.0), 100.0) / 100 * width
    partial = spec.get("partial")
    if not partial:
        filled = int(round(exact))
        return full * filled + empty * (width - filled)
    filled = int(exact)
    bar = full * filled
    rest = exact - filled
    if filled < width and rest > 0:
        step = int(rest * (len(partial) + 1))
        if step:
            bar += partial[step - 1]
            filled += 1
    return bar + empty * (width - filled)


def sample(style: str, pct: float = 62.0, width: int = 8) -> str:
    """A short bar for a settings menu, so the choice is visible."""
    return render(pct, cells(style, wide=5, narrow=width), style)
