"""Price table (USD per 1M tokens) and API-equivalent cost.

Cache rules (Anthropic docs):
  cache write 5m  = 1.25x input
  cache write 1h  = 2.00x input
  cache read      = 0.10x input  (0.025x on Fable 5.1)

Subscriptions (Pro/Max) are not billed per token; the cost here is the
"API-equivalent value" - a weight unit for usage, and a way to see how much
the plan is saving.
"""
from __future__ import annotations

# model -> (input, output, cache_read_mult)
_MODELS: dict[str, tuple[float, float, float]] = {
    "claude-fable-5-1":   (10.0, 50.0, 0.025),
    "claude-mythos-5-1":  (10.0, 50.0, 0.025),
    "claude-fable-5":     (10.0, 50.0, 0.10),
    "claude-opus-5":      (5.0,  25.0, 0.10),
    "claude-opus-4-8":    (5.0,  25.0, 0.10),
    "claude-opus-4-7":    (5.0,  25.0, 0.10),
    "claude-opus-4-6":    (5.0,  25.0, 0.10),
    "claude-sonnet-5":    (2.0,  10.0, 0.10),
    "claude-sonnet-4-6":  (3.0,  15.0, 0.10),
    "claude-haiku-4-5":   (1.0,   5.0, 0.10),
}

WRITE_5M_MULT = 1.25
WRITE_1H_MULT = 2.00

# family fallback, for models released after this table was written
_FAMILY_FALLBACK = (
    ("fable", "claude-fable-5-1"),
    ("mythos", "claude-mythos-5-1"),
    ("opus", "claude-opus-5"),
    ("sonnet", "claude-sonnet-5"),
    ("haiku", "claude-haiku-4-5"),
)

MILLION = 1_000_000.0


def resolve(model: str | None) -> tuple[float, float, float] | None:
    """Returns (input, output, cache_read_mult), or None when not billable."""
    if not model or model.startswith("<"):
        return None  # <synthetic>: responses the CLI generates locally
    if model in _MODELS:
        return _MODELS[model]
    for token, ref in _FAMILY_FALLBACK:
        if token in model:
            return _MODELS[ref]
    return None


def cost(model: str | None, inp: int, out: int, w5m: int, w1h: int, read: int) -> float:
    """USD cost for one request, with the four token kinds priced apart."""
    p = resolve(model)
    if p is None:
        return 0.0
    p_in, p_out, read_mult = p
    return (
        inp * p_in
        + out * p_out
        + w5m * p_in * WRITE_5M_MULT
        + w1h * p_in * WRITE_1H_MULT
        + read * p_in * read_mult
    ) / MILLION


def known_models() -> list[str]:
    return sorted(_MODELS)
