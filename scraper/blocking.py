"""Spot bot-protection challenge pages so we back off instead of hammering."""

from __future__ import annotations

import asyncio
import time

BLOCK_STATUSES = {403, 429, 503}

CHALLENGE_MARKERS = (
    "challenges.cloudflare.com",
    "cf-chl",
    "just a moment...",
    "attention required! | cloudflare",
    "px-captcha",
    "captcha-delivery.com",  # DataDome
    "_incapsula_resource",
    "request unsuccessful. incapsula",
    "access denied</title>",
    "are you a robot",
    "unusual traffic from your computer",
)


async def detect_block(page, status: int | None = None) -> str | None:
    """Return a short reason if the page looks like a block/challenge page, else None."""
    try:
        html = (await page.content())[:20000].lower()
    except Exception:
        html = ""
    for marker in CHALLENGE_MARKERS:
        if marker in html:
            return f"challenge page ({marker})"
    if status in BLOCK_STATUSES:
        return f"HTTP {status}"
    return None


async def wait_until_clear(page, timeout_s: float, initial_reason: str | None = None) -> str | None:
    """
    Interstitials like Cloudflare's "Just a moment..." usually clear by themselves in a real
    browser after a few seconds. Just wait (never interact); return the reason if still blocked.
    The HTTP status of the first response is ignored once the page content looks normal.
    """
    reason = initial_reason
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        await asyncio.sleep(1)
        try:
            reason = await detect_block(page)
        except Exception:  # mid-navigation
            continue
        if reason is None:
            return None
    return reason
