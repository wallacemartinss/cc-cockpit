"""Aggregations: 5h blocks, day, week, project, model, session."""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from . import accounts, anchors, auth, calibration, config, i18n, panel
from .accounts import Account
from .collector import Event, load_events, refresh
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
        """Tokens that did not come from a cache hit - the ones that weigh."""
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
    """Rebuilds the rate-limit windows: a block starts at the exact timestamp of
    its first request and lasts block_hours; a silence longer than the window
    opens the next one.

    The start is NOT rounded down to the hour. Checked against what Claude Code
    itself reports: a first request at 08:46:33 resets at 13:46, not 13:00.
    """
    span = block_hours * HOUR
    blocks: list[dict] = []
    cur: Bucket | None = None
    start = 0.0
    last = 0.0
    for e in events:
        if cur is None or e.t - start >= span or e.t - last >= span:
            if cur is not None:
                blocks.append({"start": start, "end": start + span, "bucket": cur})
            start = e.t
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


def _heatmap(events: list[Event], now: float, weeks: int = 4) -> dict:
    """Spend by weekday and hour of day.

    The daily and hourly series each answer "how much, when" along one axis.
    Crossing them is what shows a *pattern* - the Tuesday afternoon that is
    always expensive, the weekend that is not - which neither one can.
    """
    cutoff = now - weeks * 7 * 86400
    grid = [[0.0] * 24 for _ in range(7)]
    for e in events:
        if e.t < cutoff:
            continue
        when = datetime.fromtimestamp(e.t).astimezone()
        grid[when.weekday()][when.hour] += e.c          # Monday is 0
    peak = max((v for row in grid for v in row), default=0.0)
    return {"weeks": weeks, "peak": round(peak, 4),
            "grid": [[round(v, 4) for v in row] for row in grid]}


def _fill_hours(hourly: dict[int, Bucket], now: float) -> list[dict]:
    first = int((now - 23 * HOUR) // HOUR)
    last = int(now // HOUR)
    return [
        {"hour": h * HOUR, **hourly.get(h, Bucket()).as_dict()}
        for h in range(first, last + 1)
    ]


def summary(events: list[Event] | None = None, cfg: dict | None = None,
            account: Account | None = None) -> dict:
    """Everything the tray and the dashboard show, for one account.

    An account is not an optional label here: the rate-limit windows, the
    calibrated ceilings and the live sessions all belong to a subscription, and
    none of them survives being averaged with another one's.
    """
    cfg = cfg or config.load()
    i18n.use(cfg.get("language"))
    acct = account if account is not None else accounts.primary(cfg)
    if events is None:
        events, _ = refresh(acct)
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

    # The account-wide window may have opened before the first local request
    # (the Claude app shares the same limit), so a known end wins over the
    # local estimate: official statusline data first, manual anchor second.
    official_block = panel.window("block", now, account=acct)
    end_override = (official_block["resets_at"] if official_block
                    else anchors.block_end(now, account=acct))
    block_source = "official" if official_block else ("anchored" if end_override else "local")
    if end_override:
        start = end_override - block_hours * HOUR
        bucket = Bucket()
        for e in events:
            if start <= e.t < end_override:
                bucket.add(e)
        active = {"start": start, "end": end_override, "bucket": bucket}

    # ceilings, in order of trust: manual config > calibration against the
    # percentage Claude Code reports > the largest value ever observed
    lim_block, src_block = cfg["limits"].get("block_usd"), "manual"
    if not lim_block:
        lim_block, src_block = calibration.ceiling("block", account=acct), "calibrated"
    if not lim_block:
        lim_block = max((b["bucket"].usd for b in closed), default=0.0)
        src_block = "peak"

    lim_week, src_week = cfg["limits"].get("week_usd"), "manual"
    if not lim_week:
        lim_week, src_week = calibration.ceiling("week", account=acct), "calibrated"
    if not lim_week:
        weeks: dict[str, float] = defaultdict(float)
        for e in events:
            weeks[datetime.fromtimestamp(e.t).astimezone().strftime("%G-W%V")] += e.c
        lim_week = max(weeks.values(), default=0.0)
        src_week = "peak"

    def _official_gauge(info: dict | None, bucket: Bucket) -> dict:
        """Official percentage wins, and it also reveals the real ceiling."""
        if not info:
            return {}
        pct = info["pct"]
        limit = round(bucket.usd / (pct / 100), 2) if pct > 0 else None
        return {"pct": round(pct, 1), "limit": limit, "limit_source": "official",
                "official_age_s": info["age_s"]}

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
            "limit_source": src_block,
            "window_source": block_source,
            **_official_gauge(official_block, b),
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
                      "eta_limit_s": None, **nxt.as_dict(), **_gauge(0, lim_block),
                      "limit_source": src_block, "window_source": block_source}

    lim_day = max((b.usd for d, b in daily.items() if d != datetime.now().astimezone().strftime("%Y-%m-%d")), default=0.0)

    official_week = panel.window("week", now, account=acct)
    if official_week:
        w_end = official_week["resets_at"]
        week_window = (w_end - 7 * 24 * HOUR, w_end)
    else:
        week_window = anchors.week_window(now, account=acct)
    if week_window:
        w_start, w_end = week_window
        week = Bucket()
        for e in events:
            if w_start <= e.t < w_end:
                week.add(e)
        week_extra = {"window_source": "official" if official_week else "anchored",
                      "start": w_start, "end": w_end,
                      "remaining_s": max(0.0, w_end - now)}
    else:
        week = totals["last_7d"]
        week_extra = {"window_source": "rolling", "start": now - 7 * 24 * HOUR,
                      "end": now, "remaining_s": None}
    week_info = {**week.as_dict(), **_gauge(week.usd, lim_week),
                 "limit_source": src_week, **week_extra,
                 **_official_gauge(official_week, week)}

    live = live_sessions(acct)
    contexts = panel.contexts(account=acct)
    for item in live:
        b = per_session.get(item["session_id"])
        item["usage"] = b.as_dict() if b else Bucket().as_dict()
        item["context"] = contexts.get(item["session_id"], {})

    plan = cfg.get("plan_monthly_usd")
    value = totals["month"].usd
    roi = round(value / plan, 1) if plan else None

    return {
        "generated_at": now,
        "account": acct.as_dict(),
        "login": auth.status(acct, now),
        "block_hours": block_hours,
        "totals": {k: v.as_dict() for k, v in totals.items()},
        "today_gauge": {**totals["today"].as_dict(), **_gauge(totals["today"].usd, lim_day)},
        "block": block_info,
        "week": week_info,
        "daily": _fill_days(daily, 60),
        "hourly_24h": _fill_hours(hourly24, now),
        "heatmap": _heatmap(events, now),
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
        "local_currency": cfg.get("local_currency"),
        "i18n": {"language": i18n.language(), "tag": i18n.tag(), "catalog": i18n.catalog()},
        "thresholds": {"warn": cfg.get("warn_pct", 70), "critical": cfg.get("critical_pct", 90)},
    }


# ---------------------------------------------------------------- many accounts

ALL_ID = "__all__"


def per_account(cfg: dict | None = None) -> list[dict]:
    """One summary per configured account, in configured order."""
    cfg = cfg or config.load()
    return [summary(cfg=cfg, account=a) for a in accounts.listed(cfg)]


def combined(cfg: dict | None = None, parts: list[dict] | None = None) -> dict:
    """Money across every account, with the rate-limit windows deliberately out.

    Spend, tokens, requests, projects and models are additive and worth seeing
    together. Percentages are not: each subscription has its own ceiling and its
    own reset, so a single ring over both would be a number that does not exist.
    The per-account gauges are passed through untouched instead, for the UI to
    show side by side, and `window_source` is "combined" so nothing mistakes them.
    """
    cfg = cfg or config.load()
    found = accounts.listed(cfg)
    parts = parts if parts is not None else per_account(cfg)

    merged: list[Event] = []
    seen: set[str] = set()
    for account in found:
        for event in load_events(account):
            if event.k not in seen:      # two ids on one directory would double count
                seen.add(event.k)
                merged.append(event)
    merged.sort(key=lambda e: e.t)

    # a ghost account: its data dir does not exist, so no snapshot, anchor or
    # calibration leaks into a view that must not carry any of them
    ghost = Account(id=ALL_ID, label=t_all(), claude_dir=accounts.primary(cfg).claude_dir)
    out = summary(events=merged, cfg=cfg, account=ghost)

    gauges = [{"account": p["account"]["id"], "label": p["account"]["label"],
               "block": p["block"], "week": p["week"], "login": p.get("login")}
              for p in parts]
    for window in ("block", "week"):
        out[window] = {**out[window], "pct": None, "limit": None,
                       "window_source": "combined", "per_account": gauges}
    out["account"] = {"id": ALL_ID, "label": t_all(), "dir": "", "exists": True}
    # a login belongs to one account; the combined view carries them per account
    out["login"] = None
    out["per_account"] = gauges
    # each part already resolved its own sessions, with the right usage attached
    out["sessions"] = [s for p in parts for s in p["sessions"]]
    return out


def t_all() -> str:
    return i18n.t("all_accounts")


def overview(cfg: dict | None = None) -> dict:
    """What the dashboard needs to draw its tabs, in one round trip."""
    cfg = cfg or config.load()
    found = accounts.listed(cfg)
    return {
        "multi": len(found) > 1,
        "primary": accounts.primary(cfg).id,
        "all_id": ALL_ID,
        "accounts": [a.as_dict() for a in found],
    }
