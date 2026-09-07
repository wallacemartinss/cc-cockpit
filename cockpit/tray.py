"""GNOME tray indicator."""
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
        "Missing the AppIndicator binding. Install it with:\n"
        "  sudo apt install gir1.2-ayatanaappindicator3-0.1\n"
        "and make sure the 'Ubuntu AppIndicators' extension is enabled."
    )

if _IND_NS == "AyatanaAppIndicator3":
    from gi.repository import AyatanaAppIndicator3 as AppIndicator  # noqa: E402
else:
    from gi.repository import AppIndicator3 as AppIndicator  # noqa: E402

from . import config, icon, server  # noqa: E402
from .i18n import duration as _dur  # noqa: E402
from .i18n import money as _money  # noqa: E402
from .i18n import t  # noqa: E402
from .i18n import tokens as _toks  # noqa: E402
from .i18n import use as use_language  # noqa: E402
from .stats import summary  # noqa: E402

APP_ID = "cc-cockpit"


def _gaugebar(pct: float | None, width: int = 14) -> str:
    if pct is None:
        return "▱" * width
    fill = int(round(min(pct, 100) / 100 * width))
    return "▰" * fill + "▱" * (width - fill)


def _minibar(frac: float, width: int = 6) -> str:
    fill = max(1, int(round(frac * width)))
    return "▰" * fill + "▱" * (width - fill)


class Tray:
    def __init__(self) -> None:
        self.cfg = config.ensure()
        use_language(self.cfg.get("language"))
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
        self.ind.set_title(APP_ID)
        self.ind.set_label("cc", APP_ID)

        port = int(self.cfg.get("dashboard_port") or 8765)
        threading.Thread(target=server.serve, args=(port,), daemon=True).start()
        self.url = f"http://127.0.0.1:{port}/"

        self.refresh()
        GLib.timeout_add_seconds(int(self.cfg.get("refresh_seconds") or 20), self._tick)

    # ---------- cycle ----------
    def _tick(self) -> bool:
        self.refresh()
        return True

    def refresh(self, *_a) -> None:
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self) -> None:
        try:
            data = summary(cfg=self.cfg)
        except Exception as exc:  # a read error must not kill the indicator
            data = {"error": str(exc)}
        GLib.idle_add(self._apply, data)

    def _apply(self, data: dict) -> bool:
        self.data = data
        if "error" in data:
            self.ind.set_label("cc ⚠", APP_ID)
        else:
            self._paint(data)
        self._build_menu(data)
        return False

    # ---------- panel ----------
    def _paint(self, s: dict) -> None:
        metric = self.cfg.get("tray_metric", "block")
        src = {
            "block": s["block"],
            "week": s["week"],
            "today": s["today_gauge"],
        }.get(metric)
        if metric == "none" or src is None:
            self.ind.set_label("", APP_ID)
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
        self.ind.set_icon_full(icon.render(pct, state, self.seq), APP_ID)

    # ---------- menu ----------
    def _build_menu(self, s: dict) -> None:
        for child in self.menu.get_children():
            self.menu.remove(child)

        if "error" in s:
            self._row(t("read_error"), icon.dot("crit"))
            self._row(s["error"][:70])
            self._sep()
            self._actions()
            self.menu.show_all()
            return

        th = s["thresholds"]
        b, w, tot = s["block"], s["week"], s["totals"]

        # rate-limit block
        pct = b.get("pct") if b["active"] else None
        state = icon.state_for(pct, th["warn"], th["critical"])
        head = t("block_of", h=f"{s['block_hours']:.0f}")
        if pct is not None:
            head += f" · {pct:.0f}%"
        self._row(head, icon.dot(state, 16, pct if pct is not None else 0))
        if b["active"]:
            self._row(f"{_gaugebar(pct)}  {_money(b['usd'])}")
            self._row(" · ".join((
                t("resets_in", d=_dur(b["remaining_s"])),
                t("pace", v=_money(b["burn_usd_per_h"])),
                t("projection", v=_money(b["projected_usd"])),
            )))
            if b.get("eta_limit_s"):
                self._row(t("ceiling_eta", d=_dur(b["eta_limit_s"])))
        else:
            self._row(t("no_activity"))

        # rolling week
        self._sep()
        wp = w.get("pct")
        wstate = icon.state_for(wp, th["warn"], th["critical"])
        wtitle = t("week_window") if w.get("window_source") == "anchored" else t("days7")
        self._row(wtitle + (f" · {wp:.0f}%" if wp is not None else ""),
                  icon.dot(wstate, 16, wp if wp is not None else 0))
        self._row(f"{_gaugebar(wp)}  {_money(w['usd'])} · {_toks(w['tokens'])}")
        if w.get("remaining_s"):
            self._row(t("resets_in", d=_dur(w["remaining_s"])))

        # day and month
        self._sep()
        self._row(f"{t('today')} · {_money(tot['today']['usd'])}", icon.dot("idle"))
        self._row(t("tokens_requests", tok=_toks(tot["today"]["tokens"]),
                    n=tot["today"]["requests"]))
        self._row(f"{t('month')} · {_money(tot['month']['usd'])}", icon.dot("idle"))
        self._row(t("cache_hit_7d", p=f"{tot['last_7d']['cache_hit_pct']:.0f}"))

        # live sessions
        self._sep()
        if not s["sessions"]:
            self._row(t("no_sessions"), icon.dot("idle"))
        for x in s["sessions"]:
            busy = x["status"] == "busy"
            item = Gtk.ImageMenuItem.new_with_label(
                f"{x['name']} · {_money(x['usage']['usd'])} · {_toks(x['usage']['tokens'])}")
            item.set_image(Gtk.Image.new_from_file(icon.dot("ok" if busy else "idle")))
            item.set_always_show_image(True)
            inner = Gtk.Menu()
            state_line = t("working") if busy else t("idle_for", d=_dur(x["idle_s"]))
            for line in (
                x["cwd"],
                f"{state_line} · {t('open_for', d=_dur(x['uptime_s']))}",
                t("requests_tokens", n=x["usage"]["requests"], tok=_toks(x["usage"]["tokens"])),
                t("pid_line", pid=x["pid"], mb=f"{x['rss_mb']:.0f}", version=x["version"]),
            ):
                sub_item = Gtk.MenuItem(label=line)
                sub_item.set_sensitive(False)
                inner.append(sub_item)
            item.set_submenu(inner)
            self.menu.append(item)

        # today's projects
        if s["projects_today"]:
            self._sep()
            top = s["projects_today"][:5]
            biggest = max(p["usd"] for p in top) or 1
            self._row(t("projects_today"), icon.dot("idle"))
            for p in top:
                self._row(f"{_minibar(p['usd'] / biggest)} {p['label'][:24]} · {_money(p['usd'])}")

        self._sep()
        self._actions()
        self.menu.show_all()

    def _actions(self) -> None:
        self._action(t("open_dashboard"), lambda *_: webbrowser.open(self.url))
        self._action(t("refresh_now"), self.refresh)
        self._action(t("quit"), lambda *_: Gtk.main_quit())

    def _row(self, text: str, icon_path: str | None = None) -> None:
        """Informational line. Deliberately left sensitive: an insensitive item
        renders pale grey in GNOME and makes the whole menu look disabled."""
        if icon_path:
            item = Gtk.ImageMenuItem.new_with_label(text)
            item.set_image(Gtk.Image.new_from_file(icon_path))
            item.set_always_show_image(True)
        else:
            item = Gtk.MenuItem(label=text)
        item.connect("activate", lambda *_: None)
        self.menu.append(item)

    def _sep(self) -> None:
        self.menu.append(Gtk.SeparatorMenuItem())

    def _action(self, label: str, callback) -> None:
        item = Gtk.MenuItem(label=label)
        item.connect("activate", callback)
        self.menu.append(item)


def main() -> None:
    Tray()
    Gtk.main()
