"""Claude Code conversations: the ones running, and the ones to go back to.

Two questions, two sources on disk.

*Alive right now*: each CLI instance writes <account>/sessions/<pid>.json. The
file survives a kill -9, so every entry is validated against /proc: the pid must
exist AND its starttime must match, which rules out a recycled pid.

*Recent*: a closed terminal leaves nothing behind but its transcript, and that
is the only thing that can be reopened - `claude --resume` needs the session id
and the directory the conversation was started in, both of which are in there.
So the recent list is read from the transcripts, never from our own event
history: what Claude Code has already pruned cannot be resumed, however much of
it we still keep.

A session belongs to the account whose directory it was found in - that is the
only way to tell a company CLI from a personal one, since the process itself
looks identical.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .accounts import Account, primary

# Claude Code rewrites the generated title and the cwd on every turn, so the
# last few kilobytes answer for a transcript of any size.
TAIL_BYTES = 64 * 1024
# only read when there is no generated title yet: far enough in for the first
# typed prompt, which sits behind a handful of metadata records
HEAD_BYTES = 32 * 1024
# (mtime, size) -> what was read, so a twenty-second refresh re-reads nothing
_META: dict[str, tuple[float, int, dict]] = {}


def proc_starttime(pid: int) -> str | None:
    try:
        stat = Path(f"/proc/{pid}/stat").read_bytes()
    except OSError:
        return None
    # field 22 (starttime) comes after the parenthesised comm, which may hold spaces
    tail = stat[stat.rfind(b")") + 2 :].split()
    try:
        return tail[19].decode()
    except IndexError:
        return None


def cmdline(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="replace").strip()
    except OSError:
        return ""


def _rss_mb(pid: int) -> float:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0.0


def live_sessions(account: Account | None = None) -> list[dict]:
    acct = account if account is not None else primary()
    sessions_dir = acct.sessions_dir
    out: list[dict] = []
    if not sessions_dir.exists():
        return out
    now = time.time()
    for path in sessions_dir.glob("*.json"):
        try:
            d = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        pid = d.get("pid")
        if not isinstance(pid, int):
            continue
        st = proc_starttime(pid)
        if st is None:
            continue
        want = str(d.get("procStart") or "")
        if want and st != want:
            continue  # pid recycled by another process
        if "claude" not in cmdline(pid):
            continue
        started = (d.get("startedAt") or 0) / 1000
        updated = (d.get("statusUpdatedAt") or d.get("updatedAt") or 0) / 1000
        out.append({
            "account": acct.id,
            "account_label": acct.title,
            "pid": pid,
            "session_id": d.get("sessionId") or "",
            "name": d.get("name") or f"pid {pid}",
            "cwd": d.get("cwd") or "",
            "status": d.get("status") or "?",
            "kind": d.get("kind") or "",
            "entrypoint": d.get("entrypoint") or "",
            "version": d.get("version") or "",
            "started_at": started,
            "uptime_s": max(0.0, now - started) if started else 0.0,
            "idle_s": max(0.0, now - updated) if updated else 0.0,
            "rss_mb": round(_rss_mb(pid), 1),
        })
    out.sort(key=lambda s: s["started_at"])
    return out


# ------------------------------------------------------- conversations to reopen

def _decode(raw: bytes) -> dict | None:
    try:
        d = json.loads(raw)
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


def _first_prompt(path: Path) -> str:
    """What the conversation opened with - the title before one was generated.

    A transcript gets its `ai-title` a turn or two in, so a session that was
    closed right away has none, and "(no title)" for the very session someone
    is looking for is the one case this list must not produce.
    """
    try:
        with path.open("rb") as fh:
            head = fh.read(HEAD_BYTES)
    except OSError:
        return ""
    for raw in head.split(b"\n")[:-1]:      # the last piece may be half a line
        d = _decode(raw)
        if not d or d.get("type") != "user" or d.get("isSidechain"):
            continue
        content = (d.get("message") or {}).get("content")
        if not isinstance(content, str):
            continue                        # a tool result, not something typed
        for line in content.strip().splitlines():
            line = line.strip()
            if line and not line.startswith("<"):   # skip the injected blocks
                return line[:80]
    return ""


def _meta(path: Path, stat: os.stat_result) -> dict:
    """Title and working directory of one transcript, read from its tail."""
    key = str(path)
    cached = _META.get(key)
    if cached and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
        return cached[2]
    try:
        with path.open("rb") as fh:
            if stat.st_size > TAIL_BYTES:
                fh.seek(stat.st_size - TAIL_BYTES)
            tail = fh.read()
    except OSError:
        tail = b""
    title = cwd = ""
    # backwards, so the newest record wins - and the half line the seek cut off
    # is reached last, where failing to decode it costs nothing
    for raw in reversed(tail.split(b"\n")):
        d = _decode(raw) if raw else None
        if not d:
            continue
        if not title and d.get("type") == "ai-title":
            title = str(d.get("aiTitle") or "").strip()
        if not cwd and d.get("cwd"):
            cwd = str(d["cwd"])
        if title and cwd:
            break
    meta = {"title": title or _first_prompt(path), "cwd": cwd}
    if len(_META) > 256:
        _META.clear()      # a pruned transcript never comes back; rebuilding is cheap
    _META[key] = (stat.st_mtime, stat.st_size, meta)
    return meta


def recent_sessions(account: Account | None = None, limit: int = 5,
                    skip: set[str] | None = None) -> list[dict]:
    """Conversations that can be resumed, newest first.

    Sessions still running are handed in as `skip`: they are already on the live
    list, and offering the same conversation twice under two headings would be
    the one thing worse than not offering it at all.

    Only the newest `limit` transcripts are opened, so the cost does not grow
    with the number of projects. Subagent transcripts live one level deeper and
    are not conversations of their own, which is why the glob stops at the
    project directory instead of descending like the collector's.
    """
    acct = account if account is not None else primary()
    if limit <= 0 or not acct.projects_dir.is_dir():
        return []
    skip = skip or set()

    found: list[tuple[float, str, Path, os.stat_result]] = []
    for path in acct.projects_dir.glob("*/*.jsonl"):
        session_id = path.stem
        if session_id in skip:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        found.append((stat.st_mtime, session_id, path, stat))
    found.sort(key=lambda item: -item[0])

    now = time.time()
    out: list[dict] = []
    for mtime, session_id, path, stat in found:
        if len(out) >= limit:
            break
        meta = _meta(path, stat)
        if not meta["cwd"]:
            continue     # nothing to resume into: not a conversation, or unreadable
        out.append({
            "account": acct.id,
            "account_label": acct.title,
            "session_id": session_id,
            "title": meta["title"],
            "cwd": meta["cwd"],
            "last_at": mtime,
            "ago_s": max(0.0, now - mtime),
        })
    return out
