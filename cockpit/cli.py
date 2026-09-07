"""Linha de comando do cc-cockpit."""
from __future__ import annotations

import argparse
import json
import sys

from . import config, server
from .collector import refresh
from .stats import summary


def _money(v: float) -> str:
    return f"${v:,.2f}"


def _toks(n: int) -> str:
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if n >= div:
            return f"{n/div:.1f}{suf}" if div > 1e3 else f"{n/div:.0f}{suf}"
    return str(n)


def _dur(s: float) -> str:
    s = max(0, int(s))
    d, h, m = s // 86400, s % 86400 // 3600, s % 3600 // 60
    return f"{d}d {h}h" if d else (f"{h}h{m:02d}" if h else f"{m}min")


def _bar(pct: float | None, width: int = 24) -> str:
    if pct is None:
        return "·" * width
    fill = int(min(pct, 100) / 100 * width)
    return "█" * fill + "░" * (width - fill)


def report() -> None:
    s = summary()
    b, w, t = s["block"], s["week"], s["totals"]
    print(f"\n\033[1mcc-cockpit\033[0m  ·  {len(s['sessions'])} sessão(ões) aberta(s)\n")

    for title, d, extra in (
        (f"bloco {s['block_hours']:.0f}h", b,
         f"reseta em {_dur(b['remaining_s'])} · ritmo {_money(b['burn_usd_per_h'])}/h · "
         f"projeção {_money(b['projected_usd'])}" if b["active"] else "inativo"),
        ("7 dias", w, f"{w['requests']} requests · {w['sessions']} sessões"),
        ("hoje", {**t["today"], "pct": None}, f"{t['today']['requests']} requests"),
        ("mês", {**t["month"], "pct": None}, f"cache hit {t['month']['cache_hit_pct']:.0f}%"),
    ):
        pct = d.get("pct")
        pcts = f"{pct:5.1f}%" if pct is not None else "    —"
        print(f"  {title:<9} {_bar(pct)} {pcts}  {_money(d['usd']):>10}  {_toks(d['tokens']):>7} tok   {extra}")

    print("\n  \033[1msessões abertas\033[0m")
    if s["sessions"]:
        for x in s["sessions"]:
            mark = "\033[32m▶\033[0m" if x["status"] == "busy" else "·"
            print(f"   {mark} {x['name']:<14} {x['status']:<5} {_money(x['usage']['usd']):>9} "
                  f"{_toks(x['usage']['tokens']):>7}  há {_dur(x['uptime_s']):<7} {x['cwd']}")
    else:
        print("   (nenhuma)")

    print("\n  \033[1mprojetos · histórico\033[0m")
    for p in s["projects"][:8]:
        print(f"   {p['label'][:34]:<34} {_money(p['usd']):>10} {_toks(p['tokens']):>8}  {p['requests']:>5} req")

    print("\n  \033[1mmodelos\033[0m")
    for m in s["models"]:
        if m["requests"]:
            print(f"   {m['model'][:24]:<24} {_money(m['usd']):>10} {m['requests']:>6} req")

    a = t["all"]
    print(f"\n  histórico local: {a['requests']} requests · {_toks(a['tokens'])} tokens · "
          f"{_money(a['usd'])} equivalente API\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cc-cockpit", description="Painel de uso do Claude Code")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("tray", help="indicador na bandeja do GNOME (padrão)")
    p_serve = sub.add_parser("serve", help="só o dashboard web")
    p_serve.add_argument("--port", type=int)
    p_serve.add_argument("--open", action="store_true")
    sub.add_parser("report", help="resumo no terminal")
    sub.add_parser("json", help="despeja o resumo em JSON")
    sub.add_parser("collect", help="incorpora os transcripts novos e sai")
    sub.add_parser("config", help="mostra o caminho e o conteúdo da config")
    args = ap.parse_args(argv)

    cmd = args.cmd or "tray"
    if cmd == "tray":
        from .tray import main as tray_main
        tray_main()
    elif cmd == "serve":
        server.serve(args.port, open_browser=args.open)
    elif cmd == "report":
        report()
    elif cmd == "json":
        json.dump(summary(), sys.stdout, indent=2, ensure_ascii=False)
        print()
    elif cmd == "collect":
        events, new = refresh()
        print(f"{new} evento(s) novo(s) · {len(events)} no histórico")
    elif cmd == "config":
        cfg = config.ensure()
        print(config.CONFIG_FILE)
        print(json.dumps(cfg, indent=2, ensure_ascii=False))
    return 0
