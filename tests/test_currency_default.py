import unittest

from cockpit import i18n


class CurrencyDefaultTests(unittest.TestCase):
    """The currency the Plan tab offers before the user picks one."""

    def tearDown(self):
        i18n.use(None)

    def test_portuguese_offers_the_real(self):
        i18n.use("pt")
        self.assertEqual(i18n.default_currency(), {"code": "BRL", "symbol": "R$"})

    def test_other_languages_offer_nothing(self):
        for language in ("en", "es"):
            i18n.use(language)
            self.assertEqual(i18n.default_currency(), {}, language)

    def test_a_default_never_carries_a_rate(self):
        # without a rate the local figure stays off: nothing converts on a guess
        i18n.use("pt")
        self.assertNotIn("rate", i18n.default_currency())


if __name__ == "__main__":
    unittest.main()
