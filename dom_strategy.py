from playwright.async_api import Page
from companies import CompanyConfig, DomConfig
from utils import _paginate_click, _paginate_scroll, _paginate_page_number, _perform_search
import logging

log = logging.getLogger("job_scraper")


async def _scrape_dom_page(page: Page, cfg: CompanyConfig) -> list[dict]:
    """Scrape job cards from the current DOM state."""
    dom = cfg.dom
    results = []

    # ── Special case: Rubrik groups cards under location sections ────────
    if cfg.name == "Rubrik":
        sections = page.locator("div.careers_section_listing_container")
        sec_count = await sections.count()
        for i in range(sec_count):
            section = sections.nth(i)
            try:
                location = (await section.locator("h4.careers_section_listing_location_title").inner_text()).replace(
                    "Office", "").strip()
            except Exception:
                location = ""
            cards = section.locator(dom.job_card_selector)
            card_count = await cards.count()
            for j in range(card_count):
                job = await _extract_card(cards.nth(j), dom, cfg.name)
                if dom.base_url:
                    if job['apply_url'].startswith("/"):
                        job["apply_url"] = f"{dom.base_url}{job['apply_url']}"
                    else:
                        job["apply_url"] = f"{dom.base_url}/{job['{{{apply_url']}"
                job["location"] = location
                results.append(job)
                log.info(job)
        return results

    # ── Generic DOM scraping ─────────────────────────────────────────────
    cards = page.locator(dom.job_card_selector)
    count = await cards.count()
    log.info(f"✅ [{cfg.name}] Found {count} job cards")
    for i in range(count):
        try:
            job = await _extract_card(cards.nth(i), dom, cfg.name)
            if dom.base_url:
                if job['apply_url'].startswith("/"):
                    job["apply_url"] = f"{dom.base_url}{job['apply_url']}"
                else:
                    job["apply_url"] = f"{dom.base_url}/{job['apply_url']}"
            results.append(job)
            log.info(job)
        except Exception as e:
            log.error(f"  Skipped card {i}: {e}")
    return results


async def _extract_card(card, dom: DomConfig, company: str) -> dict:
    """Extract fields from a single card locator using DomConfig.fields."""
    job = {"company": company}
    for field_name, selector in dom.fields.items():
        try:
            if selector.startswith("attr:"):
                # format: "attr:ATTRNAME:CSS_SELECTOR"
                _, attr_name, css = selector.split(":", 2)
                el = card.locator(css).first
                value = await el.get_attribute(attr_name)
            else:
                el = card.locator(selector).first
                value = (await el.inner_text()).strip()
                # strip label prefixes like "Location", "Category"
                for prefix in ("Location", "Category"):
                    if value.startswith(prefix):
                        value = value[len(prefix):].strip()
            job[field_name] = value
        except Exception:
            log.error(f"  Warning: Failed to extract {field_name} using selector '{selector}'")
    return job


async def run_dom_strategy(page: Page, cfg: CompanyConfig) -> list[dict]:
    results: list[dict] = []

    await page.goto(cfg.url)
    await page.wait_for_timeout(cfg.initial_wait_ms)
    if cfg.search:
        await _perform_search(page, cfg.search)

    p = cfg.pagination
    if p.type == "page_number":
        async def on_page():
            page_jobs = await _scrape_dom_page(page, cfg)
            results.extend(page_jobs)

        await _paginate_page_number(page, p, on_page)

    elif p.type == "scroll":
        await _paginate_scroll(page, p)
        results.extend(await _scrape_dom_page(page, cfg))

    elif p.type == "click":
        await _paginate_click(page, p)
        results.extend(await _scrape_dom_page(page, cfg))

    else:
        results.extend(await _scrape_dom_page(page, cfg))

    return results
