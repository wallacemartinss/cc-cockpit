"""Tray indicator, over StatusNotifierItem.

Nothing here is GNOME-specific: libayatana-appindicator publishes the item on
the session bus and whichever panel implements the KDE spec renders it. What
changes between desktops is only which package provides that host, so the
message shown when the binding is missing asks desktop.py for the right advice.
"""
from __future__ import annotations

import shutil
import threading
import webbrowser
from dataclasses import dataclass

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

from . import accounts, config, icon, instance, server, stats, terminal  # noqa: E402
from .i18n import duration as _dur  # noqa: E402
from .i18n import money as _money  # noqa: E402
from .i18n import t  # noqa: E402
from .i18n import tokens as _toks  # noqa: E402
from .i18n import use as use_language  # noqa: E402
from .i18n import window_tail  # noqa: E402

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


@dataclass(frozen=True)
class Row:
    """One menu line, described before any widget exists.

    `shape` is what decides between a cheap label update and a full rebuild:
    two menus with the same shape hold the same widgets in the same order, so
    the panel never has to redraw the popup.
    """
    kind: str                                    # sep | row | session | action | picker
    label: str = ""
    icon: str | None = None
    lines: tuple = ()                            # session detail, as a submenu
    choices: tuple = ()                          # picker options: (id, label)
    active: str = ""
    action: object = None
    cwd: str = ""                                # where a session's terminal opens
    command: tuple = ()                          # what that terminal runs

    @property
    def shape(self) -> tuple:
        return (self.kind, len(self.lines), len(self.choices), bool(self.command))


class Tray:
    def __init__(self) -> None:
        self.cfg = config.ensure()
        use_language(self.cfg.get("language"))
        self._rebuilding = False
        self._items: list = []
        self._shape: tuple = ()
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
    # Composing the menu and rendering it are kept apart on purpose. The menu is
    # exported over dbusmenu and drawn by the panel, and there the two kinds of
    # change are not equal: adding or removing an item is a layout change, so
    # the shell tears the popup down and draws it again - that is the flicker,
    # and the reason an expanded session folded shut every twenty seconds.
    # Changing a label is a property update, applied in place. So a refresh that
    # keeps the same shape only writes labels, and the open popup is left alone.
    def _build_menu(self, s: dict) -> None:
        self._rebuilding = True
        try:
            self._render(self._compose(s))
        finally:
            self._rebuilding = False

    def _compose(self, s: dict) -> list[Row]:
        rows: list[Row] = []
        if "error" in s:
            rows.append(Row("row", t("read_error"), icon.dot("crit")))
            rows.append(Row("row", s["error"][:70]))
            rows.append(Row("sep"))
            return rows + self._action_rows()

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
                rows.append(Row("row", part["account"]["label"],
                                icon.dot(state, 22, pct if pct is not None else 0)))
            # only the account on the panel gets the pace and projection lines;
            # a full block for each would push the totals off a small screen
            rows += self._window_rows(part, style, width, th,
                                      detail=len(parts) == 1
                                      or part["account"]["id"] == primary_id)
            rows.append(Row("sep"))

        # --- day, month, cache ---
        rows.append(Row("row", f"{t('today')}   {_money(tot['today']['usd'])}   "
                        f"{_toks(tot['today']['tokens'])}   {tot['today']['requests']} req",
                        icon.dot("idle", 22)))
        rows.append(Row("row", f"{t('month')}   {_money(tot['month']['usd'])}   "
                        + t("cache_hit_7d", p=f"{tot['last_7d']['cache_hit_pct']:.0f}"),
                        icon.dot("idle", 22)))
        rows.append(Row("sep"))

        # --- live sessions, with the context window from the statusline ---
        if not s["sessions"]:
            rows.append(Row("row", t("no_sessions"), icon.dot("idle", 22)))
        for x in s["sessions"]:
            busy = x["status"] == "busy"
            ctx = (x.get("context") or {}).get("context_pct")
            bits = [x["name"], _money(x["usage"]["usd"])]
            if len(parts) > 1:
                bits.insert(1, x.get("account_label") or x.get("account") or "")
            if ctx is not None:
                bits.append(f"ctx {ctx:.0f}%")
            elif not busy:
                bits.append(t("idle_for", d=_dur(x["idle_s"])))
            state_line = t("working") if busy else t("idle_for", d=_dur(x["idle_s"]))
            lines = [
                x["cwd"],
                f"{state_line} · {t('open_for', d=_dur(x['uptime_s']))}",
                t("requests_tokens", n=x["usage"]["requests"], tok=_toks(x["usage"]["tokens"])),
                t("pid_line", pid=x["pid"], mb=f"{x['rss_mb']:.0f}", version=x["version"]),
            ]
            if ctx is not None:
                lines.insert(2, f"{_bar(ctx, width, style)}   ctx {ctx:.0f}%")
            rows.append(Row("session", "   ".join(bits),
                            icon.dot("ok" if busy else "idle", 22, 100 if busy else None),
                            tuple(lines), cwd=x["cwd"],
                            command=self._resume_command(x)))

        # --- today's projects ---
        if s["projects_today"]:
            rows.append(Row("sep"))
            top = s["projects_today"][:5]
            biggest = max(p["usd"] for p in top) or 1
            for p in top:
                rows.append(Row("row", f"{_bar(p['usd'] / biggest * 100, 6, style)}   "
                                f"{p['label'][:22]}   {_money(p['usd'])}"))

        rows.append(Row("sep"))
        return rows + self._action_rows()

    @staticmethod
    def _resume_command(session: dict) -> tuple:
        """How to reopen one conversation, or nothing when there is no terminal."""
        if not terminal.available() or not session.get("cwd"):
            return ()
        claude = shutil.which("claude") or "claude"
        session_id = session.get("session_id") or ""
        return (claude, "--resume", session_id) if session_id else (claude,)

    def _window_rows(self, part: dict, style: str, width: int, th: dict,
                     detail: bool) -> list[Row]:
        b, w = part["block"], part["week"]
        titles = (t("block_of", h=f"{part['block_hours']:.0f}"),
                  t("week_window") if w.get("window_source") in ("official", "anchored")
                  else t("days7"))
        rows: list[Row] = []
        for index, (info, title) in enumerate(zip((b, w), titles)):
            if index:
                rows.append(Row("sep"))     # the two windows are separate readings
            pct = info.get("pct")
            state = icon.state_for(pct, th["warn"], th["critical"])
            head = f"{title}   {pct:.0f}%" if pct is not None else title
            rows.append(Row("row", head, icon.dot(state, 22, pct if pct is not None else 0)))
            rows.append(Row("row", f"{_bar(pct, width, style, state)}   {_money(info['usd'])}"))
            if detail:
                rows.append(Row("row", "   " + window_tail(info, is_block=info is b)))
        return rows

    def _action_rows(self) -> list[Row]:
        rows: list[Row] = []
        found = accounts.listed(self.cfg)
        if len(found) > 1:
            rows.append(Row("picker", t("panel_account"),
                            choices=tuple((a.id, a.title) for a in found),
                            active=accounts.primary(self.cfg).id))
            rows.append(Row("sep"))
        rows.append(Row("action", t("open_dashboard"),
                        action=lambda *_: webbrowser.open(self.url)))
        rows.append(Row("action", t("refresh_now"), action=self.refresh))
        rows.append(Row("action", t("settings"), action=self._open_preferences))
        rows.append(Row("action", t("quit"), action=lambda *_: Gtk.main_quit()))
        return rows

    # ---------- rendering ----------
    def _render(self, rows: list[Row]) -> None:
        shape = tuple(r.shape for r in rows)
        if shape == self._shape and len(self._items) == len(rows):
            for row, item in zip(rows, self._items):
                self._update(row, item)
            return
        for child in self.menu.get_children():
            self.menu.remove(child)
        self._items = [self._create(row) for row in rows]
        for item in self._items:
            self.menu.append(item)
        self._shape = shape
        self.menu.show_all()

    def _create(self, row: Row):
        if row.kind == "sep":
            return Gtk.SeparatorMenuItem()
        if row.kind == "picker":
            item = Gtk.MenuItem(label=row.label)
            inner = Gtk.Menu()
            group = None
            choices = []
            for account_id, label in row.choices:
                choice = Gtk.RadioMenuItem(label=label)
                if group is None:
                    group = choice
                else:
                    choice.join_group(group)
                choice.set_active(account_id == row.active)
                choice.connect("toggled", self._pick_account, account_id)
                inner.append(choice)
                choices.append(choice)
            item.set_submenu(inner)
            item.cc_choices = choices
            return item
        if row.kind == "session":
            item = Gtk.ImageMenuItem.new_with_label(row.label)
            item.set_always_show_image(True)
            self._set_icon(item, row.icon)
            inner = Gtk.Menu()
            subs = []
            for line in row.lines:
                sub = Gtk.MenuItem(label=line)
                sub.set_sensitive(False)
                inner.append(sub)
                subs.append(sub)
            if row.command:
                inner.append(Gtk.SeparatorMenuItem())
                launch = Gtk.MenuItem(label=t("open_terminal"))
                launch.cc_handler = launch.connect(
                    "activate", self._open_terminal, row.cwd, row.command)
                inner.append(launch)
                item.cc_launch = launch
            item.set_submenu(inner)
            item.cc_lines = subs
            return item
        if row.kind == "action":
            item = Gtk.MenuItem(label=row.label)
            item.cc_handler = item.connect("activate", row.action)
            return item
        # an informational line. Deliberately left sensitive: an insensitive
        # item renders pale grey in GNOME and makes the whole menu look disabled
        if row.icon:
            item = Gtk.ImageMenuItem.new_with_label(row.label)
            item.set_always_show_image(True)
            self._set_icon(item, row.icon)
        else:
            item = Gtk.MenuItem(label=row.label)
        item.connect("activate", lambda *_: None)
        return item

    def _update(self, row: Row, item) -> None:
        """Writes a row onto an existing item, touching only what changed."""
        if row.kind == "sep":
            return
        if item.get_label() != row.label:
            item.set_label(row.label)
        if row.icon:
            self._set_icon(item, row.icon)
        if row.kind == "session":
            for line, sub in zip(row.lines, getattr(item, "cc_lines", [])):
                if sub.get_label() != line:
                    sub.set_label(line)
            launch = getattr(item, "cc_launch", None)
            if launch is not None and row.command:
                # the slot can be reused by a different session between refreshes
                launch.disconnect(launch.cc_handler)
                launch.cc_handler = launch.connect(
                    "activate", self._open_terminal, row.cwd, row.command)
        elif row.kind == "picker":
            for (account_id, label), choice in zip(row.choices,
                                                   getattr(item, "cc_choices", [])):
                if choice.get_label() != label:
                    choice.set_label(label)
                choice.set_active(account_id == row.active)
        elif row.kind == "action":
            # the callback closes over self.url, which the port can change
            handler = getattr(item, "cc_handler", None)
            if handler is not None:
                item.disconnect(handler)
            item.cc_handler = item.connect("activate", row.action)

    @staticmethod
    def _set_icon(item, path: str) -> None:
        """Only rewrite the image when the file actually changed."""
        if getattr(item, "cc_icon", None) == path:
            return
        item.set_image(Gtk.Image.new_from_file(path))
        item.cc_icon = path

    def _open_terminal(self, _widget, cwd: str, command: tuple) -> None:
        if not terminal.open_in(cwd, command):
            print(f"cc-cockpit: no terminal emulator found for {cwd}")

    def _pick_account(self, widget, account_id: str) -> None:
        # set_active() during a rebuild fires this too; only a real click counts
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


def main() -> None:
    # setup writes an autostart entry and the README also says to start the tray
    # by hand for the session already running, so this command gets run twice.
    # A second indicator with a dead dashboard is worse than a plain message.
    other = instance.claim()
    if other is not None:
        print(f"cc-cockpit: the tray is already running (pid {other})")
        return

    settings = Gtk.Settings.get_default()
    if settings is not None:
        # The state in this menu is carried by the coloured dots, and GTK hides
        # menu images unless this is on - it is off by default on several
        # desktops since GTK deprecated the property.
        settings.set_property("gtk-menu-images", True)
    Tray()
    try:
        Gtk.main()
    finally:
        instance.release()
