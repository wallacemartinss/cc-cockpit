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
    # More than one Claude Code account on this machine. Empty means the single
    # implicit account at CLAUDE_CONFIG_DIR (or ~/.claude), which is the whole
    # story for most people. Each entry needs a unique id - it names a directory
    # under ~/.local/share/cc-cockpit/accounts/ - plus the Claude Code home:
    #   {"id": "pessoal", "label": "Pessoal", "dir": "~/.claude-pessoal"}
    # `cc-cockpit accounts --detect` fills this in from what is on disk.
    "accounts": [],
    # which account the tray label and a bare command speak for. null = the first
    "primary_account": None,
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
    """Loads the config, writing any key the file is missing.

    A file written by an older version would otherwise never show the new
    options, and the file is where people look to discover them.
    """
    cfg = load()
    if not CONFIG_FILE.exists() or set(cfg) - set(_flat(CONFIG_FILE)) or _missing(cfg):
        save(cfg)
    return cfg


def _flat(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _missing(cfg: dict) -> bool:
    stored = _flat(CONFIG_FILE)
    if set(cfg) - set(stored):
        return True
    return any(
        isinstance(v, dict) and set(v) - set(stored.get(k, {}))
        for k, v in cfg.items()
    )
