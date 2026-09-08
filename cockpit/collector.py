"""Incremental collector for Claude Code transcripts.

Reads <account>/projects/**/*.jsonl from the last known offset and appends
compact events to ~/.local/share/cc-cockpit/accounts/<id>/events.ndjson.

That buys two things the transcripts alone do not give:
  1. cheap reads - only the delta is parsed on each refresh;
  2. a permanent history - Claude Code prunes transcripts after ~30 days.

Every entry point takes an account. Histories are kept apart rather than tagged
in one file, because the state that sits next to them - rate limits, calibration,
anchors - cannot be merged at all; see accounts.py.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import pricing
from .accounts import Account, primary

SCHEMA = 1


def _account(account: Account | None) -> Account:
    return account if account is not None else primary()


@dataclass(slots=True)
class Event:
    k: str      # dedup key: message.id:requestId
    t: float    # epoch seconds (UTC)
    m: str      # model
    i: int      # input tokens
    o: int      # output tokens
    w5: int     # cache write 5m
    w1: int     # cache write 1h
    r: int      # cache read
    c: float    # API-equivalent cost in USD
    s: str      # sessionId
    p: str      # project cwd
    x: int      # 1 = sidechain (subagent)
    ef: str     # effort

    @classmethod
    def from_row(cls, d: dict) -> "Event | None":
        msg = d.get("message") or {}
        u = msg.get("usage") or {}
        if not u:
            return None
        key = f"{msg.get('id') or ''}:{d.get('requestId') or ''}"
        if key == ":":
            return None
        ts = d.get("timestamp") or ""
        try:
            epoch = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
        cc = u.get("cache_creation") or {}
        w5 = int(cc.get("ephemeral_5m_input_tokens") or 0)
        w1 = int(cc.get("ephemeral_1h_input_tokens") or 0)
        total_write = int(u.get("cache_creation_input_tokens") or 0)
        if w5 + w1 == 0 and total_write:
            w5 = total_write  # older transcripts without the per-TTL split
        model = msg.get("model") or ""
        inp = int(u.get("input_tokens") or 0)
        out = int(u.get("output_tokens") or 0)
        read = int(u.get("cache_read_input_tokens") or 0)
        return cls(
            k=key, t=epoch, m=model, i=inp, o=out, w5=w5, w1=w1, r=read,
            c=round(pricing.cost(model, inp, out, w5, w1, read), 6),
            s=d.get("sessionId") or "",
            p=d.get("cwd") or "",
            x=1 if d.get("isSidechain") else 0,
            ef=d.get("effort") or "",
        )

    def to_json(self) -> str:
        return json.dumps(self.__dict__ if not hasattr(self, "__slots__") else {
            f: getattr(self, f) for f in self.__slots__
        }, separators=(",", ":"))

    @property
    def tokens(self) -> int:
        return self.i + self.o + self.w5 + self.w1 + self.r


def _load_state(acct: Account) -> dict:
    try:
        st = json.loads(acct.path("state.json").read_text())
        if st.get("schema") == SCHEMA:
            return st
    except (OSError, ValueError):
        pass
    return {"schema": SCHEMA, "files": {}}


def _save_state(acct: Account, state: dict) -> None:
    acct.data_dir.mkdir(parents=True, exist_ok=True)
    path = acct.path("state.json")
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(path)


def load_events(account: Account | None = None) -> list[Event]:
    """Reads the consolidated history of one account."""
    acct = _account(account)
    events: list[Event] = []
    events_file = acct.path("events.ndjson")
    if not events_file.exists():
        return events
    with events_file.open(errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                events.append(Event(**d))
            except (ValueError, TypeError):
                continue
    return events


def _read_new_lines(path: Path, offset: int) -> tuple[list[bytes], int]:
    """Reads only what was appended, never a half-written line."""
    size = path.stat().st_size
    if size < offset:            # truncated or rotated -> reprocess
        offset = 0
    if size == offset:
        return [], offset
    with path.open("rb") as fh:
        fh.seek(offset)
        chunk = fh.read(size - offset)
    end = chunk.rfind(b"\n")
    if end == -1:
        return [], offset        # no complete line yet
    complete = chunk[: end + 1]
    return complete.splitlines(), offset + len(complete)


def refresh(account: Account | None = None) -> tuple[list[Event], int]:
    """Ingests whatever is new for one account. Returns (full history, new count)."""
    acct = _account(account)
    projects_dir = acct.projects_dir
    state = _load_state(acct)
    events = load_events(acct)
    seen = {e.k for e in events}
    new: list[Event] = []

    for path in sorted(projects_dir.glob("**/*.jsonl")):
        key = str(path)
        info = state["files"].get(key, {"offset": 0})
        try:
            lines, offset = _read_new_lines(path, int(info.get("offset", 0)))
        except OSError:
            continue
        for raw in lines:
            if b'"usage"' not in raw:
                continue
            try:
                d = json.loads(raw)
            except ValueError:
                continue
            if d.get("type") != "assistant":
                continue
            ev = Event.from_row(d)
            if ev is None or ev.k in seen:
                continue
            seen.add(ev.k)
            new.append(ev)
        state["files"][key] = {"offset": offset, "seen_at": time.time()}

    if new:
        new.sort(key=lambda e: e.t)
        acct.data_dir.mkdir(parents=True, exist_ok=True)
        with acct.path("events.ndjson").open("a") as fh:
            for ev in new:
                fh.write(ev.to_json() + "\n")
        events.extend(new)
        events.sort(key=lambda e: e.t)

    # forget files Claude Code has already pruned
    alive = {str(p) for p in projects_dir.glob("**/*.jsonl")}
    state["files"] = {k: v for k, v in state["files"].items() if k in alive}
    _save_state(acct, state)
    return events, len(new)


def utc_now() -> float:
    return datetime.now(timezone.utc).timestamp()
