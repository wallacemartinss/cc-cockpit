"""Desktop integration: autostart entry, desktop detection and dependency hints.

Packaged installs have no checkout to run a shell script from, so this is what
`cc-cockpit setup` drives.

The tray speaks StatusNotifierItem through libayatana-appindicator, which is not
a GNOME protocol: any panel that implements the KDE spec hosts it. What differs
between desktops is which package puts that host on the bus, so the advice given
when the tray is missing has to follow the desktop actually in use.
"""
from __future__ import annotations

import configparser
import os
import shutil
import sys
from importlib import resources
from pathlib import Path

APP_ID = "cc-cockpit"

TEMPLATE = """[Desktop Entry]
Type=Application
Name=cc-cockpit
Comment=Claude Code usage in the tray
Exec={exec_line}
TryExec={try_exec}
Icon=cc-cockpit
Terminal=false
Categories=System;Monitor;
Hidden={hidden}
X-GNOME-Autostart-enabled={enabled}
"""

# The panel has to be up before the indicator registers, and only GNOME honours
# X-GNOME-Autostart-Delay - xfce4-session and lxsession ignore it. Waiting inside
# the command is the one form every session manager gets right.
AUTOSTART_DELAY = 8


def _xdg(var: str, default: str) -> Path:
    # an empty variable means unset, per the spec - not the current directory
    return Path(os.environ.get(var) or Path.home() / default)


def autostart_file() -> Path:
    """Resolved per call, so XDG_CONFIG_HOME is read when it is needed."""
    return _xdg("XDG_CONFIG_HOME", ".config") / "autostart" / f"{APP_ID}.desktop"


def _entries() -> list[Path]:
    """The user's entry first: by the XDG rule it shadows the system ones."""
    dirs = (os.environ.get("XDG_CONFIG_DIRS") or "/etc/xdg").split(":")
    return [autostart_file()] + [Path(d) / "autostart" / f"{APP_ID}.desktop" for d in dirs if d]


def _read(path: Path):
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(path, encoding="utf-8")
        return parser["Desktop Entry"]
    except (configparser.Error, KeyError, UnicodeDecodeError):
        return None


def autostart_enabled() -> bool:
    """Whether the session manager will start the tray at the next login."""
    for path in _entries():
        if not path.exists():
            continue
        entry = _read(path)
        if entry is None:
            return False
        try:
            return (not entry.getboolean("Hidden", fallback=False)
                    and entry.getboolean("X-GNOME-Autostart-enabled", fallback=True))
        except ValueError:
            return False
    return False


def autostart_declined() -> bool:
    """The user turned it off on purpose, so `setup` must not turn it back on."""
    path = autostart_file()
    return path.exists() and not autostart_enabled()


def executable() -> list[str]:
    """The installed entry point, or the module when run from a checkout.

    The entry point this process was started through comes first: with a .deb
    in /usr/bin and an old install.sh launcher in ~/.local/bin, PATH finds the
    launcher, and `/usr/bin/cc-cockpit --autostart on` has to mean /usr/bin.
    """
    invoked = Path(sys.argv[0]) if sys.argv and sys.argv[0] else None
    if (invoked and invoked.is_absolute() and invoked.name == APP_ID
            and os.access(invoked, os.X_OK)):
        return [str(invoked)]
    found = shutil.which("cc-cockpit")
    if found:
        return [found]
    return [sys.executable, "-m", "cockpit"]


def _exec_quote(program: str) -> str:
    """Quotes a path for Exec=. Two escaping layers apply: the Exec rules
    (backslash, quote, backtick, dollar inside quotes; % doubled) and then the
    string rules of the file itself, which double every backslash again."""
    if any(c in program for c in "\n\r"):
        raise ValueError(f"cannot write a desktop entry for {program!r}")
    quoted = program.replace("\\", "\\\\")
    for char in ('"', "`", "$"):
        quoted = quoted.replace(char, "\\" + char)
    return '"' + quoted.replace("\\", "\\\\").replace("%", "%%") + '"'


def _write_autostart(enabled: bool) -> Path:
    program, *rest = executable()
    exec_line = " ".join([_exec_quote(program), *rest, "tray", "--delay", str(AUTOSTART_DELAY)])
    path = autostart_file()
    content = TEMPLATE.format(
        exec_line=exec_line,
        # TryExec keeps a stale entry quiet once the package is removed
        try_exec=program.replace("\\", "\\\\"),
        hidden=str(not enabled).lower(),
        enabled=str(enabled).lower())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def enable_autostart() -> Path:
    return _write_autostart(True)


def disable_autostart() -> bool:
    """Turns it off and says whether it was on.

    The entry is rewritten with Hidden=true rather than deleted: that is how
    the XDG spec lets a user switch off an entry installed under /etc/xdg, and
    it is what tells a later `setup` that the answer was no - which is why it
    is written even when nothing was registered yet.
    """
    was = autostart_enabled()
    _write_autostart(False)
    return was


SYSTEM_ICON_DIRS = (Path("/usr/share/icons"), Path("/usr/local/share/icons"))
ICON_SUBPATH = Path("hicolor/scalable/apps") / f"{APP_ID}.svg"


def install_icon() -> Path | None:
    """Copies the app icon into the user's theme, for pip and pipx installs.

    The .deb and the AUR package put it under /usr/share already; there is
    nothing to add then. Returns where it was written, or None.
    """
    if any((d / ICON_SUBPATH).exists() for d in SYSTEM_ICON_DIRS):
        return None
    target = _xdg("XDG_DATA_HOME", ".local/share") / "icons" / ICON_SUBPATH
    source = resources.files("cockpit").joinpath("assets", f"{APP_ID}.svg").read_bytes()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source)
    return target


# Names that identify a desktop in XDG_CURRENT_DESKTOP. The variable often
# carries the distribution first ("ubuntu:GNOME"), so the list is what decides.
KNOWN_DESKTOPS = ("gnome", "xfce", "lxde", "lxqt", "kde", "plasma", "mate",
                  "cinnamon", "budgie", "unity", "pantheon")

# What has to be running for a StatusNotifierItem to be shown, per desktop.
TRAY_HOSTS = {
    "gnome": ("GNOME: enable the AppIndicator extension "
              "(gnome-shell-extension-appindicator)."),
    "xfce": ("XFCE: add 'Status Tray Items' to the panel - xfce4-panel 4.16+ "
             "hosts indicators on its own. On 4.14 install "
             "xfce4-statusnotifier-plugin instead."),
    "lxde": ("LXDE: lxpanel has no StatusNotifierItem host, so the indicator "
             "falls back to the old XEmbed tray and loses its panel label. "
             "snixembed restores the indicator path."),
    "lxqt": "LXQt: enable the Status Notifier plugin on the panel.",
    "mate": "MATE: add 'Indicator Applet' or 'Notification Area' to the panel.",
}
_KDE_HOST = "the system tray hosts indicators natively - nothing to install."
TRAY_HOSTS["kde"] = TRAY_HOSTS["plasma"] = f"KDE Plasma: {_KDE_HOST}"


def current_desktop() -> str:
    """The desktop in use, lowercased, or '' when it cannot be told."""
    raw = os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("DESKTOP_SESSION") or ""
    # Cinnamon and a few others announce themselves as "X-Cinnamon".
    parts = [p[2:] if p.startswith("x-") else p
             for p in raw.lower().replace(";", ":").split(":") if p]
    for part in parts:
        if part in KNOWN_DESKTOPS:
            return part
    return parts[-1] if parts else ""


def tray_host_hint() -> str:
    """What this desktop needs on the panel for the indicator to show up."""
    desktop = current_desktop()
    if desktop in TRAY_HOSTS:
        return TRAY_HOSTS[desktop]
    return ("Make sure the panel hosts StatusNotifierItem indicators"
            + (f" ({desktop})." if desktop else "."))


def tray_available() -> tuple[bool, str]:
    """Whether the tray can run here, and what to install when it cannot."""
    try:
        import gi  # noqa: F401
    except ImportError:
        return False, "python3-gi (Debian/Ubuntu) or python-gobject (Arch)"
    try:
        import cairo  # noqa: F401
    except ImportError:
        return False, "python3-cairo (Debian/Ubuntu) or python-cairo (Arch)"
    import gi
    for namespace in ("AyatanaAppIndicator3", "AppIndicator3"):
        try:
            gi.require_version(namespace, "0.1")
            return True, ""
        except ValueError:
            continue
    return False, ("gir1.2-ayatanaappindicator3-0.1 (Debian/Ubuntu) or "
                   "libayatana-appindicator (Arch)")
