"""
Replays onboarded configs: one company at a time, human-paced, with block detection.

Per company:  open start page → wait out bot check → start popup watcher → search →
              for each page: scroll & harvest cards → next page (control, else recorded URL pattern)
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from pathlib import Path

from scraper import settings
from scraper.blocking import detect_block, wait_until_clear
from scraper.browser import open_browser
from scraper.capture import NetworkRecorder, screenshot
from scraper.config import CompanyConfig
from scraper.health import update_health
from scraper.human import Human
from scraper.locate import find_frame
from scraper.log import get_logger
from scraper.popups import PopupWatcher
from scraper.scrape.dom import count_cards, extract_cards
from scraper.scrape.navigation import explain_missing_control, go_to_next_page, settle
from scraper.scrape.search import apply_search

log = get_logger()

CHALLENGE_WAIT_S = 25  # how long to let an automatic bot check clear before skipping the company


@dataclass
class CompanyResult:
    name: str
    slug: str
    status: str  # ok | empty | blocked | error
    jobs: list[dict] = field(default_factory=list)
    pages: int = 0
    error: str | None = None


def job_key(row: dict) -> str | None:
    if row.get("apply_url"):
        return row["apply_url"]
    if row.get("job_id"):
        return f"id:{row['job_id']}"
    if row.get("title"):
        return f"{row['title']}|{row.get('location', '')}"
    return None


async def _wait_for_cards(scope, cfg: CompanyConfig, timeout_s: float = 15) -> int:
    deadline = time.monotonic() + timeout_s
    while True:
        n = await count_cards(scope, cfg.dom)
        if n or time.monotonic() > deadline:
            return n
        await asyncio.sleep(0.5)


async def _open_start_page(page, cfg: CompanyConfig) -> str | None:
    """Load the start URL; returns a reason if a bot check is still showing after waiting."""
    response = await page.goto(cfg.start_url, wait_until="domcontentloaded")
    await settle(page)
    reason = await detect_block(page, response.status if response else None)
    if not reason:
        return None
    log.info(f"  {cfg.name}: bot check showing ({reason}); waiting for it to clear by itself…")
    reason = await wait_until_clear(page, CHALLENGE_WAIT_S, reason)
    if not reason:
        await settle(page)
    return reason


async def scrape_company(
    context,
    cfg: CompanyConfig,
    *,
    max_pages: int | None = None,
    speed: float | None = None,
    run_dir: Path | None = None,
) -> CompanyResult:
    max_pages = max_pages or cfg.pagination.max_pages
    log.info(f"{'=' * 50}\n  Scraping {cfg.name}\n{'=' * 50}")

    page = await context.new_page()
    human = Human(page, speed)
    recorder = NetworkRecorder(run_dir, mode="data").attach(page) if run_dir else None
    watcher = None
    jobs: dict[str, dict] = {}
    pages = 0

    async def harvest(scope) -> None:
        for row in await extract_cards(scope, cfg.dom):
            key = job_key(row)
            if key and key not in jobs:
                jobs[key] = row

    def result(status: str, error: str | None = None) -> CompanyResult:
        rows = [dict(row, company=cfg.name) for row in jobs.values()]
        return CompanyResult(cfg.name, cfg.slug, status, rows, pages, error)

    try:
        reason = await _open_start_page(page, cfg)
        if reason:
            log.warning(f"  {cfg.name}: still blocked ({reason}); skipping")
            return result("blocked", reason)

        if cfg.popups:
            watcher = PopupWatcher(page, cfg.popups).start()  # closes recorded popups every few seconds
        scope = find_frame(page, cfg.frame_url_contains)
        if cfg.search:
            await apply_search(page, scope, cfg.search, human)
            if watcher:
                await watcher.check_now()
            scope = find_frame(page, cfg.frame_url_contains)

        infinite = cfg.pagination.type == "scroll"
        for page_no in range(1, max_pages + 1):
            pages = page_no
            before = len(jobs)
            await _wait_for_cards(scope, cfg)
            # harvest on every scroll step, so virtualised lists are read while on screen
            await human.scroll_page(on_step=lambda s=scope: harvest(s), max_steps=80 if infinite else 40)
            if run_dir:
                await screenshot(page, run_dir, f"page{page_no}")
            new = len(jobs) - before
            log.info(f"  page {page_no}: +{new} jobs (total {len(jobs)})")

            if page_no > 1 and new == 0:
                break
            if page_no >= max_pages or cfg.pagination.type in ("none", "scroll"):
                break
            await human.pause(*settings.DELAY_BETWEEN_PAGES_S)
            if watcher:
                await watcher.check_now()  # don't let a fresh popup swallow the next-page click
            if not await go_to_next_page(page, scope, cfg.pagination, page_no, human):
                log.info(f"  no further pages ({await explain_missing_control(scope, cfg.pagination, page_no)})")
                if run_dir:
                    await screenshot(page, run_dir, f"no_next_after_page{page_no}")
                break
            scope = find_frame(page, cfg.frame_url_contains)

        return result("ok" if jobs else "empty")

    except Exception as e:
        log.exception(f"  {cfg.name} failed: {e}")
        return result("error", str(e))
    finally:
        if watcher:
            await watcher.stop()
        if recorder:
            await recorder.close()
        await page.close()


async def scrape_all(
    configs: list[CompanyConfig],
    *,
    max_pages: int | None = None,
    headless: bool = settings.HEADLESS,
    speed: float | None = None,
    har: bool = False,
) -> list[CompanyResult]:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    har_path = settings.CAPTURE_DIR / "_runs" / f"{stamp}.har.zip" if har else None
    speed = settings.HUMAN_SPEED if speed is None else speed
    results = []
    async with open_browser(headless=headless, har_path=har_path) as context:
        for i, cfg in enumerate(configs):
            if i and speed > 0:
                wait = random.uniform(*settings.DELAY_BETWEEN_COMPANIES_S) * speed
                log.info(f"  pausing {wait:.0f}s before the next company")
                await asyncio.sleep(wait)
            run_dir = settings.CAPTURE_DIR / cfg.slug / f"scrape_{stamp}"
            result = await scrape_company(context, cfg, max_pages=max_pages, speed=speed, run_dir=run_dir)
            update_health(cfg, result)
            results.append(result)
    return results
