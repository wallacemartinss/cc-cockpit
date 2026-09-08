"""More than one Claude Code account on the same machine.

Claude Code keeps everything under one directory, chosen by CLAUDE_CONFIG_DIR
and defaulting to ~/.claude. Someone with a company account and a personal one
runs two of them - `~/.claude` and, say, `~/.claude-pessoal`.

Reading both is the easy half. The half that matters is that almost nothing this
tool measures can be merged across accounts:

  * the 5h and 7d windows in panel.json are the *account's* rate limits. Two
    accounts have two independent windows, and a single snapshot file means the
    last CLI to render a statusline silently overwrites the other one's numbers;
  * calibration.json maps USD to percent for one plan. Feeding a Max and a Pro
    into the same median corrupts both ceilings, permanently;
  * anchors, live sessions and the ingest offsets are all per account too.

So an account is a dimension, not a second path to glob. Each one owns a
subdirectory of the data dir, and every module that keeps state takes an account.
Only money aggregates across accounts - see stats.combined().
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from . import config

DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "cc-cockpit"
ACCOUNTS_DIR = DATA_DIR / "accounts"

DEFAULT_ID = "default"
# what a single-account install had before accounts existed, at the data dir root
LEGACY_FILES = ("events.ndjson", "state.json", "panel.json", "panel-history.ndjson",
                "anchors.json", "calibration.json")
_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,40}$")


def default_claude_dir() -> Path:
    """Where Claude Code keeps its data when nothing else is configured."""
    return Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")).expanduser()


@dataclass(frozen=True)
class Account:
    id: str
    label: str
    claude_dir: Path

    # ---- what Claude Code writes ----
    @property
    def projects_dir(self) -> Path:
        return self.claude_dir / "projects"

    @property
    def sessions_dir(self) -> Path:
        return self.claude_dir / "sessions"

    @property
    def settings_file(self) -> Path:
        return self.claude_dir / "settings.json"

    # ---- what cc-cockpit writes ----
    @property
    def data_dir(self) -> Path:
        return ACCOUNTS_DIR / self.id

    def path(self, name: str) -> Path:
        return self.data_dir / name

    @property
    def title(self) -> str:
        return self.label or self.id

    def exists(self) -> bool:
        return self.claude_dir.is_dir()

    def as_dict(self) -> dict:
        return {"id": self.id, "label": self.title, "dir": str(self.claude_dir),
                "exists": self.exists()}


def _build(entry: dict, index: int) -> Account | None:
    raw_dir = entry.get("dir") or ""
    if not raw_dir:
        return None
    account_id = str(entry.get("id") or f"account{index}")
    if not _ID_RE.match(account_id):
        # the id names a directory under the data dir; refuse anything else
        return None
    return Account(id=account_id, label=str(entry.get("label") or ""),
                   claude_dir=Path(raw_dir).expanduser())


def listed(cfg: dict | None = None) -> list[Account]:
    """Every configured account, or the implicit single one."""
    cfg = cfg if cfg is not None else config.load()
    out: list[Account] = []
    seen: set[str] = set()
    for i, entry in enumerate(cfg.get("accounts") or [], start=1):
        if not isinstance(entry, dict):
            continue
        account = _build(entry, i)
        if account and account.id not in seen:
            seen.add(account.id)
            out.append(account)
    if not out:
        out.append(Account(id=DEFAULT_ID, label="", claude_dir=default_claude_dir()))
    return out


def primary(cfg: dict | None = None) -> Account:
    """The account the tray label and a bare command speak for."""
    cfg = cfg if cfg is not None else config.load()
    found = listed(cfg)
    wanted = cfg.get("primary_account")
    for account in found:
        if account.id == wanted:
            return account
    return found[0]


def get(account_id: str, cfg: dict | None = None) -> Account | None:
    for account in listed(cfg):
        if account.id == account_id:
            return account
    return None


def resolve(account_id: str | None, cfg: dict | None = None) -> Account:
    """An account by id, falling back to the primary. Raises on a bad id."""
    cfg = cfg if cfg is not None else config.load()
    if not account_id:
        return primary(cfg)
    account = get(account_id, cfg)
    if account is None:
        known = ", ".join(a.id for a in listed(cfg))
        raise ValueError(f"unknown account {account_id!r} - configured: {known}")
    return account


def is_multi(cfg: dict | None = None) -> bool:
    return len(listed(cfg)) > 1


def discover() -> list[Path]:
    """Directories that look like a Claude Code home, for `accounts --detect`."""
    home = Path.home()
    out = []
    for path in sorted(home.glob(".claude*")):
        if path.is_dir() and ((path / "projects").is_dir() or (path / "sessions").is_dir()):
            out.append(path)
    extra = default_claude_dir()
    if extra.is_dir() and extra not in out:
        out.insert(0, extra)
    return out


def suggest_id(path: Path) -> str:
    """A readable id for a discovered directory: ~/.claude-pessoal -> pessoal."""
    name = path.name.lstrip(".")
    name = name[len("claude"):].lstrip("-_.") if name.startswith("claude") else name
    name = re.sub(r"[^A-Za-z0-9._-]", "-", name).strip("-_.")
    return name or DEFAULT_ID


def migrate(cfg: dict | None = None) -> Account | None:
    """Moves a pre-accounts data dir into accounts/<primary>/, once.

    The flat layout is what every install before this change has, and the files
    hold history Claude Code has already pruned - so they are moved, never left
    behind for a fresh start.

    Collisions are the normal case, not the exotic one: the statusline runs on
    every CLI render, so a new-code write can easily land in the account
    directory before any command gets around to migrating. Each file is decided
    on its own, and events.ndjson - the only one holding anything irreplaceable -
    is merged rather than picked between.
    """
    stale = [DATA_DIR / name for name in LEGACY_FILES]
    if not any(path.exists() for path in stale):
        return None
    target = primary(cfg)
    target.data_dir.mkdir(parents=True, exist_ok=True)

    moved = False
    for path in stale:
        if not path.exists():
            continue
        dest = target.data_dir / path.name
        if not dest.exists():
            path.replace(dest)
            moved = True
        elif path.name == "events.ndjson":
            _merge_events(path, dest)
            moved = True
        else:
            # a snapshot the new code already rewrote: keep the fresh one and
            # park the old file instead of deleting anything the user may want
            path.replace(path.with_suffix(path.suffix + ".pre-accounts"))
            moved = True
    return target if moved else None


def _merge_events(source: Path, dest: Path) -> None:
    """Appends the old history into the new file, without duplicating a request.

    Events carry a dedup key, so this is a set union rather than a concatenation;
    order is restored by the reader, which sorts by timestamp anyway.
    """
    import json

    def keys(path: Path) -> set[str]:
        found = set()
        try:
            with path.open(errors="replace") as fh:
                for line in fh:
                    try:
                        found.add(json.loads(line)["k"])
                    except (ValueError, KeyError, TypeError):
                        continue
        except OSError:
            pass
        return found

    known = keys(dest)
    with source.open(errors="replace") as src, dest.open("a") as out:
        for line in src:
            try:
                key = json.loads(line)["k"]
            except (ValueError, KeyError, TypeError):
                continue
            if key not in known:
                known.add(key)
                out.write(line if line.endswith("\n") else line + "\n")
    source.replace(source.with_suffix(source.suffix + ".pre-accounts"))


def rehome(account: Account) -> bool:
    """Carries the pre-accounts history over when the default gains a real id.

    Someone who has been running cc-cockpit already has history under
    accounts/default. The moment they name that same directory "empresa", the
    id changes and the old folder would be orphaned - together with everything
    Claude Code has since pruned, which is exactly what this tool exists to keep.
    """
    if account.id == DEFAULT_ID or account.data_dir.exists():
        return False
    legacy = ACCOUNTS_DIR / DEFAULT_ID
    if not legacy.is_dir():
        return False
    if account.claude_dir != default_claude_dir():
        return False
    if any(a.id == DEFAULT_ID for a in listed()):
        return False               # something still answers to that id
    legacy.replace(account.data_dir)
    return True
