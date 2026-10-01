"""The dollar rate, from Banco Central do Brasil, on request.

This is the one network call cc-cockpit makes, and it only happens when the
user presses the button beside the rate in Settings - never at start-up, never
on a timer. Everything else stays on the machine.

The default source is series 1 of the SGS - the PTAX selling rate, published
once per business day around 13:00 Brasília time. The URL can be changed in
Settings, for the day Banco Central moves it; the reply still has to keep the
SGS shape, or it is refused rather than turned into a number.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from . import __version__

DEFAULT_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.1/dados/ultimos/1?formato=json"
TIMEOUT = 10          # seconds
MAX_BYTES = 64_000    # a reply with one or a few rows is well under a kilobyte


class RateError(Exception):
    """Why no rate came back, in words fit to show beside the field."""


def url_for(cfg: dict) -> str:
    return (cfg.get("rate_url") or "").strip() or DEFAULT_URL


def stored_url(text: str) -> str | None:
    """What goes in the config: nothing while the release default is in use,
    so a URL fixed in a later release reaches whoever never changed it."""
    text = (text or "").strip()
    return None if not text or text == DEFAULT_URL else text


def parse(rows) -> tuple[float, str]:
    """(rate, date) from an SGS reply: [{"data": "25/09/2026", "valor": "5.1991"}, ...]."""
    if not isinstance(rows, list) or not rows or not isinstance(rows[-1], dict):
        raise RateError("unexpected reply")
    last = rows[-1]
    try:
        value = float(str(last["valor"]).replace(",", "."))
        date = str(last["data"])
    except (KeyError, ValueError):
        raise RateError("unexpected reply") from None
    if not value > 0:
        raise RateError("unexpected reply")
    return value, date


def fetch(url: str = DEFAULT_URL) -> tuple[float, str]:
    """Asks the source once. Raises RateError on anything but a usable rate."""
    if not url.lower().startswith("https://"):
        raise RateError("the address must start with https://")
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": f"cc-cockpit/{__version__}"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read(MAX_BYTES + 1)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise RateError(str(getattr(exc, "reason", exc))) from None
    if len(body) > MAX_BYTES:
        raise RateError("reply too large")
    try:
        return parse(json.loads(body))
    except ValueError:
        raise RateError("unexpected reply") from None
