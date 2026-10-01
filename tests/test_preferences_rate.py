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
class RateButtonTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        from cockpit import config
        for name, value in (("CONFIG_DIR", Path(temp.name)),
                            ("CONFIG_FILE", Path(temp.name) / "config.json")):
            p = patch.object(config, name, value)
            p.start()
            self.addCleanup(p.stop)
        # any network access during these tests is a failure
        guard = patch("cockpit.rate.urllib.request.urlopen",
                      side_effect=AssertionError("network used"))
        self.urlopen = guard.start()
        self.addCleanup(guard.stop)

    def open(self):
        from cockpit.preferences import Preferences
        prefs = Preferences()
        self.addCleanup(prefs.destroy)
        return prefs

    def test_opening_settings_never_touches_the_network(self):
        self.open()
        self.urlopen.assert_not_called()

    def test_button_only_for_the_real(self):
        prefs = self.open()
        prefs.currency_code.set_text("BRL")
        self.assertTrue(prefs.rate_button.get_sensitive())
        prefs.currency_code.set_text("eur")
        self.assertFalse(prefs.rate_button.get_sensitive())
        prefs.currency_code.set_text("brl")
        self.assertTrue(prefs.rate_button.get_sensitive())

    def test_a_result_fills_the_field_without_saving(self):
        from cockpit import config
        prefs = self.open()
        prefs._rate_done((5.1991, "25/09/2026"), None)
        self.assertEqual(prefs.currency_rate.get_text(), "5.1991")
        self.assertIn("25/09/2026", prefs.rate_status.get_text())
        self.assertIsNone(config.load()["local_currency"])

    def test_a_failure_leaves_the_field_alone(self):
        prefs = self.open()
        prefs.currency_rate.set_text("5.40")
        prefs._rate_done(None, "offline")
        self.assertEqual(prefs.currency_rate.get_text(), "5.40")
        self.assertIn("offline", prefs.rate_status.get_text())

    def test_default_restores_the_release_url_and_saves_nothing_extra(self):
        from cockpit import config, rate
        prefs = self.open()
        prefs.rate_url.set_text("https://mirror.example/api")
        prefs._save()
        self.assertEqual(config.load()["rate_url"], "https://mirror.example/api")
        prefs = self.open()
        self.assertEqual(prefs.rate_url.get_text(), "https://mirror.example/api")
        prefs.rate_default.clicked()
        self.assertEqual(prefs.rate_url.get_text(), rate.DEFAULT_URL)
        prefs._save()
        self.assertIsNone(config.load()["rate_url"])


if __name__ == "__main__":
    unittest.main()
