"""When the login expires, and which plan it is on.

Claude Code keeps its OAuth state in <account>/.credentials.json. Exactly three
fields are read from that file and nothing else: `refreshTokenExpiresAt`,
`subscriptionType` and `rateLimitTier`. The tokens sitting beside them are never
read, never stored, never printed, and never enter this module's return value.
The plan itself comes first from the profile in .claude.json, through
accounts.identity(); the two credential fields are its fallback.

The file holds a second timestamp, `expiresAt`, which is deliberately *not*
read. It belongs to the access token, which the CLI refreshes by itself - it
sits about four hours out at any moment, so surfacing it would announce an
expiry that never actually happens. `refreshTokenExpiresAt` is the one that
means "you will have to sign in again", and it is weeks away.

The file may not exist at all: a login kept in the system keyring, or a machine
that has never signed in. That is not an error, it is simply nothing to show.
"""
from __future__ import annotations

import json
import time

from .accounts import Account, identity, primary

# what counts as "soon", in days. The login is not a rate limit, so it does not
# share the configurable percentage thresholds
WARN_DAYS = 7
CRITICAL_DAYS = 2


# Which plan an account is on, for the Plan tab and the "paid for itself" line.
# The profile Claude Code keeps in .claude.json comes first: it is refetched,
# while the tier inside .credentials.json is fixed when the login happens and
# goes stale after an upgrade (seen: profile at max_20x, token still at max_5x).
# Monthly list prices in USD. A tier missing here gets a name and no price
# rather than a guessed one, and the seat plans have no single price to offer.
PLANS = {"pro": "Pro", "max": "Max", "team": "Team", "enterprise": "Enterprise"}
TIERS = {"max_5x": ("Max 5x", 100.0), "max_20x": ("Max 20x", 200.0), "pro": ("Pro", 20.0)}
PRICES = {"pro": 20.0}


def _oauth(acct: Account) -> dict | None:
    try:
        raw = json.loads(acct.credentials_file.read_text())
    except (OSError, ValueError):
        return None                      # keyring, or never signed in
    oauth = raw.get("claudeAiOauth") if isinstance(raw, dict) else None
    return oauth if isinstance(oauth, dict) else None


def _named(kind: str, tier) -> tuple[str, float | None]:
    if isinstance(tier, str):
        for key, found in TIERS.items():
            if tier.endswith(key):
                return found
    return PLANS.get(kind, kind.capitalize()), PRICES.get(kind)


def account_plan(account: Account | None = None) -> dict | None:
    """Who is logged in and on which plan, or None when there is no login to read.

    Everything returned is what the Plan tab shows; ids and tokens stay out.
    """
    acct = account if account is not None else primary()
    who = identity(acct.claude_dir)
    kind = (who.get("organizationType") or "").removeprefix("claude_")
    tier = who.get("organizationRateLimitTier") or who.get("userRateLimitTier")
    source = "profile"
    if not kind:
        oauth = _oauth(acct) or {}
        kind = oauth.get("subscriptionType") if isinstance(oauth.get("subscriptionType"), str) else ""
        tier = oauth.get("rateLimitTier")
        source = "credentials"
    if not kind:
        return None
    name, price = _named(kind, tier)
    org = (who.get("organizationName") or "").strip()
    since = who.get("subscriptionCreatedAt")
    return {
        "name": name,
        "monthly_usd": price,
        "source": source,
        "full_name": who.get("fullName") or who.get("displayName"),
        "email": who.get("emailAddress"),
        # Anthropic names a personal organisation after the email: noise here
        "organization": org if org and "'s Organization" not in org else None,
        "role": who.get("organizationRole"),
        "billing": who.get("billingType"),
        "subscribed_since": since[:10] if isinstance(since, str) else None,
        "extra_usage": who.get("hasExtraUsageEnabled"),
    }


def status(account: Account | None = None, now: float | None = None) -> dict | None:
    """Login expiry for one account, or None when there is nothing to read."""
    oauth = _oauth(account if account is not None else primary())
    if oauth is None:
        return None
    expires = oauth.get("refreshTokenExpiresAt")
    if not isinstance(expires, (int, float)) or expires <= 0:
        return None

    now = now or time.time()
    expires_at = expires / 1000.0        # Claude Code writes milliseconds
    remaining = expires_at - now
    plan = oauth.get("subscriptionType")
    return {
        "expires_at": expires_at,
        "remaining_s": remaining,
        "expired": remaining <= 0,
        "state": state_for(remaining),
        "plan": plan if isinstance(plan, str) else "",
    }


def state_for(remaining_s: float) -> str:
    if remaining_s <= 0:
        return "crit"
    days = remaining_s / 86400
    if days <= CRITICAL_DAYS:
        return "crit"
    if days <= WARN_DAYS:
        return "warn"
    return "ok"
