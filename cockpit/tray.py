"""Indicador de bandeja do GNOME."""
from __future__ import annotations

import threading
import webbrowser

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

_IND_NS = None
for ns in ("AyatanaAppIndicator3", "AppIndicator3"):
    try:
        gi.require_version(ns, "0.1")
        _IND_NS = ns
        break
    except ValueError:
        continue

if _IND_NS is None:
    raise SystemExit(
        "Falta o binding do AppIndicator. Instale com:\n"
        "  sudo apt install gir1.2-ayatanaappindicator3-0.1\n"
        "e verifique se a extensao 'Ubuntu AppIndicators' esta ativa."
    )

if _IND_NS == "AyatanaAppIndicator3":
    from gi.repository import AyatanaAppIndicator3 as AppIndicator  # noqa: E402
else:
    from gi.repository import AppIndicator3 as AppIndicator  # noqa: E402

from . import config, icon, server  # noqa: E402
from .stats import summary  # noqa: E402

APP_ID = "cc-cockpit"


def _money(v: float) -> str:
    return f"${v:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")


def _toks(n: int) -> str:
    if n >= 1e9:
        return f"{n/1e9:.2f}B"
    if n >= 1e6:
        return f"{n/1e6:.1f}M"
    if n >= 1e3:
        return f"{n/1e3:.0f}k"
    return str(n)


def _dur(s: float) -> str:
    s = max(0, int(s))
    d, h, m = s // 86400, s % 86400 // 3600, s % 3600 // 60
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h{m:02d}"
    return f"{m}min"


class Tray:
    def __init__(self) -> None:
        self.cfg = config.ensure()
        self.seq = 0
        self.data: dict | None = None
        self.ind = AppIndicator.Indicator.new(
            APP_ID, "utilities-system-monitor",
            AppIndicator.IndicatorCategory.SYSTEM_SERVICES,
        )
        self.ind.set_icon_theme_path(str(icon.ICON_DIR))
        self.ind.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.menu = Gtk.Menu()
        self.ind.set_menu(self.menu)
        self.ind.set_label("cc", "cc-cockpit")

        port = int(self.cfg.get("dashboard_port") or 8765)
        threading.Thread(target=server.serve, args=(port,), daemon=True).start()
        self.url = f"http://127.0.0.1:{port}/"

        self.refresh()
        GLib.timeout_add_seconds(int(self.cfg.get("refresh_seconds") or 20), self._tick)

    # ---------- ciclo ----------
    def _tick(self) -> bool:
        self.refresh()
        return True

    def refresh(self, *_a) -> None:
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self) -> None:
        try:
            data = summary(cfg=self.cfg)
        except Exception as exc:  # nao deixa o tray morrer por erro de leitura
            data = {"error": str(exc)}
        GLib.idle_add(self._apply, data)

    def _apply(self, data: dict) -> bool:
        self.data = data
        if "error" in data:
            self.ind.set_label("cc ⚠", "cc-cockpit")
        else:
            self._paint(data)
        self._build_menu(data)
        return False

    # ---------- visual ----------
    def _paint(self, s: dict) -> None:
        metric = self.cfg.get("tray_metric", "block")
        src = {"block": s["block"], "week": s["week"], "today": {**s["totals"]["today"], "pct": None}}.get(metric)
        if metric == "none" or src is None:
            self.ind.set_label("", "cc-cockpit")
            pct = None
        else:
            pct = src.get("pct")
            bits = []
            if pct is not None:
                bits.append(f"{pct:.0f}%")
            if self.cfg.get("tray_show_cost", True):
                bits.append(_money(src["usd"]))
            self.ind.set_label(" · ".join(bits) or "—", "cc-cockpit 000%")
        th = s["thresholds"]
        state = icon.state_for(pct, th["warn"], th["critical"])
        self.seq += 1
        name = icon.render(pct, state, self.seq)
        self.ind.set_icon_full(name, "cc-cockpit")

    def _build_menu(self, s: dict) -> None:
        for child in self.menu.get_children():
            self.menu.remove(child)

        if "error" in s:
            self._info(f"erro: {s['error'][:80]}")
        else:
            b, w, t = s["block"], s["week"], s["totals"]
            head = f"Bloco de {s['block_hours']:.0f}h"
            if b["active"]:
                pct = f"{b['pct']:.0f}%" if b.get("pct") is not None else "—"
                self._info(f"{head}: {pct} · {_money(b['usd'])}")
                self._info(f"   reseta em {_dur(b['remaining_s'])} · ritmo {_money(b['burn_usd_per_h'])}/h")
                self._info(f"   projeção {_money(b['projected_usd'])}"
                           + (f" · teto em {_dur(b['eta_limit_s'])}" if b.get("eta_limit_s") else ""))
            else:
                self._info(f"{head}: inativo")
            wp = f"{w['pct']:.0f}%" if w.get("pct") is not None else "—"
            self._info(f"7 dias: {wp} · {_money(w['usd'])} · {_toks(w['tokens'])}")
            self._info(f"Hoje: {_money(t['today']['usd'])} · {_toks(t['today']['tokens'])} · "
                       f"{t['today']['requests']} req")
            self._info(f"Mês: {_money(t['month']['usd'])} · cache hit {t['last_7d']['cache_hit_pct']:.0f}%")

            self._sep()
            sess = s["sessions"]
            if sess:
                sub = Gtk.Menu()
                for x in sess:
                    mark = "▶" if x["status"] == "busy" else "•"
                    it = Gtk.MenuItem(label=f"{mark} {x['name']} · {_money(x['usage']['usd'])}")
                    inner = Gtk.Menu()
                    for line in (x["cwd"], f"pid {x['pid']} · {x['status']} · v{x['version']}",
                                 f"aberta há {_dur(x['uptime_s'])} · ociosa há {_dur(x['idle_s'])}",
                                 f"{_toks(x['usage']['tokens'])} tokens · {x['usage']['requests']} req",
                                 f"RAM {x['rss_mb']:.0f} MB"):
                        sit = Gtk.MenuItem(label=line)
                        sit.set_sensitive(False)
                        inner.append(sit)
                    it.set_submenu(inner)
                    sub.append(it)
                parent = Gtk.MenuItem(label=f"Sessões abertas ({len(sess)})")
                parent.set_submenu(sub)
                self.menu.append(parent)
            else:
                self._info("Nenhuma sessão aberta")

            if s["projects_today"]:
                sub = Gtk.Menu()
                for p in s["projects_today"]:
                    it = Gtk.MenuItem(label=f"{p['label']} · {_money(p['usd'])} · {_toks(p['tokens'])}")
                    it.set_sensitive(False)
                    sub.append(it)
                parent = Gtk.MenuItem(label="Projetos de hoje")
                parent.set_submenu(sub)
                self.menu.append(parent)

        self._sep()
        self._action("Abrir dashboard", lambda *_: webbrowser.open(self.url))
        self._action("Atualizar agora", self.refresh)
        self._action("Sair", lambda *_: Gtk.main_quit())
        self.menu.show_all()

    def _info(self, text: str) -> None:
        it = Gtk.MenuItem(label=text)
        it.set_sensitive(False)
        self.menu.append(it)

    def _sep(self) -> None:
        self.menu.append(Gtk.SeparatorMenuItem())

    def _action(self, label: str, cb) -> None:
        it = Gtk.MenuItem(label=label)
        it.connect("activate", cb)
        self.menu.append(it)


def main() -> None:
    Tray()
    Gtk.main()
