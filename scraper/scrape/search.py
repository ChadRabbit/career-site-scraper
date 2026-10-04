from __future__ import annotations

from urllib.parse import quote_plus

from scraper.config import SearchConfig
from scraper.human import Human
from scraper.locate import resolve
from scraper.log import get_logger
from scraper.scrape.navigation import QuietNetwork, settle

log = get_logger()


MAX_QUERY_CHARS = 120


def is_plausible_query(value: str | None) -> bool:
    """A search query is a short single line, never a page's worth of text."""
    return bool(value and value.strip()) and len(value) <= MAX_QUERY_CHARS and "\n" not in value


async def apply_search(page, scope, search: SearchConfig, human: Human) -> bool:
    """Replay the recorded search. Prefers the results URL when the query lives in the URL."""
    if not is_plausible_query(search.query):
        log.warning(f"  saved search query looks wrong ({len(search.query)} chars); skipping search. "
                    "Re-onboard this company with --force.")
        return False
    if search.results_url:
        await page.goto(search.results_url.replace("{query}", quote_plus(search.query)))
        await settle(page)
        return True

    box = await resolve(scope, search.input)
    if box is None:
        log.warning("  search box not found; continuing without search")
        return False
    async with QuietNetwork(page):  # live-filtering boxes fire requests while typing
        await human.type(box.first, search.query)
    await human.pause(0.3, 0.8)
    async with QuietNetwork(page):
        if search.submit == "enter":
            await box.first.press("Enter")
        elif search.submit == "click":
            button = await resolve(scope, search.submit_button)
            if button is not None:
                await human.click(button.first)
            else:
                await box.first.press("Enter")
    await settle(page)
    return True
