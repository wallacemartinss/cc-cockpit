"""Desktop integration: autostart entry and statusline registration.

Packaged installs have no checkout to run a shell script from, so this is what
`cc-cockpit setup` drives.
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
X-GNOME-Autostart-Delay=8
"""


def executable() -> str:
    """The installed entry point, or the module when run from a checkout."""
    found = shutil.which("cc-cockpit")
    if found:
        return found
    return f"{sys.executable} -m cockpit"


def enable_autostart() -> Path:
    AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
    DESKTOP_FILE.write_text(TEMPLATE.format(exec_line=f"{executable()} tray"))
    return DESKTOP_FILE


def disable_autostart() -> bool:
    if DESKTOP_FILE.exists():
        DESKTOP_FILE.unlink()
        return True
    return False


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
