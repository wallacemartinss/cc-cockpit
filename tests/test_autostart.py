import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cockpit import desktop
from cockpit.cli import main


class Sandbox(unittest.TestCase):
    """XDG directories in a temp dir, and an installed entry point."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        env = patch.dict(os.environ, {
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "XDG_CONFIG_DIRS": str(self.root / "system"),
            "XDG_DATA_HOME": str(self.root / "data"),
        })
        env.start()
        self.addCleanup(env.stop)
        which = patch("cockpit.desktop.shutil.which", return_value="/usr/bin/cc-cockpit")
        which.start()
        self.addCleanup(which.stop)


class AutostartTests(Sandbox):
    def test_path_follows_xdg_config_home_at_call_time(self):
        self.assertEqual(desktop.autostart_file(),
                         self.root / "config/autostart/cc-cockpit.desktop")

    def test_enable_writes_a_visible_entry_with_delay_and_tryexec(self):
        path = desktop.enable_autostart()
        text = path.read_text()
        self.assertIn('Exec="/usr/bin/cc-cockpit" tray --delay 8\n', text)
        self.assertIn("TryExec=/usr/bin/cc-cockpit\n", text)
        self.assertIn("Icon=cc-cockpit\n", text)
        self.assertIn("Hidden=false\n", text)
        self.assertTrue(desktop.autostart_enabled())

    def test_disable_keeps_the_file_as_an_explicit_off(self):
        desktop.enable_autostart()
        self.assertTrue(desktop.disable_autostart())
        self.assertTrue(desktop.autostart_file().exists())
        self.assertIn("Hidden=true\n", desktop.autostart_file().read_text())
        self.assertFalse(desktop.autostart_enabled())
        self.assertTrue(desktop.autostart_declined())

    def test_disable_when_never_enabled_reports_so(self):
        self.assertFalse(desktop.disable_autostart())
        self.assertFalse(desktop.autostart_enabled())

    def test_disable_overrides_a_system_wide_entry(self):
        system = self.root / "system/autostart/cc-cockpit.desktop"
        system.parent.mkdir(parents=True)
        system.write_text("[Desktop Entry]\nType=Application\nExec=cc-cockpit tray\n")
        self.assertTrue(desktop.autostart_enabled())
        desktop.disable_autostart()
        self.assertFalse(desktop.autostart_enabled())
        self.assertNotIn("Hidden", system.read_text())   # the system file is untouched

    def test_gnome_flag_off_counts_as_disabled(self):
        path = desktop.autostart_file()
        path.parent.mkdir(parents=True)
        path.write_text("[Desktop Entry]\nExec=cc-cockpit tray\nX-GNOME-Autostart-enabled=false\n")
        self.assertFalse(desktop.autostart_enabled())

    def test_unreadable_entry_counts_as_disabled(self):
        path = desktop.autostart_file()
        path.parent.mkdir(parents=True)
        path.write_text("not an ini file")
        self.assertFalse(desktop.autostart_enabled())

    def test_exec_escapes_special_characters(self):
        with patch("cockpit.desktop.shutil.which", return_value='/opt/my app/$x%/cc-cockpit'):
            text = desktop.enable_autostart().read_text()
        self.assertIn('Exec="/opt/my app/\\\\$x%%/cc-cockpit" tray --delay 8\n', text)
        self.assertIn("TryExec=/opt/my app/$x%/cc-cockpit\n", text)

    def test_checkout_without_entry_point_runs_the_module(self):
        with patch("cockpit.desktop.shutil.which", return_value=None), \
                patch("cockpit.desktop.sys.executable", "/usr/bin/python3"):
            text = desktop.enable_autostart().read_text()
        self.assertIn('Exec="/usr/bin/python3" -m cockpit tray --delay 8\n', text)
        self.assertIn("TryExec=/usr/bin/python3\n", text)

    def test_absolute_invocation_wins_over_an_earlier_one_on_path(self):
        # `/usr/bin/cc-cockpit --autostart on` with an old launcher in ~/.local/bin
        with patch("cockpit.desktop.sys.argv", ["/usr/bin/cc-cockpit"]), \
                patch("cockpit.desktop.os.access", return_value=True), \
                patch("cockpit.desktop.shutil.which",
                      return_value="/home/u/.local/bin/cc-cockpit"):
            text = desktop.enable_autostart().read_text()
        self.assertIn('Exec="/usr/bin/cc-cockpit" tray --delay 8\n', text)

    def test_relative_or_foreign_invocation_falls_back_to_path(self):
        for argv0 in ("cc-cockpit", "/usr/lib/python3/dist-packages/cockpit/__main__.py"):
            with patch("cockpit.desktop.sys.argv", [argv0]), \
                    patch("cockpit.desktop.os.access", return_value=True):
                text = desktop.enable_autostart().read_text()
            self.assertIn('Exec="/usr/bin/cc-cockpit" tray', text, argv0)

    def test_path_with_newline_is_refused(self):
        with patch("cockpit.desktop.shutil.which", return_value="/opt/a\nb/cc-cockpit"):
            with self.assertRaises(ValueError):
                desktop.enable_autostart()
        self.assertFalse(desktop.autostart_file().exists())


class AutostartFlagTests(Sandbox):
    """`--autostart` only flips the preference: no config, no collection, no tray."""

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with patch("cockpit.cli.config.ensure") as ensure, \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        ensure.assert_not_called()
        return code, out.getvalue()

    def test_status_on_off_round_trip(self):
        self.assertEqual(self.run_cli("--autostart", "status"), (0, "autostart: off\n"))
        self.assertFalse(desktop.autostart_file().exists())
        self.assertEqual(self.run_cli("--autostart", "on"), (0, "autostart: on\n"))
        self.assertTrue(desktop.autostart_enabled())
        self.assertEqual(self.run_cli("--autostart", "off"), (0, "autostart: off\n"))
        self.assertFalse(desktop.autostart_enabled())

    def test_refuses_to_combine_with_a_subcommand(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(["--autostart", "on", "report"])


class SetupTests(Sandbox):
    """`setup` keeps enabling autostart, but no longer overrides an explicit off."""

    def run_setup(self, *extra):
        out = io.StringIO()
        with patch("cockpit.cli.refresh", return_value=([], 0)), \
                patch("cockpit.cli.accounts.listed", return_value=[]), \
                patch("cockpit.cli.accounts.discover", return_value=[]), \
                patch("cockpit.cli.config.ensure", return_value={}), \
                patch("cockpit.cli.accounts.migrate"), \
                contextlib.redirect_stdout(out):
            self.assertEqual(main(["setup", "--no-statusline", *extra]), 0)
        return out.getvalue()

    def test_fresh_setup_enables_autostart(self):
        self.assertIn("autostart: on", self.run_setup())
        self.assertTrue(desktop.autostart_enabled())

    def test_setup_keeps_an_explicit_off(self):
        desktop.enable_autostart()
        desktop.disable_autostart()
        output = self.run_setup()
        self.assertIn("autostart: off (kept", output)
        self.assertFalse(desktop.autostart_enabled())

    def test_off_before_the_first_setup_is_kept(self):
        # nothing registered yet: the "no" still has to be written down
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--autostart", "off"]), 0)
        self.assertIn("Hidden=true\n", desktop.autostart_file().read_text())
        self.assertIn("autostart: off (kept", self.run_setup())
        self.assertFalse(desktop.autostart_enabled())

    def test_setup_remove_turns_it_off(self):
        self.run_setup()
        self.assertIn("autostart: off", self.run_setup("--remove"))
        self.assertFalse(desktop.autostart_enabled())

    def test_setup_installs_the_icon_for_a_pip_install(self):
        with patch("cockpit.desktop.SYSTEM_ICON_DIRS", (self.root / "usr-share-icons",)):
            self.run_setup()
        icon = self.root / "data/icons/hicolor/scalable/apps/cc-cockpit.svg"
        self.assertTrue(icon.exists())
        self.assertIn("<svg", icon.read_text())

    def test_setup_leaves_the_icon_to_the_package(self):
        system = self.root / "usr-share-icons"
        (system / desktop.ICON_SUBPATH).parent.mkdir(parents=True)
        (system / desktop.ICON_SUBPATH).write_text("<svg/>")
        with patch("cockpit.desktop.SYSTEM_ICON_DIRS", (system,)):
            self.assertNotIn("icon:", self.run_setup())
        self.assertFalse((self.root / "data/icons" / desktop.ICON_SUBPATH).exists())


if __name__ == "__main__":
    unittest.main()
