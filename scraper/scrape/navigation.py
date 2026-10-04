from __future__ import annotations

import asyncio
import time

from scraper.config import PaginationConfig
from scraper.human import Human
from scraper.locate import resolve
from scraper.log import get_logger

log = get_logger()

_DISABLED_JS = """
el => el.disabled === true
   || el.getAttribute('aria-disabled') === 'true'
   || /(^|[\\s_-])disabled($|[\\s_-])/i.test(el.className || '')
   || getComputedStyle(el).pointerEvents === 'none'
"""


async def settle(page, idle_ms: int = 6_000) -> None:
    """Wait for the page to calm down after navigation or a click, without hanging on chatty sites."""
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15_000)
    except Exception:
        pass
    try:
        await page.wait_for_load_state("networkidle", timeout=idle_ms)
    except Exception:
        pass


class QuietNetwork:
    """
    Wrap a click: waits until the page's XHR/fetch/document requests have been quiet for
    quiet_ms. (Playwright's "networkidle" only tracks navigations, so it returns instantly
    after a "Load more" click that fires an XHR.)

        async with QuietNetwork(page):
            await human.click(button)
    """

    TRACKED = {"xhr", "fetch", "document", "script"}

    def __init__(self, page, quiet_ms: int = 800, timeout_ms: int = 12_000):
        self.page = page
        self.quiet_s = quiet_ms / 1000
        self.timeout_s = timeout_ms / 1000
        self.inflight: set = set()
        self.last_activity = time.monotonic()

    def _on_request(self, request):
        if request.resource_type in self.TRACKED:
            self.inflight.add(request)
            self.last_activity = time.monotonic()

    def _on_done(self, request):
        self.inflight.discard(request)
        self.last_activity = time.monotonic()

    async def __aenter__(self):
        self.page.on("request", self._on_request)
        self.page.on("requestfinished", self._on_done)
        self.page.on("requestfailed", self._on_done)
        return self

    async def __aexit__(self, *exc):
        try:
            await asyncio.sleep(0.3)  # give the click's requests a moment to start
            deadline = time.monotonic() + self.timeout_s
            while time.monotonic() < deadline:
                if not self.inflight and time.monotonic() - self.last_activity >= self.quiet_s:
                    break
                await asyncio.sleep(0.1)
            try:
                await self.page.wait_for_load_state("domcontentloaded", timeout=5_000)
            except Exception:
                pass
        finally:
            self.page.remove_listener("request", self._on_request)
            self.page.remove_listener("requestfinished", self._on_done)
            self.page.remove_listener("requestfailed", self._on_done)


async def next_control(scope, pagination: PaginationConfig, current_page: int):
    """The clickable control that leads to page current_page + 1, or None when we are at the end."""
    if pagination.type in ("next", "load_more"):
        loc = await resolve(scope, pagination.control)
    elif pagination.type == "page_number" and pagination.page_number_template:
        selector = pagination.page_number_template.replace("{page}", str(current_page + 1))
        loc = await resolve(scope, [selector])
    else:
        return None
    if loc is None:
        return None
    control = loc.first
    try:
        if not await control.is_visible():
            return None
        if await control.evaluate(_DISABLED_JS):
            return None
    except Exception:
        return None
    return control


async def explain_missing_control(scope, pagination: PaginationConfig, current_page: int) -> str:
    """Why next_control() found nothing, for the log."""
    if pagination.type == "page_number" and pagination.page_number_template:
        selectors = [pagination.page_number_template.replace("{page}", str(current_page + 1))]
    else:
        selectors = pagination.control.candidates if pagination.control else []
    parts = []
    for selector in selectors[:4]:
        try:
            loc = scope.locator(selector)
            n = await loc.count()
            detail = f"{n} match" + ("" if n == 1 else "es")
            if n:
                detail += ", visible" if await loc.first.is_visible() else ", hidden"
                if await loc.first.evaluate(_DISABLED_JS):
                    detail += ", disabled"
        except Exception as e:
            detail = f"error {str(e)[:60]}"
        parts.append(f"{selector[:80]} → {detail}")
    return "; ".join(parts) or "no selectors recorded"


async def go_to_next_page(page, scope, pagination: PaginationConfig, current_page: int, human: Human) -> bool:
    control = await next_control(scope, pagination, current_page)
    if control is not None:
        async with QuietNetwork(page):
            await human.click(control)
        return True
    # fallback: the URL pattern seen during onboarding (e.g. "...&page={page}")
    template = pagination.url_template
    if pagination.type in ("next", "page_number") and template and "{page}" in template:
        log.info(f"  next-page control not found ({await explain_missing_control(scope, pagination, current_page)}); "
                 f"using the recorded URL pattern instead")
        await page.goto(template.replace("{page}", str(current_page + 1)), wait_until="domcontentloaded")
        await settle(page)
        return True
    return False
