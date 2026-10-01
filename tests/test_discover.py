import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cockpit import accounts


class DiscoverTests(unittest.TestCase):
    """What `accounts --detect` and Settings offer as a Claude Code account."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        env = patch.dict(os.environ, {"HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
        running = patch("cockpit.accounts.running_config_dirs", return_value=[])
        running.start()
        self.addCleanup(running.stop)

    def make(self, name, *entries):
        path = self.home / name
        path.mkdir()
        for entry in entries:
            if entry.endswith("/"):
                (path / entry).mkdir()
            else:
                (path / entry).write_text("{}")
        return path

    def test_a_plugin_folder_with_only_a_settings_file_is_not_an_account(self):
        # ~/.claude-mem, from the claude-mem plugin: its own settings.json and a database
        self.make(".claude-mem", "settings.json", "claude-mem.db", "chroma/", "logs/")
        self.assertNotIn(self.home / ".claude-mem", accounts.discover())

    def test_real_homes_are_still_found(self):
        default = self.make(".claude", "projects/", "settings.json")
        logged_in = self.make(".claude-work", ".credentials.json")
        used = self.make(".claude-pessoal", "sessions/")
        own_state = self.make(".claude-empresa", ".claude.json")
        found = accounts.discover()
        for path in (default, logged_in, used, own_state):
            self.assertIn(path, found, path.name)

    def test_settings_alone_is_not_enough_anywhere(self):
        self.assertFalse(accounts.looks_like_claude_home(self.make(".claude-x", "settings.json")))

    def test_a_running_claude_code_is_trusted_as_is(self):
        # a CLAUDE_CONFIG_DIR in use right now is an account even before it has history
        fresh = self.make(".claude-fresh", "settings.json")
        with patch("cockpit.accounts.running_config_dirs", return_value=[fresh]):
            self.assertIn(fresh, accounts.discover())


if __name__ == "__main__":
    unittest.main()
