"""When the login expires.

Claude Code keeps its OAuth state in <account>/.credentials.json. Exactly two
fields are read from that file and nothing else: `refreshTokenExpiresAt` and
`subscriptionType`. The tokens sitting beside them are never read, never stored,
never printed, and never enter this module's return value.

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

from .accounts import Account, primary

# what counts as "soon", in days. The login is not a rate limit, so it does not
# share the configurable percentage thresholds
WARN_DAYS = 7
CRITICAL_DAYS = 2


def status(account: Account | None = None, now: float | None = None) -> dict | None:
    """Login expiry for one account, or None when there is nothing to read."""
    acct = account if account is not None else primary()
    try:
        raw = json.loads(acct.credentials_file.read_text())
    except (OSError, ValueError):
        return None                      # keyring, or never signed in
    oauth = raw.get("claudeAiOauth")
    if not isinstance(oauth, dict):
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
