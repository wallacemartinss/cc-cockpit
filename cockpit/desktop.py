"""Desktop integration: autostart entry, desktop detection and dependency hints.

Packaged installs have no checkout to run a shell script from, so this is what
`cc-cockpit setup` drives.

The tray speaks StatusNotifierItem through libayatana-appindicator, which is not
a GNOME protocol: any panel that implements the KDE spec hosts it. What differs
between desktops is which package puts that host on the bus, so the advice given
when the tray is missing has to follow the desktop actually in use.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

AUTOSTART_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart"
DESKTOP_FILE = AUTOSTART_DIR / "cc-cockpit.desktop"

TEMPLATE = """[Desktop Entry]
Type=Application
Name=cc-cockpit
Comment=Claude Code usage in the tray
Exec={exec_line}
Icon=utilities-system-monitor
Terminal=false
Categories=System;Monitor;
X-GNOME-Autostart-enabled=true
"""

# The panel has to be up before the indicator registers, and only GNOME honours
# X-GNOME-Autostart-Delay - xfce4-session and lxsession ignore it. Waiting inside
# the command is the one form every session manager gets right.
AUTOSTART_DELAY = 8


def executable() -> str:
    """The installed entry point, or the module when run from a checkout."""
    found = shutil.which("cc-cockpit")
    if found:
        return found
    return f"{sys.executable} -m cockpit"


def enable_autostart() -> Path:
    AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
    DESKTOP_FILE.write_text(TEMPLATE.format(
        exec_line=f"{executable()} tray --delay {AUTOSTART_DELAY}"))
    return DESKTOP_FILE


def disable_autostart() -> bool:
    if DESKTOP_FILE.exists():
        DESKTOP_FILE.unlink()
        return True
    return False


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
