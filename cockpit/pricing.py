"""Tabela de precos (USD por 1M tokens) e calculo de custo equivalente API.

Regras de cache (docs Anthropic):
  cache write 5m  = 1.25x input
  cache write 1h  = 2.00x input
  cache read      = 0.10x input  (0.025x no Fable 5.1)

Assinaturas (Pro/Max) nao cobram por token; o custo aqui e o "valor
equivalente API" - serve como unidade de peso do consumo e para saber
quanto o plano esta economizando.
"""
from __future__ import annotations

# modelo -> (input, output, cache_read_mult)
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

# fallback por familia, para modelos novos que ainda nao estao na tabela
_FAMILY_FALLBACK = (
    ("fable", "claude-fable-5-1"),
    ("mythos", "claude-mythos-5-1"),
    ("opus", "claude-opus-5"),
    ("sonnet", "claude-sonnet-5"),
    ("haiku", "claude-haiku-4-5"),
)

MILLION = 1_000_000.0


def resolve(model: str | None) -> tuple[float, float, float] | None:
    """Retorna (input, output, cache_read_mult) ou None se nao for cobravel."""
    if not model or model.startswith("<"):
        return None  # <synthetic>: respostas locais do proprio CLI
    if model in _MODELS:
        return _MODELS[model]
    for token, ref in _FAMILY_FALLBACK:
        if token in model:
            return _MODELS[ref]
    return None


def cost(model: str | None, inp: int, out: int, w5m: int, w1h: int, read: int) -> float:
    """Custo em USD para um request, com os quatro tipos de token separados."""
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
