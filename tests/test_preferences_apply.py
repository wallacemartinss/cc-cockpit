import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
    HAS_GTK = Gtk.init_check()[0]
except (ImportError, ValueError):
    HAS_GTK = False


@unittest.skipUnless(HAS_GTK, "needs PyGObject and a display")
class ApplyTests(unittest.TestCase):
    """Apply saves and tells the tray, but leaves Settings open."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        from cockpit import config
        for name, value in (("CONFIG_DIR", Path(temp.name)),
                            ("CONFIG_FILE", Path(temp.name) / "config.json")):
            p = patch.object(config, name, value)
            p.start()
            self.addCleanup(p.stop)
        from cockpit.preferences import Preferences
        self.saved = []
        self.prefs = Preferences(on_saved=self.saved.append)
        self.addCleanup(self.prefs.destroy)
        self.prefs.show_all()

    def test_apply_saves_and_keeps_the_window_open(self):
        from cockpit import config
        self.prefs.label_format.set_active_id("pct_reset")
        self.prefs._apply()
        self.assertEqual(config.load()["tray_label"], "pct_reset")
        self.assertEqual(self.saved[-1]["tray_label"], "pct_reset")
        self.assertTrue(self.prefs.get_visible())

    def test_applying_twice_reports_each_change(self):
        for fmt in ("reset", "block_week"):
            self.prefs.label_format.set_active_id(fmt)
            self.prefs._apply()
        self.assertEqual([c["tray_label"] for c in self.saved], ["reset", "block_week"])

    def test_save_still_closes(self):
        self.prefs._save()
        while Gtk.events_pending():        # close() takes effect on the next loop turn
            Gtk.main_iteration()
        self.assertFalse(self.prefs.get_visible())
        self.assertEqual(len(self.saved), 1)


if __name__ == "__main__":
    unittest.main()
