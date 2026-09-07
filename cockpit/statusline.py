"""`cc-cockpit statusline`: captures the payload and prints a status line.

Register it in ~/.claude/settings.json:

    "statusLine": {"type": "command", "command": "cc-cockpit statusline"}

Anything already configured there can be kept by chaining it:

    "command": "cc-cockpit statusline --chain 'my-other-statusline'"
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from . import panel
from .i18n import duration as _dur


def _bar(pct: float, width: int = 8) -> str:
    fill = int(round(min(pct, 100) / 100 * width))
    return "▰" * fill + "▱" * (width - fill)


def render(payload: dict, snapshot: dict) -> str:
    import time
    now = time.time()
    parts = []
    for name, label in (("block", "5h"), ("week", "7d")):
        info = panel.window(name, now, snapshot)
        if info:
            parts.append(f"{label} {_bar(info['pct'])} {info['pct']:.0f}% "
                         f"({_dur(info['resets_at'] - now)})")
    ctx = (payload.get("context_window") or {}).get("used_percentage")
    if ctx is not None:
        parts.append(f"ctx {ctx:.0f}%")
    model = (payload.get("model") or {}).get("display_name")
    if model:
        parts.append(model)
    return "  ·  ".join(parts)


SETTINGS = Path.home() / ".claude" / "settings.json"


def self_command() -> str:
    """How to invoke this tool from outside.

    sys.argv[0] points at __main__.py, which Claude Code cannot run. Resolve the
    installed entry point instead, so the registered command keeps working after
    an upgrade; fall back to the module when running from a checkout.
    """
    import shutil
    import sys

    found = shutil.which("cc-cockpit")
    if found:
        return f"{found} statusline"
    wrapper = Path.home() / ".local" / "bin" / "cc-cockpit"
    if wrapper.exists():
        return f"{wrapper} statusline"
    root = Path(__file__).resolve().parent.parent
    return f"cd {root} && {sys.executable} -m cockpit statusline"


def install(command: str | None = None) -> str:
    """Registers the statusline in ~/.claude/settings.json, keeping a backup.

    An existing statusline is not replaced - it is chained, so its output is
    still what shows up in the CLI.
    """
    import shutil

    command = command or self_command()
    settings = json.loads(SETTINGS.read_text()) if SETTINGS.exists() else {}
    current = settings.get("statusLine")
    if isinstance(current, dict) and "cc-cockpit" in str(current.get("command", "")):
        return "already registered"

    if isinstance(current, dict) and current.get("command"):
        existing = current["command"].replace("'", "'\\''")
        command = f"{command} --chain '{existing}'"
        note = "registered, chaining the previous statusline"
    else:
        note = "registered"

    if SETTINGS.exists():
        shutil.copy2(SETTINGS, SETTINGS.with_suffix(".json.bak"))
    settings["statusLine"] = {"type": "command", "command": command}
    SETTINGS.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
    return note


def main(chain: str | None = None) -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except ValueError:
        return 0                      # never break the CLI's status line
    snapshot = panel.record(payload)

    if chain:
        try:
            result = subprocess.run(chain, shell=True, input=raw, text=True,
                                    capture_output=True, timeout=5)
            sys.stdout.write(result.stdout)
            return 0
        except (subprocess.SubprocessError, OSError):
            pass
    print(render(payload, snapshot))
    return 0
