"""Icone da bandeja: anel de progresso desenhado em tempo real."""
from __future__ import annotations

import math
from pathlib import Path

import cairo

from .collector import DATA_DIR

ICON_DIR = DATA_DIR / "icons"
SIZE = 64

PALETTE = {
    "ok":   (0.31, 0.66, 0.48),
    "warn": (0.85, 0.64, 0.25),
    "crit": (0.85, 0.34, 0.34),
    "idle": (0.55, 0.58, 0.65),
}


def state_for(pct: float | None, warn: float, crit: float) -> str:
    if pct is None:
        return "idle"
    if pct >= crit:
        return "crit"
    if pct >= warn:
        return "warn"
    return "ok"


def render(pct: float | None, state: str, seq: int) -> str:
    """Gera o PNG e devolve o nome (sem extensao) para o AppIndicator.

    O nome muda a cada render porque o indicador ignora um arquivo cujo
    nome nao mudou - e o cache dele nao percebe reescrita no mesmo path.
    """
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    for old in ICON_DIR.glob("cc-cockpit-*.png"):
        old.unlink(missing_ok=True)

    name = f"cc-cockpit-{seq % 1000}"
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, SIZE, SIZE)
    ctx = cairo.Context(surf)
    cx = cy = SIZE / 2
    r = SIZE / 2 - 7
    lw = 8.0
    ctx.set_line_width(lw)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)

    ctx.set_source_rgba(0.55, 0.58, 0.65, 0.30)
    ctx.arc(cx, cy, r, 0, 2 * math.pi)
    ctx.stroke()

    p = 0.0 if pct is None else max(0.0, min(100.0, pct)) / 100
    if p > 0:
        cr, cg, cb = PALETTE[state]
        ctx.set_source_rgb(cr, cg, cb)
        ctx.arc(cx, cy, r, -math.pi / 2, -math.pi / 2 + 2 * math.pi * p)
        ctx.stroke()

    cr, cg, cb = PALETTE[state]
    ctx.set_source_rgba(cr, cg, cb, 0.9)
    ctx.arc(cx, cy, 7.5, 0, 2 * math.pi)
    ctx.fill()

    surf.write_to_png(str(ICON_DIR / f"{name}.png"))
    return name
