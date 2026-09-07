"""Preferences window.

The tray menu cannot host this: GNOME's appindicator extension renders submenus
inline and stops at one level, and a menu has nowhere to type a number anyway.
"""
from __future__ import annotations

import subprocess

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from . import config  # noqa: E402
from .collector import DATA_DIR  # noqa: E402
from .i18n import t  # noqa: E402

SPACING = 8


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
        self.set_default_size(460, -1)
        self.set_border_width(16)
        self.set_position(Gtk.WindowPosition.CENTER)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.add(outer)

        block_hours = f"{self.cfg.get('block_hours', 5):.0f}"
        general = self._section(outer, t("general"))
        self.metric = self._combo(general, 0, t("panel_shows"), "tray_metric", [
            ("block", t("block_of", h=block_hours)), ("week", t("days7")),
            ("today", t("today")), ("none", t("metric_none"))])
        self.style = self._combo(general, 1, t("bar_style"), "menu_bar_style", [
            ("blocks", t("style_blocks")), ("dots", t("style_dots")),
            ("emoji", t("style_emoji"))])
        self.language = self._combo(general, 2, t("language_label"), "language", [
            ("auto", t("auto")), ("en", "English"),
            ("pt", "Português"), ("es", "Español")])
        self.show_cost = Gtk.Switch(halign=Gtk.Align.START)
        self.show_cost.set_active(bool(self.cfg.get("tray_show_cost", True)))
        self._attach(general, 3, t("show_cost"), self.show_cost)
        self.refresh_seconds = self._spin(general, 4, t("refresh_every"),
                                          self.cfg.get("refresh_seconds", 20), 5, 600,
                                          suffix=t("seconds"))
        self.port = self._spin(general, 5, t("dashboard_port"),
                               self.cfg.get("dashboard_port", 8765), 1024, 65535)

        limits = self._section(outer, t("ceilings"), hint=t("ceilings_hint"))
        self.block_usd = self._entry(limits, 0, t("block_limit"),
                                     _number((self.cfg.get("limits") or {}).get("block_usd")))
        self.week_usd = self._entry(limits, 1, t("week_limit"),
                                    _number((self.cfg.get("limits") or {}).get("week_usd")))

        plan = self._section(outer, t("plan_title"), hint=t("plan_hint"))
        self.plan_name = self._entry(plan, 0, t("plan_name_label"), self.cfg.get("plan_name") or "")
        self.plan_cost = self._entry(plan, 1, t("plan_cost"),
                                     _number(self.cfg.get("plan_monthly_usd")))

        currency = self.cfg.get("local_currency") or {}
        money = self._section(outer, t("currency_title"))
        self.currency_code = self._entry(money, 0, t("currency_code"), currency.get("code", ""))
        self.currency_symbol = self._entry(money, 1, t("currency_symbol"), currency.get("symbol", ""))
        self.currency_rate = self._entry(money, 2, t("currency_rate"), _number(currency.get("rate")))

        alerts = self._section(outer, t("alerts"))
        self.warn = self._spin(alerts, 0, t("warn_at"), self.cfg.get("warn_pct", 70), 1, 100)
        self.critical = self._spin(alerts, 1, t("critical_at"), self.cfg.get("critical_pct", 90), 1, 200)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=SPACING)
        outer.pack_start(buttons, False, False, 0)
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

    # ---------- building blocks ----------
    def _section(self, parent: Gtk.Box, title: str, hint: str = "") -> Gtk.Grid:
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
               options: list[tuple[str, str]]) -> Gtk.ComboBoxText:
        combo = Gtk.ComboBoxText()
        for value, text in options:
            combo.append(value, text)
        combo.set_active_id(str(self.cfg.get(key, options[0][0])))
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

        cfg["warn_pct"] = int(self.warn.get_value())
        cfg["critical_pct"] = int(self.critical.get_value())

        config.save(cfg)
        if self.on_saved:
            self.on_saved(cfg)
        self.close()

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
