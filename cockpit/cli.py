"""cc-cockpit command line."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import __version__, accounts, anchors, calibration, config, desktop, i18n, server, stats
from .collector import refresh
from .i18n import duration as _dur
from .i18n import money as _money
from .i18n import t
from .i18n import tokens as _toks
from .i18n import window_tail
from .stats import summary


def _bar(pct: float | None, width: int = 24) -> str:
    if pct is None:
        return "·" * width
    fill = int(min(pct, 100) / 100 * width)
    return "█" * fill + "░" * (width - fill)


def report(cfg: dict, s: dict | None = None) -> None:
    s = s if s is not None else summary(cfg=cfg)
    b, w, tot = s["block"], s["week"], s["totals"]
    who = (s.get("account") or {}).get("label") or ""
    head = f"cc-cockpit · {who}" if who and who != "default" else "cc-cockpit"
    print(f"\n\033[1m{head}\033[0m  ·  {t('sessions_open', n=len(s['sessions']))}\n")

    rows = (
        (t("block_of", h=f"{s['block_hours']:.0f}"), b,
         window_tail(b, is_block=True, sep=" · ")),
        (t("days7"), w, window_tail(w, sep=" · ")),
        (t("today"), s["today_gauge"], t("cache_hit_7d", p=f"{tot['last_7d']['cache_hit_pct']:.0f}")),
        (t("month"), {**tot["month"], "pct": None},
         t("tokens_requests", tok=_toks(tot["month"]["tokens"]), n=tot["month"]["requests"])),
    )
    label_width = max(len(r[0]) for r in rows)
    for label, d, extra in rows:
        pct = d.get("pct")
        if d.get("window_source") == "combined":
            extra = t("combined_note")
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


def _setup(args) -> int:
    if args.remove:
        removed = desktop.disable_autostart()
        print(f"autostart: {'removed' if removed else 'was not registered'}")
        print("statusline: remove the statusLine entry from ~/.claude/settings.json to undo it")
        return 0

    path = desktop.enable_autostart()
    print(f"autostart: {path}")

    if not args.no_statusline:
        from . import statusline as sl
        for account in accounts.listed():
            where = _tilde(sl.settings_file(account))
            print(f"statusline: {where}: {sl.install(account=account)}")

    ok, missing = desktop.tray_available()
    if ok:
        print("tray: ready")
    else:
        print(f"tray: unavailable - install {missing}")
        print("      the dashboard and 'report' work without it")
    # setup is where the panel side is worth saying out loud: the binding can be
    # installed and the indicator still invisible for want of a host on the panel
    print(f"      {desktop.tray_host_hint()}")
    events, new = refresh()
    print(t("cli_new_events", new=new, total=len(events)))
    return 0


# --------------------------------------------------------------------- accounts

def _accounts_cmd(args, cfg: dict) -> int:
    changed = False
    entries = list(cfg.get("accounts") or [])

    if args.detect:
        known = {str(a.claude_dir) for a in accounts.listed(cfg)} if entries else set()
        found = accounts.discover()
        print(t("acct_detected", n=len(found)))
        added = []
        for path in found:
            if str(path) in known:
                continue
            account_id = accounts.suggest_id(path)
            while any(e.get("id") == account_id for e in entries):
                account_id += "2"
            entries.append({"id": account_id, "label": account_id.title(),
                            "dir": _tilde(path)})
            added.append((account_id, path))
        if added:
            for account_id, path in added:
                print("  " + t("acct_added", id=account_id, dir=_tilde(path)))
            changed = True
        else:
            print("  " + t("acct_none_new"))

    if args.rename:
        for spec in args.rename:
            if "=" not in spec:
                print(f"--rename wants old=new, got {spec!r}")
                return 1
            old_id, _, new_id = spec.partition("=")
            try:
                note = accounts.rename(old_id.strip(), new_id.strip(), cfg)
            except ValueError as exc:
                print(str(exc))
                return 1
            for entry in entries:
                if entry.get("id") == old_id.strip():
                    entry["id"] = new_id.strip()
            if cfg.get("primary_account") == old_id.strip():
                cfg["primary_account"] = args.primary = new_id.strip()
            print(f"  {note}")
            changed = True

    if args.label:
        for spec in args.label:
            if "=" not in spec:
                print(f"--label wants id=name, got {spec!r}")
                return 1
            account_id, _, name = spec.partition("=")
            for entry in entries:
                if entry.get("id") == account_id.strip():
                    entry["label"] = name.strip()
                    changed = True
                    break
            else:
                # an implicit account has no entry yet; naming it creates one
                account = accounts.get(account_id.strip(), cfg)
                if account is None:
                    print(f"unknown account {account_id.strip()!r}")
                    return 1
                entries.append({"id": account.id, "label": name.strip(),
                                "dir": _tilde(account.claude_dir)})
                changed = True

    if args.add:
        for spec in args.add:
            if "=" not in spec:
                print(f"--add wants id=path, got {spec!r}")
                return 1
            account_id, _, raw = spec.partition("=")
            account_id = account_id.strip()
            entries = [e for e in entries if e.get("id") != account_id]
            entries.append({"id": account_id, "label": account_id.title(),
                            "dir": raw.strip()})
            changed = True

    if args.remove:
        before = len(entries)
        entries = [e for e in entries if e.get("id") not in args.remove]
        changed = changed or len(entries) != before

    if changed:
        cfg["accounts"] = entries
        stored = config.load()
        stored["accounts"] = entries
        if args.primary:
            stored["primary_account"] = cfg["primary_account"] = args.primary
        config.save(stored)
        # a renamed default must take its history along, or the pruned months go
        for account in accounts.listed(cfg):
            if accounts.rehome(account):
                print(f"  history moved into accounts/{account.id}/")
        if args.rename:
            # the id is baked into each settings.json, so it has to follow
            from . import statusline as sl
            for account in accounts.listed(cfg):
                print(f"  statusline {account.id}: {sl.install(account=account)}")
    elif args.primary:
        stored = config.load()
        stored["primary_account"] = cfg["primary_account"] = args.primary
        config.save(stored)

    primary = accounts.primary(cfg)
    for account in accounts.listed(cfg):
        mark = "*" if account.id == primary.id else " "
        note = "" if account.exists() else f"   ← {t('acct_missing')}"
        print(f" {mark} {account.id:<14} {_tilde(account.claude_dir)}{note}")
    if accounts.is_multi(cfg):
        print(f"\n  {t('combined_note')}")
        print("  cc-cockpit setup    " + t("acct_setup_hint"))
    return 0


def _tilde(path) -> str:
    text = str(path)
    home = str(Path.home())
    return "~" + text[len(home):] if text.startswith(home) else text


def _resolve_summary(args, cfg: dict):
    """The summary a command should act on: one account, or every account."""
    which = getattr(args, "account", None)
    if which in ("all", stats.ALL_ID):
        return stats.combined(cfg), None
    account = accounts.resolve(which, cfg)
    return summary(cfg=cfg, account=account), account


def _pct(value: str | None) -> float | None:
    if value is None:
        return None
    return float(value.strip().rstrip("%").replace(",", "."))


def _sync(args, cfg: dict) -> int:
    account = accounts.resolve(getattr(args, "account", None), cfg)
    if args.reset:
        anchors.clear(account=account)
        calibration.clear(account=account)
        print(t("sync_cleared"))
        return 0

    now = time.time()
    touched = False
    for flag, setter in (("block_reset", anchors.set_block_end),
                         ("week_reset", anchors.set_week_end)):
        raw = getattr(args, flag)
        if raw:
            try:
                setter(now + anchors.parse_duration(raw), account=account)
            except ValueError as exc:
                print(str(exc))
                return 1
            touched = True

    # the anchors have to be in place before the windows are measured
    s = summary(cfg=cfg, account=account)
    for window, raw in (("block", args.block), ("week", args.week)):
        pct = _pct(raw)
        if pct is None:
            continue
        used = s[window]["usd"]
        if used <= 0:
            print(t("cal_no_usage"))
            continue
        try:
            implied = calibration.add(window, used, pct, account=account)
        except ValueError as exc:
            print(str(exc))
            return 1
        print(t("cal_recorded", pct=f"{pct:g}", used=_money(used),
                window=window, v=_money(implied)))
        touched = True

    if touched:
        s = summary(cfg=cfg, account=account)
    _sync_state(s, account)
    return 0


def _sync_state(s: dict, account=None) -> None:
    data = calibration.load(account)
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
    parser.add_argument("--version", action="version", version=f"cc-cockpit {__version__}")
    parser.add_argument("--lang", choices=i18n.SUPPORTED, help="override the interface language")
    parser.add_argument("--account", metavar="ID",
                        help="which Claude Code account to act on ('all' to combine them)")
    sub = parser.add_subparsers(dest="cmd")
    acct = sub.add_parser("accounts", help="list and configure Claude Code accounts")
    acct.add_argument("--detect", action="store_true",
                      help="find ~/.claude* directories and register the new ones")
    acct.add_argument("--add", action="append", metavar="ID=DIR",
                      help="add or replace an account, e.g. pessoal=~/.claude-pessoal")
    acct.add_argument("--remove", action="append", metavar="ID", help="drop an account")
    acct.add_argument("--rename", action="append", metavar="OLD=NEW",
                      help="change an account id, moving its history with it")
    acct.add_argument("--label", action="append", metavar="ID=NAME",
                      help="set the name shown in the tray, tabs and report")
    acct.add_argument("--primary", metavar="ID",
                      help="which account the tray label speaks for")
    tray_cmd = sub.add_parser("tray", help="tray indicator (default)")
    tray_cmd.add_argument("--delay", type=float, default=0, metavar="SECONDS",
                          help="wait before starting, so the panel is up first "
                               "(the autostart entry uses it)")
    serve_cmd = sub.add_parser("serve", help="dashboard only")
    serve_cmd.add_argument("--port", type=int)
    serve_cmd.add_argument("--open", action="store_true")
    sub.add_parser("report", help="terminal summary")
    sub.add_parser("json", help="dump the summary as JSON")
    sub.add_parser("collect", help="ingest new transcripts and exit")
    sub.add_parser("config", help="show the config path and contents")
    setup_cmd = sub.add_parser(
        "setup", help="register autostart and the statusline capture")
    setup_cmd.add_argument("--no-statusline", action="store_true",
                           help="skip touching ~/.claude/settings.json")
    setup_cmd.add_argument("--remove", action="store_true", help="undo the autostart entry")
    line = sub.add_parser("statusline",
                          help="capture Claude Code's statusline payload (official numbers)")
    line.add_argument("--chain", help="run another statusline command and print its output")
    line.add_argument("--install", action="store_true",
                      help="register it in the account's settings.json (keeps a backup)")
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
    accounts.migrate(cfg)             # one-time move of a pre-accounts data dir

    cmd = args.cmd or "tray"
    try:
        # the statusline is exempt: it runs inside the CLI's own render loop, and
        # a stale --account left by a renamed account must not turn the user's
        # status line into an error message. It falls back to the primary below.
        if (args.account and cmd != "statusline"
                and args.account not in ("all", stats.ALL_ID)):
            accounts.resolve(args.account, cfg)      # fail fast on a typo
    except ValueError as exc:
        print(str(exc))
        return 1
    if cmd == "tray":
        delay = getattr(args, "delay", 0)   # absent when 'tray' came from the default
        if delay > 0:
            time.sleep(delay)
        from .tray import main as tray_main
        tray_main()
    elif cmd == "serve":
        server.serve(args.port, open_browser=args.open)
    elif cmd == "report":
        if args.account is None and accounts.is_multi(cfg):
            # no account asked for and several exist: show each, then the total
            parts = stats.per_account(cfg)
            for part in parts:
                report(cfg, part)
            report(cfg, stats.combined(cfg, parts))
        else:
            report(cfg, _resolve_summary(args, cfg)[0])
    elif cmd == "json":
        json.dump(_resolve_summary(args, cfg)[0], sys.stdout, indent=2, ensure_ascii=False)
        print()
    elif cmd == "accounts":
        return _accounts_cmd(args, cfg)
    elif cmd == "collect":
        total = new_total = 0
        for account in accounts.listed(cfg):
            events, new = refresh(account)
            total += len(events)
            new_total += new
        print(t("cli_new_events", new=new_total, total=total))
    elif cmd == "setup":
        return _setup(args)
    elif cmd == "statusline":
        from . import statusline as sl
        try:
            account = accounts.resolve(args.account, cfg)
        except ValueError:
            account = accounts.primary(cfg)   # renamed or dropped account
        if args.install:
            print(f"{_tilde(sl.settings_file(account))}: {sl.install(account=account)}")
            return 0
        return sl.main(args.chain, account=account)
    elif cmd == "sync":
        return _sync(args, cfg)
    elif cmd == "config":
        print(config.CONFIG_FILE)
        print(json.dumps(cfg, indent=2, ensure_ascii=False))
    return 0
