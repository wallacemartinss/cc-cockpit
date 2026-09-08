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

import json
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

    @property
    def credentials_file(self) -> Path:
        """Read only for the login expiry - see auth.py."""
        return self.claude_dir / ".credentials.json"

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


def looks_like_claude_home(path: Path) -> bool:
    return path.is_dir() and any((path / n).exists()
                                 for n in ("projects", "sessions", ".claude.json",
                                           "settings.json", ".credentials.json"))


def running_config_dirs() -> list[Path]:
    """CLAUDE_CONFIG_DIR of the Claude Code processes running right now.

    Globbing the home directory only finds an account that lives where we
    guessed. A second account is often somewhere else entirely, pointed at by
    CLAUDE_CONFIG_DIR in the shell that starts it - and the tray, launched by
    autostart, never sees that shell's environment. The process itself does,
    and /proc will say so.
    """
    found: list[Path] = []
    try:
        pids = [int(p.name) for p in Path("/proc").iterdir() if p.name.isdigit()]
    except OSError:
        return found
    for pid in pids:
        try:
            comm = (Path(f"/proc/{pid}/comm").read_text().strip())
            if "claude" not in comm and "node" not in comm:
                continue
            raw = Path(f"/proc/{pid}/environ").read_bytes()
        except OSError:
            continue
        for entry in raw.split(b"\0"):
            if entry.startswith(b"CLAUDE_CONFIG_DIR="):
                path = Path(entry.split(b"=", 1)[1].decode(errors="replace")).expanduser()
                if path not in found and looks_like_claude_home(path):
                    found.append(path)
    return found


# where discover() looks, so `--detect` can say what it searched rather than
# leaving someone staring at a list with their other account missing from it
SEARCH_GLOBS = ("~/.claude*", "~/.config/claude*")


def discover() -> dict[Path, str]:
    """Claude Code homes on this machine, mapped to how each was found."""
    out: dict[Path, str] = {}

    default = default_claude_dir()
    if looks_like_claude_home(default):
        out[default] = "CLAUDE_CONFIG_DIR" if os.environ.get("CLAUDE_CONFIG_DIR") else "default"

    for pattern in SEARCH_GLOBS:
        base = Path(pattern).expanduser()
        for path in sorted(base.parent.glob(base.name)):
            if path not in out and looks_like_claude_home(path):
                out[path] = pattern

    for path in running_config_dirs():
        if path not in out:
            out[path] = "a running Claude Code"
    return out


def identity(claude_dir: Path) -> dict:
    """Who is logged in to this directory, from Claude Code's own record.

    ~/.claude.json carries one `oauthAccount` - singular, one login per config
    directory, which is what makes a directory the right unit for an account.
    It is also the only thing that can tell a company account from a personal
    one without asking the person which is which.
    """
    # With the default home the file sits beside the directory (~/.claude.json,
    # next to ~/.claude/); a directory named by CLAUDE_CONFIG_DIR keeps its own
    # inside. Try both rather than assume which layout this install uses.
    candidates = (claude_dir / ".claude.json",
                  claude_dir.parent / f"{claude_dir.name}.json")
    raw = None
    for candidate in candidates:
        try:
            raw = json.loads(candidate.read_text())
            break
        except (OSError, ValueError):
            continue
    if raw is None:
        return {}
    account = raw.get("oauthAccount")
    if not isinstance(account, dict):
        return {}
    return {k: account.get(k) for k in
            ("displayName", "fullName", "organizationName", "organizationType",
             "organizationRole", "emailAddress")}


def suggest_label(claude_dir: Path) -> str:
    """A readable name for a directory: the organisation, or whoever is logged in.

    Anthropic names a personal organisation after the account's own email
    ("someone@example.com's Organization"), which is noise on a panel; a company
    account has a real name there, and that is exactly the one worth showing.
    """
    who = identity(claude_dir)
    org = (who.get("organizationName") or "").strip()
    if org and "'s Organization" not in org:
        return org
    return (who.get("displayName") or who.get("fullName") or "").strip()


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


def valid_id(account_id: str) -> bool:
    """An id names a directory under the data dir, so it is not free-form."""
    return bool(_ID_RE.match(account_id))


def rename(old_id: str, new_id: str, cfg: dict | None = None) -> str:
    """Renames an account id and carries its data directory along.

    The label is a display name and changing it costs nothing. The id is not: it
    names accounts/<id>/, which holds months Claude Code has already pruned. So
    this is the one place allowed to change it, and it moves the directory in
    the same breath - never leaves it behind for a silent fresh start.

    Returns a note for the caller to print. Raises ValueError on a bad request.
    """
    cfg = cfg if cfg is not None else config.load()
    if not valid_id(new_id):
        raise ValueError(f"{new_id!r} is not a usable id (letters, digits, . _ -)")
    found = {a.id: a for a in listed(cfg)}
    if old_id not in found:
        raise ValueError(f"unknown account {old_id!r} - configured: {', '.join(found)}")
    if new_id in found:
        raise ValueError(f"{new_id!r} is already taken")

    source = ACCOUNTS_DIR / old_id
    target = ACCOUNTS_DIR / new_id
    if target.exists():
        raise ValueError(f"{target} already exists - move it aside first")
    moved = False
    if source.is_dir():
        target.parent.mkdir(parents=True, exist_ok=True)
        source.replace(target)
        moved = True
    return f"{old_id} -> {new_id}" + (" (history moved)" if moved else "")
