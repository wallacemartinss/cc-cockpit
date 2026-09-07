"""cc-cockpit command line."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import anchors, calibration, config, i18n, server
from .collector import refresh
from .i18n import duration as _dur
from .i18n import money as _money
from .i18n import t
from .i18n import tokens as _toks
from .stats import summary


def _bar(pct: float | None, width: int = 24) -> str:
    if pct is None:
        return "·" * width
    fill = int(min(pct, 100) / 100 * width)
    return "█" * fill + "░" * (width - fill)


def report(cfg: dict) -> None:
    s = summary(cfg=cfg)
    b, w, tot = s["block"], s["week"], s["totals"]
    print(f"\n\033[1mcc-cockpit\033[0m  ·  {t('sessions_open', n=len(s['sessions']))}\n")

    rows = (
        (t("block_of", h=f"{s['block_hours']:.0f}"), b,
         " · ".join((t("resets_in", d=_dur(b["remaining_s"])),
                     t("pace", v=_money(b["burn_usd_per_h"])),
                     t("projection", v=_money(b["projected_usd"]))))
         if b["active"] else t("no_activity")),
        (t("days7"), w, t("tokens_requests", tok=_toks(w["tokens"]), n=w["requests"])),
        (t("today"), s["today_gauge"], t("cache_hit_7d", p=f"{tot['last_7d']['cache_hit_pct']:.0f}")),
        (t("month"), {**tot["month"], "pct": None},
         t("tokens_requests", tok=_toks(tot["month"]["tokens"]), n=tot["month"]["requests"])),
    )
    label_width = max(len(r[0]) for r in rows)
    for label, d, extra in rows:
        pct = d.get("pct")
        shown = f"{pct:5.1f}%" if pct is not None else "     "
        print(f"  {label:<{label_width}} {_bar(pct)} {shown}  {_money(d['usd']):>12}   {extra}")

    print(f"\n  \033[1m{t('cli_sessions')}\033[0m")
    if s["sessions"]:
        for x in s["sessions"]:
            mark = "\033[32m▶\033[0m" if x["status"] == "busy" else "·"
            print(f"   {mark} {x['name']:<14} {x['status']:<5} {_money(x['usage']['usd']):>11} "
                  f"{_toks(x['usage']['tokens']):>7}  {_dur(x['uptime_s']):>7}  {x['cwd']}")
    else:
        print(f"   {t('cli_none')}")

    print(f"\n  \033[1m{t('cli_projects')}\033[0m")
    for p in s["projects"][:8]:
        print(f"   {p['label'][:34]:<34} {_money(p['usd']):>12} {_toks(p['tokens']):>8}  "
              f"{p['requests']:>5} {t('cli_requests_short')}")

    print(f"\n  \033[1m{t('cli_models')}\033[0m")
    for m in s["models"]:
        if m["requests"]:
            print(f"   {m['model'][:24]:<24} {_money(m['usd']):>12} {m['requests']:>6} "
                  f"{t('cli_requests_short')}")

    a = tot["all"]
    print("\n  " + t("cli_footer", n=a["requests"], tok=_toks(a["tokens"]), usd=_money(a["usd"])) + "\n")


def _pct(value: str | None) -> float | None:
    if value is None:
        return None
    return float(value.strip().rstrip("%").replace(",", "."))


def _sync(args, cfg: dict) -> int:
    if args.reset:
        anchors.clear()
        calibration.clear()
        print(t("sync_cleared"))
        return 0

    now = time.time()
    touched = False
    for flag, setter in (("block_reset", anchors.set_block_end),
                         ("week_reset", anchors.set_week_end)):
        raw = getattr(args, flag)
        if raw:
            try:
                setter(now + anchors.parse_duration(raw))
            except ValueError as exc:
                print(str(exc))
                return 1
            touched = True

    # the anchors have to be in place before the windows are measured
    s = summary(cfg=cfg)
    for window, raw in (("block", args.block), ("week", args.week)):
        pct = _pct(raw)
        if pct is None:
            continue
        used = s[window]["usd"]
        if used <= 0:
            print(t("cal_no_usage"))
            continue
        try:
            implied = calibration.add(window, used, pct)
        except ValueError as exc:
            print(str(exc))
            return 1
        print(t("cal_recorded", pct=f"{pct:g}", used=_money(used),
                window=window, v=_money(implied)))
        touched = True

    if touched:
        s = summary(cfg=cfg)
    _sync_state(s)
    return 0


def _sync_state(s: dict) -> None:
    data = calibration.load()
    for window in calibration.WINDOWS:
        info = s[window]
        limit = calibration.ceiling(window, data)
        remaining = info.get("remaining_s")
        print(t("sync_state",
                window=window,
                source=t("src_" + info.get("window_source", "local")),
                pct=f"{info['pct']:.1f}" if info.get("pct") is not None else "—",
                used=_money(info["usd"]),
                reset=_dur(remaining) if remaining else "—",
                n=len(data.get(window, [])),
                v=_money(limit) if limit else "—"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cc-cockpit", description="Claude Code usage panel")
    parser.add_argument("--lang", choices=i18n.SUPPORTED, help="override the interface language")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("tray", help="tray indicator for GNOME (default)")
    serve_cmd = sub.add_parser("serve", help="dashboard only")
    serve_cmd.add_argument("--port", type=int)
    serve_cmd.add_argument("--open", action="store_true")
    sub.add_parser("report", help="terminal summary")
    sub.add_parser("json", help="dump the summary as JSON")
    sub.add_parser("collect", help="ingest new transcripts and exit")
    sub.add_parser("config", help="show the config path and contents")
    line = sub.add_parser("statusline",
                          help="capture Claude Code's statusline payload (official numbers)")
    line.add_argument("--chain", help="run another statusline command and print its output")
    line.add_argument("--install", action="store_true",
                      help="register it in ~/.claude/settings.json (keeps a backup)")
    sync = sub.add_parser(
        "sync", help="feed it what Claude Code's usage panel shows (percent and reset)")
    sync.add_argument("--block", metavar="PCT", help="percent used in the current session window")
    sync.add_argument("--block-reset", metavar="TIME", help="e.g. '1h55' or '1 h 55 min'")
    sync.add_argument("--week", metavar="PCT", help="percent used in the weekly window")
    sync.add_argument("--week-reset", metavar="TIME", help="e.g. '1h15'")
    sync.add_argument("--reset", action="store_true", help="drop anchors and samples")
    args = parser.parse_args(argv)

    cfg = config.ensure()
    if args.lang:
        cfg["language"] = args.lang   # the flag outranks the config file
    i18n.use(cfg.get("language"))

    cmd = args.cmd or "tray"
    if cmd == "tray":
        from .tray import main as tray_main
        tray_main()
    elif cmd == "serve":
        server.serve(args.port, open_browser=args.open)
    elif cmd == "report":
        report(cfg)
    elif cmd == "json":
        json.dump(summary(cfg=cfg), sys.stdout, indent=2, ensure_ascii=False)
        print()
    elif cmd == "collect":
        events, new = refresh()
        print(t("cli_new_events", new=new, total=len(events)))
    elif cmd == "statusline":
        from . import statusline as sl
        if args.install:
            print(f"{sl.SETTINGS}: {sl.install()}")
            return 0
        return sl.main(args.chain)
    elif cmd == "sync":
        return _sync(args, cfg)
    elif cmd == "config":
        print(config.CONFIG_FILE)
        print(json.dumps(cfg, indent=2, ensure_ascii=False))
    return 0
