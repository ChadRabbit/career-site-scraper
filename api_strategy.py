from typing import Callable
import logging

log = logging.getLogger("job_scraper")
from playwright.async_api import Response, Page
from companies import CompanyConfig
from utils import _normalize_job, _perform_search, _paginate_click, _paginate_scroll


def make_api_handler(cfg: CompanyConfig, results: list[dict]) -> Callable:
    """Returns a response handler that extracts jobs from matching XHR responses."""
    api = cfg.api

    async def handler(response: Response):
        if api.url_pattern not in response.url:
            return
        if api.content_type_filter and api.content_type_filter not in response.headers.get("content-type", ""):
            return
        try:
            data = await response.json()
        except Exception as e:
            log.error("Got an error while parsing response: {e}" )
            return

        raw_jobs = _dig(data, api.data_path) if api.data_path else data

        if not raw_jobs or not isinstance(raw_jobs, list):
            return

        log.info(f"✅ [{cfg.name}] Got {len(raw_jobs)} jobs from {response.url}")
        for raw in raw_jobs:
            job = _normalize_job(raw, api.field_mapping, cfg.name)
            results.append(job)
            log.info(job)

    return handler


async def run_api_strategy(page: Page, cfg: CompanyConfig) -> list[dict]:
    results: list[dict] = []
    handler = make_api_handler(cfg, results)

    page.on("response", handler)

    await page.goto(cfg.url)
    await page.wait_for_timeout(cfg.initial_wait_ms)
    if cfg.search:
        await _perform_search(page, cfg.search)
    p = cfg.pagination
    if p.type == "click":
        await _paginate_click(page, p)
        await page.wait_for_load_state("networkidle")
    elif p.type == "scroll":
        await _paginate_scroll(page, p)
    # page_number pagination is unusual for API strategy but supported via click fallback

    return results


def _dig(data, path: list[str]):
    """Walk nested dicts/lists using a key path."""
    for key in path:
        if isinstance(data, dict):
            data = data.get(key)
        else:
            return None
        if data is None:
            return None
    return data
