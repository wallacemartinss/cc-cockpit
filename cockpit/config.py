"""cc-cockpit configuration (~/.config/cc-cockpit/config.json)."""
from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "cc-cockpit"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS: dict = {
    # interface language: auto (follows the OS) | en | pt | es
    "language": "auto",
    # Claude Code rate-limit window
    "block_hours": 5,
    # reference ceilings in API-equivalent USD. null = auto-calibrate from the
    # largest block/week ever seen in your own history.
    "limits": {"block_usd": None, "week_usd": None},
    # what shows next to the icon: block | week | today | none
    "tray_metric": "block",
    # menu bar characters: blocks | dots | emoji (emoji is the colourful one)
    "menu_bar_style": "blocks",
    "tray_show_cost": True,
    "refresh_seconds": 20,
    # what the plan costs per month - only used to show how much it returns
    "plan_monthly_usd": None,
    "plan_name": "",
    # optional rate to show a local-currency figure next to USD
    "local_currency": None,   # e.g. {"code": "BRL", "symbol": "R$", "rate": 5.4}
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
