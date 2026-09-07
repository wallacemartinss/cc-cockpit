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


def _gaugebar(pct: float | None, width: int = 14) -> str:
    if pct is None:
        return "▱" * width
    fill = int(round(min(pct, 100) / 100 * width))
    return "▰" * fill + "▱" * (width - fill)


def _minibar(frac: float, width: int = 6) -> str:
    fill = max(1, int(round(frac * width)))
    return "▰" * fill + "▱" * (width - fill)


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
        self.ind.set_title("cc-cockpit")
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
            self._row("nao consegui ler o historico", icon.dot("crit"))
            self._row(s["error"][:70])
            self._sep()
            self._actions()
            self.menu.show_all()
            return

        th = s["thresholds"]
        b, w, t = s["block"], s["week"], s["totals"]

        # --- bloco de rate limit ---
        pct = b.get("pct") if b["active"] else None
        st = icon.state_for(pct, th["warn"], th["critical"])
        head = f"Bloco de {s['block_hours']:.0f}h"
        if pct is not None:
            head += f" · {pct:.0f}%"
        self._row(head, icon.dot(st, 16, pct if pct is not None else 0))
        if b["active"]:
            self._row(f"{_gaugebar(pct)}  {_money(b['usd'])}")
            self._row(f"reseta em {_dur(b['remaining_s'])} · {_money(b['burn_usd_per_h'])}/h "
                      f"· projeção {_money(b['projected_usd'])}")
            if b.get("eta_limit_s"):
                self._row(f"no ritmo atual, teto em {_dur(b['eta_limit_s'])}")
        else:
            self._row("sem atividade na janela atual")

        # --- semana ---
        self._sep()
        wp = w.get("pct")
        wst = icon.state_for(wp, th["warn"], th["critical"])
        self._row(f"7 dias · {wp:.0f}%" if wp is not None else "7 dias",
                  icon.dot(wst, 16, wp if wp is not None else 0))
        self._row(f"{_gaugebar(wp)}  {_money(w['usd'])} · {_toks(w['tokens'])}")

        # --- dia e mes ---
        self._sep()
        self._row(f"Hoje · {_money(t['today']['usd'])}", icon.dot("idle"))
        self._row(f"{_toks(t['today']['tokens'])} tokens · {t['today']['requests']} requests")
        self._row(f"Mês · {_money(t['month']['usd'])}", icon.dot("idle"))
        self._row(f"cache hit {t['last_7d']['cache_hit_pct']:.0f}% nos últimos 7 dias")

        # --- sessoes vivas ---
        self._sep()
        sess = s["sessions"]
        if not sess:
            self._row("Nenhuma sessão aberta", icon.dot("idle"))
        for x in sess:
            busy = x["status"] == "busy"
            it = Gtk.ImageMenuItem.new_with_label(
                f"{x['name']} · {_money(x['usage']['usd'])} · {_toks(x['usage']['tokens'])}")
            it.set_image(Gtk.Image.new_from_file(icon.dot("ok" if busy else "idle")))
            it.set_always_show_image(True)
            inner = Gtk.Menu()
            for line in (
                x["cwd"],
                f"{'trabalhando' if busy else 'ociosa há ' + _dur(x['idle_s'])} · aberta há {_dur(x['uptime_s'])}",
                f"{x['usage']['requests']} requests · {_toks(x['usage']['tokens'])} tokens",
                f"pid {x['pid']} · {x['rss_mb']:.0f} MB · v{x['version']}",
            ):
                sit = Gtk.MenuItem(label=line)
                sit.set_sensitive(False)
                inner.append(sit)
            it.set_submenu(inner)
            self.menu.append(it)

        # --- projetos do dia ---
        if s["projects_today"]:
            self._sep()
            top = s["projects_today"][:5]
            mx = max(p["usd"] for p in top) or 1
            self._row("Projetos de hoje", icon.dot("idle"))
            for p in top:
                self._row(f"{_minibar(p['usd'] / mx)} {p['label'][:24]} · {_money(p['usd'])}")

        self._sep()
        self._actions()
        self.menu.show_all()

    def _actions(self) -> None:
        self._action("Abrir dashboard", lambda *_: webbrowser.open(self.url))
        self._action("Atualizar agora", self.refresh)
        self._action("Sair", lambda *_: Gtk.main_quit())

    def _row(self, text: str, icon_path: str | None = None) -> None:
        """Linha informativa. Fica habilitada de proposito: item desabilitado
        no GNOME vira cinza-claro e o menu inteiro parece apagado."""
        if icon_path:
            it = Gtk.ImageMenuItem.new_with_label(text)
            it.set_image(Gtk.Image.new_from_file(icon_path))
            it.set_always_show_image(True)
        else:
            it = Gtk.MenuItem(label=text)
        it.connect("activate", lambda *_: None)
        self.menu.append(it)

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
