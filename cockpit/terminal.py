"""Opening a terminal on a session's directory.

What this deliberately does *not* do is raise the terminal a session is already
running in. That needs window activation by pid, and on Wayland it is not
available to an ordinary application: there is no wmctrl or xdotool to speak to,
and org.gnome.Shell.Eval is refused. So the offer is an honest one - a new
terminal in the same directory, resuming the same conversation. Claude Code
handles the overlap itself: `--resume` on a session that is still running says
so and starts a copy.
"""
from __future__ import annotations

import shlex
import shutil
import subprocess

# (binary, arguments before the command, how the command is passed)
#   "string" - one shell-quoted string, as ptyxis -x wants
#   "argv"   - the remaining arguments, as most others want
# The working directory is also handed to Popen, so a terminal missing the flag
# still lands in the right place.
LAUNCHERS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("ptyxis",              ("--new-window", "-d", "{cwd}", "-x"), "string"),
    ("gnome-terminal",      ("--working-directory={cwd}", "--"),   "argv"),
    ("konsole",             ("--workdir", "{cwd}", "-e"),          "argv"),
    ("xfce4-terminal",      ("--working-directory={cwd}", "-x"),   "argv"),
    ("kitty",               ("--directory", "{cwd}"),              "argv"),
    ("alacritty",           ("--working-directory", "{cwd}", "-e"), "argv"),
    ("foot",                ("-D", "{cwd}"),                       "argv"),
    ("wezterm",             ("start", "--cwd", "{cwd}", "--"),     "argv"),
    ("tilix",               ("-w", "{cwd}", "-e"),                 "argv"),
    ("terminator",          ("--working-directory={cwd}", "-x"),   "argv"),
    ("x-terminal-emulator", ("-e",),                               "argv"),
    ("xterm",               ("-e",),                               "argv"),
)


def launcher() -> tuple[str, tuple[str, ...], str] | None:
    """The first terminal emulator on PATH, or None."""
    for binary, prefix, mode in LAUNCHERS:
        found = shutil.which(binary)
        if found:
            return found, prefix, mode
    return None


def available() -> bool:
    return launcher() is not None


def argv_for(cwd: str, command: list[str] | tuple[str, ...]) -> list[str] | None:
    """The full argv that opens a terminal in `cwd` running `command`.

    The command is wrapped in a shell that keeps running afterwards: the window
    is meant to be a terminal in that project, not a flash that vanishes the
    moment the conversation is closed - or, worse, the moment it fails.
    """
    found = launcher()
    if found is None:
        return None
    binary, prefix, mode = found
    inner = " ".join(shlex.quote(a) for a in command)
    script = f'{inner}; exec "${{SHELL:-/bin/sh}}"'
    argv = [binary] + [part.format(cwd=cwd) for part in prefix]
    if mode == "string":
        argv.append(" ".join(shlex.quote(a) for a in ("sh", "-c", script)))
    else:
        argv += ["sh", "-c", script]
    return argv


def open_in(cwd: str, command: list[str] | tuple[str, ...]) -> bool:
    argv = argv_for(cwd, command)
    if argv is None:
        return False
    try:
        subprocess.Popen(argv, cwd=cwd or None,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)   # outlives the tray
    except OSError:
        return False
    return True


def resume(cwd: str, session_id: str) -> bool:
    """Opens a terminal continuing one Claude Code conversation."""
    claude = shutil.which("claude") or "claude"
    if not session_id:
        return open_in(cwd, [claude])
    return open_in(cwd, [claude, "--resume", session_id])
