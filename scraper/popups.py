"""
Recorded popups (cookie banners, newsletter modals, chat prompts): the user records each
popup's close button once during onboarding; PopupWatcher clicks it whenever it shows up.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable

from scraper import settings
from scraper.config import SelectorSpec
from scraper.log import get_logger

log = get_logger()

# The onboarding picker ignores clicks on elements carrying this marker, so the
# watcher's own clicks are never mistaken for a pick.
AUTO_MARK = "data-onboard-auto"

Specs = Iterable[SelectorSpec] | Callable[[], Iterable[SelectorSpec]]


class PopupWatcher:
    """
    Every `interval` seconds, click the close button of any recorded popup that is visible.

        async with PopupWatcher(page, cfg.popups):
            ...scrape...
    """

    def __init__(self, page, specs: Specs, interval: float | None = None):
        self.page = page
        self._specs = specs
        self.interval = settings.POPUP_CHECK_INTERVAL_S if interval is None else interval
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self.closed = 0

    def specs(self) -> list[SelectorSpec]:
        return list(self._specs() if callable(self._specs) else self._specs)

    async def check_now(self) -> int:
        """Close every visible recorded popup; returns how many were closed."""
        if self.page.is_closed():
            return 0
        closed = 0
        async with self._lock:
            for spec in self.specs():
                for selector in spec.candidates:
                    try:
                        loc = self.page.locator(selector).first
                        if not await loc.count() or not await loc.is_visible():
                            continue
                        await loc.evaluate(f"el => el.setAttribute('{AUTO_MARK}', '1')")
                        await loc.click(timeout=3_000)
                        closed += 1
                        log.info(f"  closed popup ({(spec.fingerprint or {}).get('text') or selector[:40]!r})")
                        break
                    except Exception:  # detached, covered, invalid selector: try the next candidate
                        continue
        self.closed += closed
        return closed

    async def _run(self) -> None:
        while not self.page.is_closed():
            await self.check_now()
            await asyncio.sleep(self.interval)

    def start(self) -> PopupWatcher:
        if self._task is None:
            self._task = asyncio.ensure_future(self._run())
        return self

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def __aenter__(self) -> PopupWatcher:
        return self.start()

    async def __aexit__(self, *exc) -> None:
        await self.stop()
