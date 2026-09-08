"""Tray indicator, over StatusNotifierItem.

Nothing here is GNOME-specific: libayatana-appindicator publishes the item on
the session bus and whichever panel implements the KDE spec renders it. What
changes between desktops is only which package provides that host, so the
message shown when the binding is missing asks desktop.py for the right advice.
"""
from __future__ import annotations

import threading
import webbrowser

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from . import desktop as _desktop  # noqa: E402

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
        "  sudo apt install gir1.2-ayatanaappindicator3-0.1   # Debian/Ubuntu\n"
        "  sudo pacman -S libayatana-appindicator             # Arch\n"
        + _desktop.tray_host_hint()
    )

if _IND_NS == "AyatanaAppIndicator3":
    from gi.repository import AyatanaAppIndicator3 as AppIndicator  # noqa: E402
else:
    from gi.repository import AppIndicator3 as AppIndicator  # noqa: E402

from . import accounts, config, icon, server, stats  # noqa: E402
from .i18n import duration as _dur  # noqa: E402
from .i18n import money as _money  # noqa: E402
from .i18n import t  # noqa: E402
from .i18n import tokens as _toks  # noqa: E402
from .i18n import use as use_language  # noqa: E402

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
        self.prefs = None
        self.timer = None
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
        self.interval = int(self.cfg.get("refresh_seconds") or 20)
        self.timer = GLib.timeout_add_seconds(self.interval, self._tick)

    # ---------- cycle ----------
    def _tick(self) -> bool:
        self.refresh()
        return True

    def refresh(self, *_a) -> None:
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self) -> None:
        try:
            parts = stats.per_account(self.cfg)
            data = parts[0] if len(parts) == 1 else stats.combined(self.cfg, parts)
            data["parts"] = parts
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
        # With several accounts the label speaks for the primary one - a panel
        # has room for one number - but the ring takes the colour of whichever
        # account is worst off, so a 95% on the one you are not watching still
        # turns the icon red.
        parts = s.get("parts") or [s]
        primary = accounts.primary(self.cfg)
        face = next((p for p in parts if p["account"]["id"] == primary.id), parts[0])

        metric = self.cfg.get("tray_metric", "block")
        src = {
            "block": face["block"],
            "week": face["week"],
            "today": face["today_gauge"],
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
            if len(parts) > 1:
                bits.append(face["account"]["label"][:8])
            self.ind.set_label(" · ".join(bits) or "—", "cc-cockpit 000%")

        th = s["thresholds"]
        worst = pct
        for part in parts:
            other = part[metric if metric in ("block", "week") else "block"].get("pct")
            if other is not None and (worst is None or other > worst):
                worst = other
        state = icon.state_for(worst, th["warn"], th["critical"])
        self.seq += 1
        # the arc still shows the account on the label; only the colour escalates
        self.ind.set_icon_full(icon.render(pct, state, self.seq), APP_ID)

    # ---------- menu ----------
    def _build_menu(self, s: dict) -> None:
        # Nothing here owns the timer or the settings window, and wiping them on
        # every rebuild used to lose both: the timer id went missing so changing
        # the refresh interval stacked a second one instead of replacing it, and
        # the window reference went missing so Settings opened a new window on
        # every click after the first refresh.
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
        tot = s["totals"]

        # --- the limit windows, per account: they cannot be merged into one ---
        parts = s.get("parts") or [s]
        primary_id = accounts.primary(self.cfg).id
        for part in parts:
            if len(parts) > 1:
                pct = part["block"].get("pct")
                state = icon.state_for(pct, th["warn"], th["critical"])
                self._row(part["account"]["label"],
                          icon.dot(state, 22, pct if pct is not None else 0))
            # only the account on the panel gets the pace and projection lines;
            # a full block for each would push the totals off a small screen
            self._windows(part, style, width, th,
                          detail=len(parts) == 1 or part["account"]["id"] == primary_id)
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
            if len(s.get("parts") or [s]) > 1:
                bits.insert(1, x.get("account_label") or x.get("account") or "")
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

    def _windows(self, part: dict, style: str, width: int, th: dict, detail: bool) -> None:
        b, w = part["block"], part["week"]
        titles = (t("block_of", h=f"{part['block_hours']:.0f}"),
                  t("week_window") if w.get("window_source") in ("official", "anchored")
                  else t("days7"))
        for info, title in zip((b, w), titles):
            pct = info.get("pct")
            state = icon.state_for(pct, th["warn"], th["critical"])
            head = f"{title}   {pct:.0f}%" if pct is not None else title
            self._row(head, icon.dot(state, 22, pct if pct is not None else 0))
            self._row(f"{_bar(pct, width, style, state)}   {_money(info['usd'])}")
            if not detail:
                continue
            tail = []
            if info.get("remaining_s"):
                tail.append(t("resets_in", d=_dur(info["remaining_s"])))
            if info is b and b["active"]:
                tail.append(t("pace", v=_money(b["burn_usd_per_h"])))
                tail.append(t("projection", v=_money(b["projected_usd"])))
            else:
                tail.append(_toks(info["tokens"]))
            self._row("   " + "  ·  ".join(tail))

    def _actions(self) -> None:
        self._account_picker()
        self._action(t("open_dashboard"), lambda *_: webbrowser.open(self.url))
        self._action(t("refresh_now"), self.refresh)

        self._action(t("settings"), self._open_preferences)

        self._action(t("quit"), lambda *_: Gtk.main_quit())

    def _account_picker(self) -> None:
        """Which account the panel label speaks for, without opening Settings."""
        found = accounts.listed(self.cfg)
        if len(found) < 2:
            return
        current = accounts.primary(self.cfg).id
        item = Gtk.MenuItem(label=t("panel_account"))
        inner = Gtk.Menu()
        group = None
        for account in found:
            choice = Gtk.RadioMenuItem(label=account.title)
            if group is None:
                group = choice
            else:
                choice.join_group(group)
            choice.set_active(account.id == current)
            choice.connect("toggled", self._pick_account, account.id)
            inner.append(choice)
        item.set_submenu(inner)
        self.menu.append(item)
        self._sep()

    def _pick_account(self, widget, account_id: str) -> None:
        # set_active() during the rebuild fires this too; only a real click counts
        if self._rebuilding or not widget.get_active():
            return
        cfg = config.load()
        cfg["primary_account"] = account_id
        config.save(cfg)
        self.cfg = cfg
        self.refresh()

    # ---------- settings ----------
    def _open_preferences(self, *_a) -> None:
        if self.prefs and self.prefs.get_visible():
            self.prefs.present()
            return
        from .preferences import Preferences

        self.prefs = Preferences(on_saved=self._settings_saved)
        self.prefs.show_all()
        self.prefs.present()

    def _settings_saved(self, cfg: dict) -> None:
        self.cfg = cfg
        use_language(cfg.get("language"))
        seconds = int(cfg.get("refresh_seconds") or 20)
        if seconds != self.interval:
            if self.timer:
                GLib.source_remove(self.timer)
            self.interval = seconds
            self.timer = GLib.timeout_add_seconds(seconds, self._tick)
        self.refresh()

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
    settings = Gtk.Settings.get_default()
    if settings is not None:
        # The state in this menu is carried by the coloured dots, and GTK hides
        # menu images unless this is on - it is off by default on several
        # desktops since GTK deprecated the property.
        settings.set_property("gtk-menu-images", True)
    Tray()
    Gtk.main()
