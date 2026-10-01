import unittest

try:
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
    HAS_GTK = Gtk.init_check()[0]
except (ImportError, ValueError):
    HAS_GTK = False


@unittest.skipUnless(HAS_GTK, "needs PyGObject and a display")
class SettingsVersionTests(unittest.TestCase):
    def test_title_says_which_version_is_running(self):
        from cockpit import __version__, i18n
        from cockpit.preferences import Preferences
        i18n.use("pt")
        self.addCleanup(i18n.use, None)
        prefs = Preferences()
        self.addCleanup(prefs.destroy)
        # the same "v" form the dashboard shows beside its refresh time
        self.assertEqual(prefs.get_title(), f"Configurações do cc-cockpit · v{__version__}")


if __name__ == "__main__":
    unittest.main()
