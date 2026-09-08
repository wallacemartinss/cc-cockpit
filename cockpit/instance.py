"""One tray at a time.

`cc-cockpit tray` is both what the autostart entry runs and what the README
tells people to run by hand right after `setup`, so it gets run twice - by the
same person, on the same login. Without a guard that means two indicators in the
panel, and the second one cannot bind the dashboard port: its server thread dies
with a traceback and leaves an icon whose "Open dashboard" does nothing.

The pid file is validated the way sessions.py validates a live CLI - the pid has
to exist, its start time has to match, and it has to look like this program - so
a recycled pid is never mistaken for a running tray, and a tray that was killed
leaves nothing behind that blocks the next one.
"""
from __future__ import annotations

import os

from .accounts import DATA_DIR
from .sessions import cmdline, proc_starttime

PIDFILE = DATA_DIR / "tray.pid"


def running() -> int | None:
    """The pid of another live tray, or None."""
    try:
        pid_text, _, start = PIDFILE.read_text().strip().partition(" ")
        pid = int(pid_text)
    except (OSError, ValueError):
        return None
    if pid == os.getpid():
        return None
    if not start or proc_starttime(pid) != start:
        return None          # dead, or a recycled pid wearing its number
    if "cockpit" not in cmdline(pid):
        return None
    return pid


def claim() -> int | None:
    """Registers this process as the tray. Returns the pid already holding it."""
    other = running()
    if other is not None:
        return other
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        PIDFILE.write_text(f"{os.getpid()} {proc_starttime(os.getpid()) or ''}")
    except OSError:
        pass                 # a lock we cannot write is not worth failing over
    return None


def release() -> None:
    if running() is None and PIDFILE.exists():
        PIDFILE.unlink(missing_ok=True)
