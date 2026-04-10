from typing import Callable

from playwright.async_api import Page

from api_strategy import run_api_strategy
from companies import CompanyConfig
from dom_strategy import run_dom_strategy
import logging

log = logging.getLogger("job_scraper")


async def scrape_company(page: Page, cfg: CompanyConfig) -> list[dict]:
    log.info(f"\n{'=' * 50}\n Scraping: {cfg.name}\n{'=' * 50}")
    if cfg.strategy == "api":
        return await run_api_strategy(page, cfg)
    elif cfg.strategy == "dom":
        return await run_dom_strategy(page, cfg)
    else:
        raise ValueError(f"Unknown strategy: {cfg.strategy}")


async def scrape_company_in_tab(context, cfg):
    page = await context.new_page()

    try:
        jobs = await scrape_company(page, cfg)
        log.info(f"{cfg.name}: {len(jobs)} jobs scraped")
        return cfg.name, jobs

    except Exception as e:
        log.error(f"{cfg.name} failed: {e}")
        return cfg.name, []

    finally:
        await page.close()
