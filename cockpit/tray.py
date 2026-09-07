"""GNOME tray indicator."""
from __future__ import annotations

import subprocess
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
from .collector import DATA_DIR  # noqa: E402
from .i18n import duration as _dur  # noqa: E402
from .i18n import money as _money  # noqa: E402
from .i18n import t  # noqa: E402
from .i18n import tokens as _toks  # noqa: E402
from .i18n import use as use_language  # noqa: E402
from .stats import summary  # noqa: E402

APP_ID = "cc-cockpit"


# Solid blocks keep a single advance width in the panel font; the parallelogram
# pair (U+25B0/25B1) does not and comes out slanted and uneven.
BAR_STYLES = {
    "blocks": ("█", "░"),
    "dots": ("●", "○"),
    "emoji": ("🟩", "⬛"),
}


def _bar(pct: float | None, width: int, style: str, state: str = "ok") -> str:
    full, empty = BAR_STYLES.get(style, BAR_STYLES["blocks"])
    if style == "emoji":
        full = {"ok": "🟩", "warn": "🟨", "crit": "🟥", "idle": "⬛"}.get(state, "🟩")
    if pct is None:
        return empty * width
    fill = int(round(min(pct, 100) / 100 * width))
    return full * fill + empty * (width - fill)


class Tray:
    def __init__(self) -> None:
        self.cfg = config.ensure()
        use_language(self.cfg.get("language"))
        self._rebuilding = False
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
        self._rebuilding = True
        try:
            self._fill_menu(s)
        finally:
            self._rebuilding = False

    def _fill_menu(self, s: dict) -> None:
        for child in self.menu.get_children():
            self.menu.remove(child)

        if "error" in s:
            self._row(t("read_error"), icon.dot("crit"))
            self._row(s["error"][:70])
            self._sep()
            self._actions()
            self.menu.show_all()
            return

        style = self.cfg.get("menu_bar_style", "blocks")
        width = 10 if style == "emoji" else 18
        th = s["thresholds"]
        b, w, tot = s["block"], s["week"], s["totals"]

        # --- the two limit windows, each as a headline plus one dense line ---
        for info, title in ((b, t("block_of", h=f"{s['block_hours']:.0f}")),
                            (w, t("week_window") if w.get("window_source") in ("official", "anchored")
                                else t("days7"))):
            pct = info.get("pct")
            state = icon.state_for(pct, th["warn"], th["critical"])
            head = f"{title}   {pct:.0f}%" if pct is not None else title
            self._row(head, icon.dot(state, 22, pct if pct is not None else 0))
            self._row(f"{_bar(pct, width, style, state)}   {_money(info['usd'])}")
            tail = []
            if info.get("remaining_s"):
                tail.append(t("resets_in", d=_dur(info["remaining_s"])))
            if info is b and b["active"]:
                tail.append(t("pace", v=_money(b["burn_usd_per_h"])))
                tail.append(t("projection", v=_money(b["projected_usd"])))
            else:
                tail.append(_toks(info["tokens"]))
            self._row("   " + "  ·  ".join(tail))
            self._sep()

        # --- day, month, cache ---
        self._row(f"{t('today')}   {_money(tot['today']['usd'])}   "
                  f"{_toks(tot['today']['tokens'])}   {tot['today']['requests']} req",
                  icon.dot("idle", 22))
        self._row(f"{t('month')}   {_money(tot['month']['usd'])}   "
                  + t("cache_hit_7d", p=f"{tot['last_7d']['cache_hit_pct']:.0f}"),
                  icon.dot("idle", 22))
        self._sep()

        # --- live sessions, now with the context window from the statusline ---
        if not s["sessions"]:
            self._row(t("no_sessions"), icon.dot("idle", 22))
        for x in s["sessions"]:
            busy = x["status"] == "busy"
            ctx = (x.get("context") or {}).get("context_pct")
            bits = [x["name"], _money(x["usage"]["usd"])]
            if ctx is not None:
                bits.append(f"ctx {ctx:.0f}%")
            elif not busy:
                bits.append(t("idle_for", d=_dur(x["idle_s"])))
            item = Gtk.ImageMenuItem.new_with_label("   ".join(bits))
            item.set_image(Gtk.Image.new_from_file(
                icon.dot("ok" if busy else "idle", 22, 100 if busy else None)))
            item.set_always_show_image(True)
            inner = Gtk.Menu()
            state_line = t("working") if busy else t("idle_for", d=_dur(x["idle_s"]))
            lines = [
                x["cwd"],
                f"{state_line} · {t('open_for', d=_dur(x['uptime_s']))}",
                t("requests_tokens", n=x["usage"]["requests"], tok=_toks(x["usage"]["tokens"])),
                t("pid_line", pid=x["pid"], mb=f"{x['rss_mb']:.0f}", version=x["version"]),
            ]
            if ctx is not None:
                lines.insert(2, f"{_bar(ctx, width, style)}   ctx {ctx:.0f}%")
            for line in lines:
                sub_item = Gtk.MenuItem(label=line)
                sub_item.set_sensitive(False)
                inner.append(sub_item)
            item.set_submenu(inner)
            self.menu.append(item)

        # --- today's projects ---
        if s["projects_today"]:
            self._sep()
            top = s["projects_today"][:5]
            biggest = max(p["usd"] for p in top) or 1
            for p in top:
                self._row(f"{_bar(p['usd'] / biggest * 100, 6, style)}   "
                          f"{p['label'][:22]}   {_money(p['usd'])}")

        self._sep()
        self._actions()
        self.menu.show_all()

    def _actions(self) -> None:
        self._action(t("open_dashboard"), lambda *_: webbrowser.open(self.url))
        self._action(t("refresh_now"), self.refresh)

        settings = Gtk.MenuItem(label=t("settings"))
        settings.set_submenu(self._settings_menu())
        self.menu.append(settings)

        self._action(t("quit"), lambda *_: Gtk.main_quit())

    # ---------- settings ----------
    def _settings_menu(self) -> Gtk.Menu:
        menu = Gtk.Menu()
        block = t("block_of", h=f"{self.cfg.get('block_hours', 5):.0f}")
        self._choice(menu, t("panel_shows"), "tray_metric", [
            ("block", block), ("week", t("days7")),
            ("today", t("today")), ("none", t("metric_none"))])
        self._choice(menu, t("bar_style"), "menu_bar_style", [
            ("blocks", t("style_blocks")), ("dots", t("style_dots")),
            ("emoji", t("style_emoji"))])
        self._choice(menu, t("language_label"), "language", [
            ("auto", t("auto")), ("en", "English"),
            ("pt", "Português"), ("es", "Español")])

        show_cost = Gtk.CheckMenuItem(label=t("show_cost"))
        show_cost.set_active(bool(self.cfg.get("tray_show_cost", True)))
        show_cost.connect("toggled", lambda item: self._apply_setting(
            "tray_show_cost", item.get_active()))
        menu.append(show_cost)

        menu.append(Gtk.SeparatorMenuItem())
        for label, target in ((t("open_config"), config.CONFIG_FILE), (t("open_data"), DATA_DIR)):
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _i, path=target: self._open(path))
            menu.append(item)
        return menu

    def _choice(self, parent: Gtk.Menu, label: str, key: str,
                options: list[tuple[str, str]]) -> None:
        current = self.cfg.get(key)
        submenu = Gtk.Menu()
        for value, text in options:
            item = Gtk.CheckMenuItem(label=text)
            item.set_draw_as_radio(True)
            item.set_active(current == value)
            item.connect("toggled", self._on_choice, key, value)
            submenu.append(item)
        holder = Gtk.MenuItem(label=label)
        holder.set_submenu(submenu)
        parent.append(holder)

    def _on_choice(self, item: Gtk.CheckMenuItem, key: str, value: str) -> None:
        # set_active() during a rebuild also fires "toggled"; ignore those
        if self._rebuilding or not item.get_active():
            return
        self._apply_setting(key, value)

    def _apply_setting(self, key: str, value) -> None:
        if self.cfg.get(key) == value:
            return
        self.cfg[key] = value
        config.save(self.cfg)
        if key == "language":
            use_language(value)
        self.refresh()

    @staticmethod
    def _open(path) -> None:
        try:
            subprocess.Popen(["xdg-open", str(path)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass

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
