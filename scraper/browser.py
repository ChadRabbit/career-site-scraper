from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from scraper import settings
from scraper.log import get_logger

log = get_logger()


def _async_playwright(engine: str):
    if engine == "patchright":
        try:
            from patchright.async_api import async_playwright

            return async_playwright
        except ImportError:
            log.warning("patchright is not installed (pip install patchright); falling back to playwright")
    from playwright.async_api import async_playwright

    return async_playwright


@asynccontextmanager
async def open_browser(
    *,
    user_data_dir: Path = settings.USER_DATA_DIR,
    headless: bool = settings.HEADLESS,
    har_path: Path | None = None,
    engine: str = settings.BROWSER_ENGINE,
    channel: str | None = settings.BROWSER_CHANNEL,
) -> AsyncIterator:
    """
    Persistent Chromium profile, so cookies/consent survive between runs.
    With har_path set, Playwright records every request/response of the session
    (bodies included) to a .har.zip next to our own indexed capture.
    """
    kwargs: dict = {"headless": headless}
    if headless:
        kwargs["viewport"] = settings.HEADLESS_VIEWPORT
    else:
        kwargs["no_viewport"] = True  # use the real window size, like a person would
    if channel:
        kwargs["channel"] = channel
    if har_path:
        har_path.parent.mkdir(parents=True, exist_ok=True)
        kwargs.update(record_har_path=str(har_path), record_har_content="attach", record_har_mode="full")

    async with _async_playwright(engine)() as p:
        context = await p.chromium.launch_persistent_context(str(user_data_dir), **kwargs)
        context.set_default_navigation_timeout(settings.NAVIGATION_TIMEOUT_MS)
        try:
            yield context
        finally:
            await context.close()  # also flushes the HAR file
