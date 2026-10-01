import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import copy

from cockpit import auth, config, stats
from cockpit.accounts import Account

PROFILE = {
    "displayName": "Claudio", "fullName": "Claudio Pereira", "emailAddress": "c@example.com",
    "organizationName": "c@example.com's Organization", "organizationType": "claude_max",
    "organizationRole": "admin", "organizationRateLimitTier": "default_claude_max_20x",
    "userRateLimitTier": None, "billingType": "stripe_subscription",
    "subscriptionCreatedAt": "2024-08-08T23:49:30.054216Z", "hasExtraUsageEnabled": True,
    "accountUuid": "uuid-should-not-leak",
}


class Sandbox(unittest.TestCase):
    """A default-layout account: <home>/.claude/ with <home>/.claude.json beside it."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        home = Path(temp.name)
        self.dir = home / ".claude"
        self.dir.mkdir()
        self.profile_file = home / ".claude.json"
        self.account = Account(id="default", label="", claude_dir=self.dir)

    def profile(self, **changes):
        self.profile_file.write_text(json.dumps({"oauthAccount": {**PROFILE, **changes}}))

    def credentials(self, **oauth):
        (self.dir / ".credentials.json").write_text(json.dumps({"claudeAiOauth": oauth}))


class AccountPlanTests(Sandbox):
    def test_profile_wins_over_stale_credentials(self):
        # the real case: upgraded to 20x, the token still says 5x
        self.profile()
        self.credentials(subscriptionType="max", rateLimitTier="default_claude_max_5x",
                         accessToken="sk-secret", refreshToken="rt-secret")
        plan = auth.account_plan(self.account)
        self.assertEqual((plan["name"], plan["monthly_usd"], plan["source"]),
                         ("Max 20x", 200.0, "profile"))
        self.assertEqual(plan["email"], "c@example.com")
        self.assertEqual(plan["full_name"], "Claudio Pereira")
        self.assertIsNone(plan["organization"])        # a personal org is noise
        self.assertEqual(plan["role"], "admin")
        self.assertEqual(plan["subscribed_since"], "2024-08-08")
        self.assertTrue(plan["extra_usage"])

    def test_company_organization_is_kept(self):
        self.profile(organizationName="Acme Ltda")
        self.assertEqual(auth.account_plan(self.account)["organization"], "Acme Ltda")

    def test_user_tier_when_the_org_has_none(self):
        self.profile(organizationRateLimitTier=None, userRateLimitTier="default_claude_max_5x")
        self.assertEqual(auth.account_plan(self.account)["name"], "Max 5x")

    def test_falls_back_to_credentials_without_a_profile(self):
        self.credentials(subscriptionType="max", rateLimitTier="default_claude_max_5x")
        plan = auth.account_plan(self.account)
        self.assertEqual((plan["name"], plan["monthly_usd"], plan["source"]),
                         ("Max 5x", 100.0, "credentials"))
        self.assertIsNone(plan["email"])

    def test_pro(self):
        self.profile(organizationType="claude_pro", organizationRateLimitTier="default_claude_pro")
        plan = auth.account_plan(self.account)
        self.assertEqual((plan["name"], plan["monthly_usd"]), ("Pro", 20.0))

    def test_unknown_tier_gets_a_name_and_no_price(self):
        self.profile(organizationRateLimitTier="something_new")
        plan = auth.account_plan(self.account)
        self.assertEqual((plan["name"], plan["monthly_usd"]), ("Max", None))

    def test_seat_plans_have_no_fixed_price(self):
        self.profile(organizationType="claude_team", organizationRateLimitTier=None,
                     organizationName="Acme")
        plan = auth.account_plan(self.account)
        self.assertEqual((plan["name"], plan["monthly_usd"]), ("Team", None))

    def test_no_login_at_all(self):
        self.assertIsNone(auth.account_plan(self.account))
        (self.dir / ".credentials.json").write_text("not json")
        self.assertIsNone(auth.account_plan(self.account))

    def test_secrets_and_ids_never_reach_the_result(self):
        self.profile()
        self.credentials(subscriptionType="max", accessToken="sk-secret", refreshToken="rt-secret")
        text = repr(auth.account_plan(self.account))
        for secret in ("secret", "uuid-should-not-leak"):
            self.assertNotIn(secret, text)

    def test_login_status_still_reads_the_same_file(self):
        self.credentials(subscriptionType="max", refreshTokenExpiresAt=2_000_000_000_000)
        status = auth.status(self.account, now=1_000_000_000)
        self.assertEqual(status["plan"], "max")
        self.assertEqual(status["expires_at"], 2_000_000_000.0)


class PlanPriceInStatsTests(Sandbox):
    """What the "paid for itself" line divides by."""

    def plan_block(self, cfg):
        base = {**copy.deepcopy(config.DEFAULTS), "recent_sessions": 0}
        with patch("cockpit.stats.accounts.listed", return_value=[self.account]):
            return stats.summary(events=[], cfg={**base, **cfg}, account=self.account)["plan"]

    def test_detected_price_by_default(self):
        self.profile()
        plan = self.plan_block({})
        self.assertEqual((plan["monthly_usd"], plan["name"], plan["source"]),
                         (200.0, "Max 20x", "profile"))

    def test_manual_cost_overrides_the_detected_one(self):
        self.profile()
        plan = self.plan_block({"plan_monthly_usd": 230})
        self.assertEqual((plan["monthly_usd"], plan["name"], plan["source"]),
                         (230, "Max 20x", "manual"))

    def test_typed_name_is_the_last_resort(self):
        plan = self.plan_block({"plan_name": "max_20x"})
        self.assertEqual((plan["monthly_usd"], plan["name"], plan["source"]),
                         (None, "max_20x", None))

    def test_combined_view_adds_the_accounts_up(self):
        parts = [{"plan": {"monthly_usd": 200.0, "name": "Max 20x"}},
                 {"plan": {"monthly_usd": 20.0, "name": "Pro"}},
                 {"plan": {"monthly_usd": None, "name": ""}}]
        self.assertEqual(stats.combined_plan(parts, manual=None, month_usd=440.0),
                         {"monthly_usd": 220.0, "name": "Max 20x + Pro",
                          "source": "profile", "value_this_month": 440.0, "roi": 2.0})

    def test_combined_view_respects_the_manual_cost(self):
        parts = [{"plan": {"monthly_usd": 200.0, "name": "Max 20x"}}]
        self.assertEqual(stats.combined_plan(parts, manual=250, month_usd=500.0)["roi"], 2.0)


if __name__ == "__main__":
    unittest.main()
