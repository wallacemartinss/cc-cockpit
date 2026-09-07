"""Configuracao do cc-cockpit (~/.config/cc-cockpit/config.json)."""
from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "cc-cockpit"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS: dict = {
    # janela de rate limit do Claude Code
    "block_hours": 5,
    # tetos de referencia em USD equivalente API. null = auto-calibra pelo
    # maior bloco/semana ja observado no seu historico.
    "limits": {"block_usd": None, "week_usd": None},
    # o que aparece ao lado do icone: block | week | today | none
    "tray_metric": "block",
    "tray_show_cost": True,
    "refresh_seconds": 20,
    # quanto voce paga pelo plano por mes - so para calcular o quanto ele rende
    "plan_monthly_usd": None,
    "plan_name": "",
    # cotacao opcional para exibir R$ ao lado do USD
    "usd_brl": None,
    "dashboard_port": 8765,
    "warn_pct": 70,
    "critical_pct": 90,
}


def load() -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        user = json.loads(CONFIG_FILE.read_text())
    except (OSError, ValueError):
        return cfg
    for k, v in user.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    return cfg


def save(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


def ensure() -> dict:
    if not CONFIG_FILE.exists():
        save(DEFAULTS)
    return load()
