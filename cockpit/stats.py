"""Agregacoes: blocos de 5h, dia, semana, projeto, modelo, sessao."""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from . import config
from .collector import Event, refresh
from .sessions import live_sessions

HOUR = 3600.0


class Bucket:
    __slots__ = ("usd", "inp", "out", "w5", "w1", "read", "requests", "first", "last", "models", "sessions")

    def __init__(self) -> None:
        self.usd = 0.0
        self.inp = self.out = self.w5 = self.w1 = self.read = self.requests = 0
        self.first = self.last = 0.0
        self.models: dict[str, float] = defaultdict(float)
        self.sessions: set[str] = set()

    def add(self, e: Event) -> None:
        self.usd += e.c
        self.inp += e.i
        self.out += e.o
        self.w5 += e.w5
        self.w1 += e.w1
        self.read += e.r
        self.requests += 1
        self.models[e.m] += e.c
        self.sessions.add(e.s)
        if not self.first or e.t < self.first:
            self.first = e.t
        if e.t > self.last:
            self.last = e.t

    @property
    def tokens(self) -> int:
        return self.inp + self.out + self.w5 + self.w1 + self.read

    @property
    def billable(self) -> int:
        """Tokens que nao vieram de cache hit - o que realmente 'pesa'."""
        return self.inp + self.out + self.w5 + self.w1

    def as_dict(self) -> dict:
        total_in = self.inp + self.w5 + self.w1 + self.read
        return {
            "usd": round(self.usd, 4),
            "tokens": self.tokens,
            "input": self.inp,
            "output": self.out,
            "cache_write_5m": self.w5,
            "cache_write_1h": self.w1,
            "cache_read": self.read,
            "requests": self.requests,
            "sessions": len(self.sessions - {""}),
            "cache_hit_pct": round(100 * self.read / total_in, 1) if total_in else 0.0,
            "first": self.first,
            "last": self.last,
            "models": {k: round(v, 4) for k, v in sorted(self.models.items(), key=lambda kv: -kv[1])},
        }


def _day_bounds(offset_days: int = 0) -> tuple[float, float]:
    now = datetime.now().astimezone()
    start = (now - timedelta(days=offset_days)).replace(hour=0, minute=0, second=0, microsecond=0)
    return start.timestamp(), (start + timedelta(days=1)).timestamp()


def build_blocks(events: list[Event], block_hours: float) -> list[dict]:
    """Reconstroi as janelas de rate limit: comeca na hora cheia do primeiro
    request e dura block_hours; um silencio maior que a janela abre outra."""
    span = block_hours * HOUR
    blocks: list[dict] = []
    cur: Bucket | None = None
    start = 0.0
    last = 0.0
    for e in events:
        if cur is None or e.t - start >= span or e.t - last >= span:
            if cur is not None:
                blocks.append({"start": start, "end": start + span, "bucket": cur})
            start = float(int(e.t // HOUR) * HOUR)
            cur = Bucket()
        cur.add(e)
        last = e.t
    if cur is not None:
        blocks.append({"start": start, "end": start + span, "bucket": cur})
    return blocks


def _gauge(value: float, limit: float | None) -> dict:
    if not limit or limit <= 0:
        return {"limit": None, "pct": None}
    return {"limit": round(limit, 2), "pct": round(100 * value / limit, 1)}


def _label(cwd: str) -> str:
    if not cwd:
        return "(sem projeto)"
    p = Path(cwd)
    if str(p) == str(Path.home()):
        return "~"
    return p.name or str(p)


def _fill_days(daily: dict[str, Bucket], keep: int) -> list[dict]:
    if not daily:
        return []
    start = datetime.strptime(min(daily), "%Y-%m-%d")
    end = datetime.now().astimezone().replace(tzinfo=None)
    out = []
    cur = start
    while cur.date() <= end.date():
        key = cur.strftime("%Y-%m-%d")
        out.append({"date": key, **daily.get(key, Bucket()).as_dict()})
        cur += timedelta(days=1)
    return out[-keep:]


def _fill_hours(hourly: dict[int, Bucket], now: float) -> list[dict]:
    first = int((now - 23 * HOUR) // HOUR)
    last = int(now // HOUR)
    return [
        {"hour": h * HOUR, **hourly.get(h, Bucket()).as_dict()}
        for h in range(first, last + 1)
    ]


def summary(events: list[Event] | None = None, cfg: dict | None = None) -> dict:
    cfg = cfg or config.load()
    if events is None:
        events, _ = refresh()
    now = time.time()
    block_hours = float(cfg.get("block_hours") or 5)

    windows = {
        "today": _day_bounds(0),
        "yesterday": _day_bounds(1),
        "last_24h": (now - 24 * HOUR, now),
        "last_7d": (now - 7 * 24 * HOUR, now),
        "last_30d": (now - 30 * 24 * HOUR, now),
    }
    month_start = datetime.now().astimezone().replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
    windows["month"] = (month_start, now + 1)

    totals = {k: Bucket() for k in windows}
    totals["all"] = Bucket()
    daily: dict[str, Bucket] = defaultdict(Bucket)
    hourly24: dict[int, Bucket] = defaultdict(Bucket)
    projects: dict[str, Bucket] = defaultdict(Bucket)
    projects_today: dict[str, Bucket] = defaultdict(Bucket)
    models: dict[str, Bucket] = defaultdict(Bucket)
    per_session: dict[str, Bucket] = defaultdict(Bucket)
    efforts: dict[str, int] = defaultdict(int)
    sidechain = Bucket()

    for e in events:
        totals["all"].add(e)
        for name, (a, b) in windows.items():
            if a <= e.t < b:
                totals[name].add(e)
        day = datetime.fromtimestamp(e.t).astimezone().strftime("%Y-%m-%d")
        daily[day].add(e)
        projects[e.p].add(e)
        models[e.m].add(e)
        per_session[e.s].add(e)
        if e.ef:
            efforts[e.ef] += 1
        if e.x:
            sidechain.add(e)
        if e.t >= now - 24 * HOUR:
            hourly24[int(e.t // HOUR)].add(e)
        if windows["today"][0] <= e.t < windows["today"][1]:
            projects_today[e.p].add(e)

    blocks = build_blocks(events, block_hours)
    active = None
    if blocks and blocks[-1]["end"] > now:
        active = blocks[-1]
    closed = [b for b in blocks if b is not active]

    # tetos: config manual, senao o maior valor ja observado
    lim_block = cfg["limits"].get("block_usd")
    if not lim_block and closed:
        lim_block = max(b["bucket"].usd for b in closed)
    lim_week = cfg["limits"].get("week_usd")
    if not lim_week:
        weeks: dict[str, float] = defaultdict(float)
        for e in events:
            weeks[datetime.fromtimestamp(e.t).astimezone().strftime("%G-W%V")] += e.c
        lim_week = max(weeks.values(), default=0.0)

    if active:
        b = active["bucket"]
        elapsed = max(now - active["start"], 1.0)
        remaining = max(active["end"] - now, 0.0)
        burn = b.usd / (elapsed / HOUR)
        block_info = {
            "active": True,
            "start": active["start"],
            "end": active["end"],
            "elapsed_s": elapsed,
            "remaining_s": remaining,
            "burn_usd_per_h": round(burn, 3),
            "burn_tok_per_min": round(b.tokens / (elapsed / 60), 0),
            "projected_usd": round(b.usd + burn * (remaining / HOUR), 2),
            **b.as_dict(),
            **_gauge(b.usd, lim_block),
        }
        if lim_block and burn > 0:
            headroom = max(lim_block - b.usd, 0.0)
            block_info["eta_limit_s"] = headroom / burn * HOUR
        else:
            block_info["eta_limit_s"] = None
    else:
        nxt = Bucket()
        block_info = {"active": False, "start": None, "end": None, "remaining_s": 0,
                      "burn_usd_per_h": 0.0, "burn_tok_per_min": 0.0, "projected_usd": 0.0,
                      "eta_limit_s": None, **nxt.as_dict(), **_gauge(0, lim_block)}

    lim_day = max((b.usd for d, b in daily.items() if d != datetime.now().astimezone().strftime("%Y-%m-%d")), default=0.0)

    week = totals["last_7d"]
    week_info = {**week.as_dict(), **_gauge(week.usd, lim_week)}

    live = live_sessions()
    for s in live:
        b = per_session.get(s["session_id"])
        s["usage"] = b.as_dict() if b else Bucket().as_dict()

    plan = cfg.get("plan_monthly_usd")
    value = totals["month"].usd
    roi = round(value / plan, 1) if plan else None

    return {
        "generated_at": now,
        "block_hours": block_hours,
        "totals": {k: v.as_dict() for k, v in totals.items()},
        "today_gauge": {**totals["today"].as_dict(), **_gauge(totals["today"].usd, lim_day)},
        "block": block_info,
        "week": week_info,
        "daily": _fill_days(daily, 60),
        "hourly_24h": _fill_hours(hourly24, now),
        "blocks": [
            {"start": b["start"], "end": b["end"], **b["bucket"].as_dict()}
            for b in blocks[-40:]
        ],
        "projects": sorted(
            ({"cwd": k, "label": _label(k), **v.as_dict()} for k, v in projects.items()),
            key=lambda p: -p["usd"],
        )[:25],
        "projects_today": sorted(
            ({"cwd": k, "label": _label(k), **v.as_dict()} for k, v in projects_today.items()),
            key=lambda p: -p["usd"],
        )[:10],
        "models": sorted(
            ({"model": k or "(desconhecido)", **v.as_dict()} for k, v in models.items()),
            key=lambda m: -m["usd"],
        ),
        "efforts": dict(sorted(efforts.items(), key=lambda kv: -kv[1])),
        "subagents": sidechain.as_dict(),
        "sessions": live,
        "plan": {"monthly_usd": plan, "name": cfg.get("plan_name") or "", "value_this_month": round(value, 2), "roi": roi},
        "usd_brl": cfg.get("usd_brl"),
        "thresholds": {"warn": cfg.get("warn_pct", 70), "critical": cfg.get("critical_pct", 90)},
    }
