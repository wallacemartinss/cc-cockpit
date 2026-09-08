"""Preferences window.

The tray menu cannot host this: GNOME's appindicator extension renders submenus
inline and stops at one level, and a menu has nowhere to type a number anyway.

The settings are split across notebook tabs, and each tab scrolls. As one flat
column it had outgrown a laptop screen - the bottom rows, Save included, were
simply unreachable on a short display with no way to scroll to them.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from . import accounts, bars, config  # noqa: E402
from .accounts import DATA_DIR  # noqa: E402
from .i18n import t  # noqa: E402

SPACING = 8


def _tilde(path) -> str:
    text, home = str(path), str(Path.home())
    return "~" + text[len(home):] if text.startswith(home) else text


def _number(value) -> str:
    """Optional numbers show as an empty field, never as 'None'."""
    return "" if value in (None, "") else str(value)


def _parse_number(text: str) -> float | None:
    text = text.strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


class Preferences(Gtk.Window):
    def __init__(self, on_saved=None) -> None:
        super().__init__(title=t("prefs_title"))
        self.cfg = config.load()
        self.on_saved = on_saved
        self.set_default_size(520, 540)
        self.set_border_width(16)
        self.set_position(Gtk.WindowPosition.CENTER)

        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.add(frame)
        self.tabs = Gtk.Notebook()
        self.tabs.set_vexpand(True)
        frame.pack_start(self.tabs, True, True, 0)

        outer = self._page(t("tab_general"))
        block_hours = f"{self.cfg.get('block_hours', 5):.0f}"
        general = self._section(outer, "")
        self.metric = self._combo(general, 0, t("panel_shows"), "tray_metric", [
            ("block", t("block_of", h=block_hours)), ("week", t("days7")),
            ("today", t("today")), ("none", t("metric_none"))])
        # the list comes from bars.py, so a new style is added in one place, and
        # each option carries a sample - the name alone does not show the look
        self.style = self._combo(
            general, 1, t("bar_style"), "menu_bar_style",
            [(name, f"{t('style_' + name)}   {bars.sample(name)}") for name in bars.ORDER],
            current=bars.canonical(self.cfg.get("menu_bar_style")))
        self.language = self._combo(general, 2, t("language_label"), "language", [
            ("auto", t("auto")), ("en", "English"),
            ("pt", "Português"), ("es", "Español")])
        self.show_cost = Gtk.Switch(halign=Gtk.Align.START)
        self.show_cost.set_active(bool(self.cfg.get("tray_show_cost", True)))
        self._attach(general, 3, t("show_cost"), self.show_cost)
        # 0 is a real answer here - it takes the list out of the menu, the
        # dashboard and the report at once
        self.recent = self._spin(general, 4, t("recent_count"),
                                 self.cfg.get("recent_sessions", 5), 0, 20)
        self.refresh_seconds = self._spin(general, 5, t("refresh_every"),
                                          self.cfg.get("refresh_seconds", 20), 5, 600,
                                          suffix=t("seconds"))
        self.port = self._spin(general, 6, t("dashboard_port"),
                               self.cfg.get("dashboard_port", 8765), 1024, 65535)

        # The name is editable here; the id is not. An id names accounts/<id>/,
        # which holds months Claude Code has already pruned, so changing it has
        # to move a directory - that lives in `cc-cockpit accounts --rename`,
        # not behind a Save button. Adding and removing, on the other hand,
        # belong here: someone with a second account opens this tab to point at
        # it, and used to find only a sentence telling them to go to a terminal.
        self.primary = None
        self.aliases: dict[str, Gtk.Entry] = {}
        self.alias_was: dict[str, str] = {}
        self.accounts_box = self._page(t("accounts"))
        self._fill_accounts()

        limits_page = self._page(t("tab_limits"))
        limits = self._section(limits_page, t("ceilings"), hint=t("ceilings_hint"))
        self.block_usd = self._entry(limits, 0, t("block_limit"),
                                     _number((self.cfg.get("limits") or {}).get("block_usd")))
        self.week_usd = self._entry(limits, 1, t("week_limit"),
                                    _number((self.cfg.get("limits") or {}).get("week_usd")))

        plan_page = self._page(t("tab_plan"))
        plan = self._section(plan_page, t("plan_title"), hint=t("plan_hint"))
        self.plan_name = self._entry(plan, 0, t("plan_name_label"), self.cfg.get("plan_name") or "")
        self.plan_cost = self._entry(plan, 1, t("plan_cost"),
                                     _number(self.cfg.get("plan_monthly_usd")))

        currency = self.cfg.get("local_currency") or {}
        money = self._section(plan_page, t("currency_title"))
        self.currency_code = self._entry(money, 0, t("currency_code"), currency.get("code", ""))
        self.currency_symbol = self._entry(money, 1, t("currency_symbol"), currency.get("symbol", ""))
        self.currency_rate = self._entry(money, 2, t("currency_rate"), _number(currency.get("rate")))

        alerts = self._section(limits_page, t("alerts"))
        self.warn = self._spin(alerts, 0, t("warn_at"), self.cfg.get("warn_pct", 70), 1, 100)
        self.critical = self._spin(alerts, 1, t("critical_at"), self.cfg.get("critical_pct", 90), 1, 200)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=SPACING)
        frame.pack_start(buttons, False, False, 0)
        for label, target in ((t("open_config"), config.CONFIG_FILE), (t("open_data"), DATA_DIR)):
            link = Gtk.Button(label=label)
            link.set_relief(Gtk.ReliefStyle.NONE)
            link.connect("clicked", lambda _b, path=target: self._open(path))
            buttons.pack_start(link, False, False, 0)

        close = Gtk.Button(label=t("close"))
        close.connect("clicked", lambda *_: self.close())
        buttons.pack_end(close, False, False, 0)
        save = Gtk.Button(label=t("save"))
        save.get_style_context().add_class("suggested-action")
        save.connect("clicked", self._save)
        buttons.pack_end(save, False, False, 0)

    # ---------- accounts ----------
    def _fill_accounts(self) -> None:
        """(Re)builds the tab, because add and remove change its shape."""
        for child in self.accounts_box.get_children():
            self.accounts_box.remove(child)
        self.aliases, self.alias_was = {}, {}

        found = accounts.listed(self.cfg)
        grid = self._section(self.accounts_box, "", hint=t("accounts_hint"))
        for row, account in enumerate(found):
            entry = self._entry(grid, row, account.id, account.label or account.id)
            entry.set_placeholder_text(account.id)
            entry.set_tooltip_text(str(account.claude_dir))
            if not account.exists():
                entry.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY,
                                              "dialog-warning-symbolic")
                entry.set_icon_tooltip_text(Gtk.EntryIconPosition.SECONDARY,
                                            f"{t('acct_missing')}: {account.claude_dir}")
            self.aliases[account.id] = entry
            # what the field started with, so "changed" means the user typed
            self.alias_was[account.id] = entry.get_text()
            drop = Gtk.Button.new_from_icon_name("list-remove-symbolic", Gtk.IconSize.BUTTON)
            drop.set_relief(Gtk.ReliefStyle.NONE)
            drop.set_tooltip_text(t("acct_remove"))
            drop.connect("clicked", self._remove_account, account.id)
            grid.attach(drop, 2, row, 1, 1)

        if len(found) > 1:
            self.primary = self._combo(
                grid, len(found), t("panel_account"), "primary_account",
                [(a.id, a.title) for a in found],
                current=accounts.primary(self.cfg).id)
        else:
            self.primary = None

        # Directories on disk that nobody configured. Nothing is added behind
        # the user's back - a stray copy is not an account - but leaving them
        # unmentioned is how someone ends up staring at one account wondering
        # where the other went.
        configured = {str(a.claude_dir) for a in found}
        missing = [(path, accounts.suggest_label(path))
                   for path in accounts.discover() if str(path) not in configured]
        if missing:
            note = Gtk.Label(halign=Gtk.Align.START, wrap=True, xalign=0, margin_top=6)
            lines = "\n".join(f"  {_tilde(path)}" + (f"  · {who}" if who else "")
                               for path, who in missing)
            note.set_markup(
                f"<b>{GLib_escape(t('acct_found_unlisted', n=len(missing)))}</b>\n"
                f"<tt>{GLib_escape(lines)}</tt>\n"
                f"<small>{GLib_escape(t('acct_detect_hint'))}</small>")
            self.accounts_box.pack_start(note, False, False, 0)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=SPACING,
                          margin_top=4)
        for label, handler in ((t("acct_detect"), self._detect_accounts),
                               (t("acct_add"), self._add_account)):
            button = Gtk.Button(label=label)
            button.connect("clicked", handler)
            actions.pack_start(button, False, False, 0)
        self.accounts_box.pack_start(actions, False, False, 0)
        self.accounts_box.show_all()

    def _apply_accounts(self, entries: list) -> None:
        cfg = config.load()
        self._save_aliases(cfg)          # never lose what was being typed
        cfg["accounts"] = entries
        config.save(cfg)
        self.cfg = cfg
        for account in accounts.listed(cfg):
            accounts.rehome(account)     # a renamed default takes its history
        self._fill_accounts()
        if self.on_saved:
            self.on_saved(cfg)           # the tray picks it up without a restart

    def _detect_accounts(self, *_a) -> None:
        cfg = config.load()
        entries = list(cfg.get("accounts") or [])
        known = {str(a.claude_dir) for a in accounts.listed(cfg)} if entries else set()
        for path in accounts.discover():
            if str(path) in known:
                continue
            entries.append(self._entry_for(path, entries))
        self._apply_accounts(entries)

    def _add_account(self, *_a) -> None:
        chooser = Gtk.FileChooserDialog(
            title=t("acct_pick"), transient_for=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER)
        chooser.add_buttons(t("close"), Gtk.ResponseType.CANCEL,
                            t("acct_add"), Gtk.ResponseType.OK)
        chooser.set_current_folder(str(Path.home()))
        chooser.set_show_hidden(True)         # a Claude home starts with a dot
        picked = chooser.get_filename() if chooser.run() == Gtk.ResponseType.OK else None
        chooser.destroy()
        if not picked:
            return
        cfg = config.load()
        entries = list(cfg.get("accounts") or [])
        if not entries:                       # materialise the implicit one first
            current = accounts.primary(cfg)
            entries.append({"id": current.id, "label": current.label,
                            "dir": _tilde(current.claude_dir)})
        if any(str(Path(e.get("dir", "")).expanduser()) == picked for e in entries):
            return                            # already there
        entries.append(self._entry_for(Path(picked), entries))
        self._apply_accounts(entries)

    @staticmethod
    def _entry_for(path, entries: list) -> dict:
        account_id = accounts.suggest_id(path)
        while any(e.get("id") == account_id for e in entries):
            account_id += "2"
        return {"id": account_id,
                "label": accounts.suggest_label(path) or account_id.title(),
                "dir": _tilde(path)}

    def _remove_account(self, _button, account_id: str) -> None:
        cfg = config.load()
        entries = [e for e in (cfg.get("accounts") or []) if e.get("id") != account_id]
        self._apply_accounts(entries)

    # ---------- building blocks ----------
    def _page(self, title: str) -> Gtk.Box:
        """A notebook tab whose content scrolls when the screen is short."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14,
                      border_width=14)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.add(box)
        self.tabs.append_page(scroller, Gtk.Label(label=title))
        return box

    def _section(self, parent: Gtk.Box, title: str, hint: str = "") -> Gtk.Grid:
        # a tab holding a single section repeats itself with a header, so the
        # title is optional and the tab name carries it instead
        if title:
            label = Gtk.Label(halign=Gtk.Align.START)
            label.set_markup(f"<b>{GLib_escape(title)}</b>")
            parent.pack_start(label, False, False, 0)
        if hint:
            note = Gtk.Label(label=hint, halign=Gtk.Align.START, wrap=True, xalign=0)
            note.get_style_context().add_class("dim-label")
            parent.pack_start(note, False, False, 0)
        grid = Gtk.Grid(column_spacing=12, row_spacing=SPACING, margin_start=6)
        parent.pack_start(grid, False, False, 0)
        return grid

    def _attach(self, grid: Gtk.Grid, row: int, label: str, widget: Gtk.Widget) -> None:
        text = Gtk.Label(label=label, halign=Gtk.Align.START, xalign=0)
        grid.attach(text, 0, row, 1, 1)
        widget.set_hexpand(True)
        grid.attach(widget, 1, row, 1, 1)

    def _combo(self, grid: Gtk.Grid, row: int, label: str, key: str,
               options: list[tuple[str, str]], current: str | None = None) -> Gtk.ComboBoxText:
        combo = Gtk.ComboBoxText()
        for value, text in options:
            combo.append(value, text)
        combo.set_active_id(str(current if current is not None else self.cfg.get(key, options[0][0])))
        if combo.get_active_id() is None:
            combo.set_active_id(options[0][0])
        self._attach(grid, row, label, combo)
        return combo

    def _spin(self, grid: Gtk.Grid, row: int, label: str, value, low: int, high: int,
              suffix: str = "") -> Gtk.SpinButton:
        spin = Gtk.SpinButton.new_with_range(low, high, 1)
        spin.set_value(float(value or low))
        if suffix:
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            box.pack_start(spin, True, True, 0)
            box.pack_start(Gtk.Label(label=suffix), False, False, 0)
            self._attach(grid, row, label, box)
        else:
            self._attach(grid, row, label, spin)
        return spin

    def _entry(self, grid: Gtk.Grid, row: int, label: str, value: str) -> Gtk.Entry:
        entry = Gtk.Entry(text=value)
        self._attach(grid, row, label, entry)
        return entry

    # ---------- persistence ----------
    def _save(self, *_a) -> None:
        cfg = self.cfg
        cfg["tray_metric"] = self.metric.get_active_id()
        cfg["menu_bar_style"] = self.style.get_active_id()
        cfg["language"] = self.language.get_active_id()
        cfg["tray_show_cost"] = self.show_cost.get_active()
        cfg["recent_sessions"] = int(self.recent.get_value())
        cfg["refresh_seconds"] = int(self.refresh_seconds.get_value())
        cfg["dashboard_port"] = int(self.port.get_value())
        cfg["limits"] = {
            "block_usd": _parse_number(self.block_usd.get_text()),
            "week_usd": _parse_number(self.week_usd.get_text()),
        }
        cfg["plan_name"] = self.plan_name.get_text().strip()
        cfg["plan_monthly_usd"] = _parse_number(self.plan_cost.get_text())

        rate = _parse_number(self.currency_rate.get_text())
        symbol = self.currency_symbol.get_text().strip()
        cfg["local_currency"] = {
            "code": self.currency_code.get_text().strip().upper(),
            "symbol": symbol,
            "rate": rate,
        } if rate and symbol else None

        if self.primary is not None:
            cfg["primary_account"] = self.primary.get_active_id()
        self._save_aliases(cfg)
        cfg["warn_pct"] = int(self.warn.get_value())
        cfg["critical_pct"] = int(self.critical.get_value())

        config.save(cfg)
        if self.on_saved:
            self.on_saved(cfg)
        self.close()

    def _save_aliases(self, cfg: dict) -> None:
        """Writes the names back, materialising an implicit account if renamed.

        With nothing configured there is one implicit account and no entry in
        the file. Naming it has to create that entry - but only when the name
        actually changed, so an untouched install keeps following
        CLAUDE_CONFIG_DIR instead of freezing today's path into the config.
        """
        entries = list(cfg.get("accounts") or [])
        by_id = {e.get("id"): e for e in entries if isinstance(e, dict)}
        for account in accounts.listed(cfg):
            widget = self.aliases.get(account.id)
            if widget is None:
                continue
            name = widget.get_text().strip()
            if name == self.alias_was.get(account.id, ""):
                continue                       # untouched
            if account.id in by_id:
                by_id[account.id]["label"] = name
            else:
                entries.append({"id": account.id, "label": name,
                                "dir": _tilde(account.claude_dir)})
        if entries:
            cfg["accounts"] = entries

    @staticmethod
    def _open(path) -> None:
        try:
            subprocess.Popen(["xdg-open", str(path)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass


def GLib_escape(text: str) -> str:
    from gi.repository import GLib
    return GLib.markup_escape_text(text)
