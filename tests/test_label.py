import unittest

from cockpit import i18n, label

BLOCK = {"pct": 10.4, "usd": 24.4712, "remaining_s": 3 * 3600 + 33 * 60, "eta_limit_s": 80 * 60}
WEEK = {"pct": 96.6, "usd": 815.54, "remaining_s": None}
TODAY = {"pct": 50.3, "usd": 152.07}


def face(**block):
    return {"account": {"id": "default", "label": "Claudio Pereira"},
            "block": {**BLOCK, **block}, "week": dict(WEEK), "today_gauge": dict(TODAY)}


class ComposeTests(unittest.TestCase):
    def setUp(self):
        i18n.use("pt")
        self.addCleanup(i18n.use, None)

    def text(self, fmt, metric="block", data=None, multi=False, cfg=None):
        return label.compose(fmt, metric, data or face(), multi=multi, cfg=cfg or {})

    def test_every_format_with_full_data(self):
        expected = {
            "pct": "10%",
            "pct_cost": "10% · US$ 24,47",
            "pct_cost_short": "10% · $24",
            "pct_reset": "10% · 3h33",
            "pct_reset_cost_short": "10% · 3h33 · $24",
            "pct_eta": "10% → 1h20",
            "block_week": "10% │ 97%",
            "reset": "3h33",
            "cost_short": "$24",
            "icon": "",
        }
        self.assertEqual(set(expected), set(label.FORMATS))
        for fmt, text in expected.items():
            self.assertEqual(self.text(fmt), text, fmt)

    def test_missing_pieces_drop_out(self):
        data = face(pct=None, remaining_s=None, eta_limit_s=None)
        self.assertEqual(self.text("pct_reset_cost_short", data=data), "$24")
        self.assertEqual(self.text("pct_eta", data=face(eta_limit_s=None)), "10%")
        self.assertEqual(self.text("reset", data=data), "—")      # never an empty label by accident

    def test_forecast_after_the_reset_is_left_out(self):
        # at this pace the ceiling is 11h30 away, but the window resets in 3h30
        data = face(remaining_s=3.5 * 3600, eta_limit_s=11.5 * 3600)
        self.assertEqual(self.text("pct_eta", data=data), "10%")

    def test_the_window_follows_the_metric(self):
        self.assertEqual(self.text("pct_cost_short", metric="week"), "97% · $816")
        self.assertEqual(self.text("pct_cost_short", metric="today"), "50% · $152")
        # a window without a reset or a forecast just has less to say
        self.assertEqual(self.text("pct_reset", metric="today"), "50%")

    def test_block_week_ignores_the_metric(self):
        self.assertEqual(self.text("block_week", metric="today"), "10% │ 97%")
        self.assertEqual(self.text("block_week", data=face(pct=None)), "— │ 97%")

    def test_metric_none_hides_the_text(self):
        self.assertEqual(self.text("pct_cost", metric="none"), "")

    def test_account_name_only_with_several_accounts(self):
        self.assertEqual(self.text("pct", multi=True), "10% · Claudio")
        self.assertEqual(self.text("icon", multi=True), "")

    def test_compact_money(self):
        self.assertEqual(label.compact_money(0.4, {}), "$0")
        self.assertEqual(label.compact_money(999.4, {}), "$999")
        self.assertEqual(label.compact_money(1234, {}), "$1,2k")
        i18n.use("en")
        self.assertEqual(label.compact_money(1234, {}), "$1.2k")
        local = {"local_currency": {"code": "BRL", "symbol": "R$", "rate": 5.4}}
        self.assertEqual(label.compact_money(24.47, local), "R$ 132")


class FormatChoiceTests(unittest.TestCase):
    """Nobody's tray changes until they pick a format."""

    def test_old_switch_on_keeps_the_value(self):
        self.assertEqual(label.format_of({"tray_label": None, "tray_show_cost": True}), "pct_cost")

    def test_old_switch_off_keeps_it_out(self):
        self.assertEqual(label.format_of({"tray_label": None, "tray_show_cost": False}), "pct")

    def test_an_explicit_choice_wins(self):
        self.assertEqual(label.format_of({"tray_label": "reset", "tray_show_cost": True}), "reset")

    def test_unknown_value_falls_back(self):
        self.assertEqual(label.format_of({"tray_label": "bogus"}), "pct_cost")

    def test_fresh_config_behaves_as_before(self):
        from cockpit import config
        self.assertIsNone(config.DEFAULTS["tray_label"])
        self.assertEqual(label.format_of(config.DEFAULTS), "pct_cost")


if __name__ == "__main__":
    unittest.main()
