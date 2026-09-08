"""`cc-cockpit statusline`: captures the payload and prints a status line.

Register it in the account's settings.json:

    "statusLine": {"type": "command", "command": "cc-cockpit statusline"}

Anything already configured there can be kept by chaining it:

    "command": "cc-cockpit statusline --chain 'my-other-statusline'"

With more than one account the registered command carries --account, and that
is not decoration: the payload holds the *account's* rate limits, so a personal
CLI writing into the company's snapshot would silently replace the percentage
the tray reports. Nothing in the payload identifies the subscription, so the
registration is what has to say it.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from . import accounts, panel
from .accounts import Account
from .i18n import duration as _dur


def _bar(pct: float, width: int = 8) -> str:
    fill = int(round(min(pct, 100) / 100 * width))
    return "▰" * fill + "▱" * (width - fill)


def render(payload: dict, snapshot: dict) -> str:
    import time
    now = time.time()
    parts = []
    for name, label in (("block", "5h"), ("week", "7d")):
        info = panel.window(name, now, snapshot)   # snapshot is already the account's
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


def settings_file(account: Account | None = None) -> Path:
    """The settings.json of one account - never a hardcoded ~/.claude."""
    return (account if account is not None else accounts.primary()).settings_file



def self_command(account: Account | None = None) -> str:
    """How to invoke this tool from outside.

    sys.argv[0] points at __main__.py, which Claude Code cannot run. Resolve the
    installed entry point instead, so the registered command keeps working after
    an upgrade; fall back to the module when running from a checkout.
    """
    import shutil
    import sys

    # only pin the account when there is more than one, so a single-account
    # registration keeps working unchanged if the id is later renamed
    tail = ""
    if account is not None and accounts.is_multi():
        tail = f" --account {account.id}"

    found = shutil.which("cc-cockpit")
    if found:
        return f"{found} statusline{tail}"
    wrapper = Path.home() / ".local" / "bin" / "cc-cockpit"
    if wrapper.exists():
        return f"{wrapper} statusline{tail}"
    root = Path(__file__).resolve().parent.parent
    return f"cd {root} && {sys.executable} -m cockpit statusline{tail}"


def install(command: str | None = None, account: Account | None = None) -> str:
    """Registers the statusline in the account's settings.json, keeping a backup.

    An existing statusline is not replaced - it is chained, so its output is
    still what shows up in the CLI.
    """
    import shutil

    acct = account if account is not None else accounts.primary()
    target = settings_file(acct)
    command = command or self_command(acct)
    settings = json.loads(target.read_text()) if target.exists() else {}
    current = settings.get("statusLine")
    if isinstance(current, dict) and "cc-cockpit" in str(current.get("command", "")):
        registered = str(current.get("command", ""))
        # Two ways a registration goes stale: a single-account one that never
        # gained --account when a second account appeared, and one still naming
        # an id that was since renamed. Both send the payload to the wrong
        # snapshot, so both get rewritten.
        if command != registered and _account_flag(registered) != _account_flag(command):
            shutil.copy2(target, target.with_suffix(".json.bak"))
            settings["statusLine"] = {"type": "command",
                                      "command": _rechain(registered, command)}
            target.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
            return f"updated to --account {acct.id}" if _account_flag(command) \
                else "updated to the account's own registration"
        return "already registered"

    if isinstance(current, dict) and current.get("command"):
        existing = current["command"].replace("'", "'\\''")
        command = f"{command} --chain '{existing}'"
        note = "registered, chaining the previous statusline"
    else:
        note = "registered"

    if target.exists():
        shutil.copy2(target, target.with_suffix(".json.bak"))
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
    settings["statusLine"] = {"type": "command", "command": command}
    target.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
    return note


def _account_flag(command: str) -> str:
    """The id in a registered '--account <id>', or '' when there is none."""
    parts = command.split()
    if "--account" in parts:
        index = parts.index("--account")
        if index + 1 < len(parts):
            return parts[index + 1]
    return ""


def _rechain(registered: str, command: str) -> str:
    """Keeps a --chain that was already there when rewriting the command."""
    marker = " --chain "
    if marker in registered:
        return command + marker + registered.split(marker, 1)[1]
    return command


def main(chain: str | None = None, account: Account | None = None) -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except ValueError:
        return 0                      # never break the CLI's status line
    snapshot = panel.record(payload, account=account)

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
