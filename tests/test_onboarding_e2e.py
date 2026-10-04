"""
End-to-end: run the real onboarding wizard in headless Chromium against local fixture
sites, with the test playing the human (clicking elements and overlay buttons).
"""

import asyncio
import json

import pytest

from scraper.config import load_config
from scraper.onboard.wizard import onboard
from scraper.scrape.runner import scrape_company


async def wizard_page(context):
    for _ in range(200):
        for page in context.pages:
            if page.url.startswith("http"):
                return page
        await asyncio.sleep(0.05)
    raise AssertionError("wizard never opened the site")


async def wait_step(page, step, task, timeout=20_000):
    waiter = asyncio.ensure_future(page.wait_for_function(
        "s => window.__onboard && window.__onboard.state.step === s", arg=step, timeout=timeout))
    done, _ = await asyncio.wait({waiter, task}, return_when=asyncio.FIRST_COMPLETED)
    if task in done and waiter not in done:
        waiter.cancel()
        task.result()  # surface the wizard's exception
        raise AssertionError(f"wizard finished before reaching step {step!r}")
    waiter.result()


async def press(page, button_id):
    await page.locator(f'[data-onboard-btn="{button_id}"]').click()


def start(context, tmp_path, name, url, **kwargs):
    return asyncio.create_task(onboard(name, url, context=context, speed=0, config_dir=tmp_path / "configs",
                                       capture_dir=tmp_path / "captures", **kwargs))


async def test_dom_site_with_search_and_next(browser_context, site, tmp_path):
    task = start(browser_context, tmp_path, "Acme", f"{site}/dom/index.html")
    page = await wizard_page(browser_context)

    await wait_step(page, "search", task)
    await page.click("input[name=q]")
    await page.fill("input[name=q]", "Engineer")
    await page.press("input[name=q]", "Enter")
    await page.wait_for_url("**q=Engineer**")
    await wait_step(page, "search", task)  # overlay restored after the navigation
    await press(page, "done")

    await wait_step(page, "card", task)
    await page.locator("a.job-title").nth(2).click()  # intercepted, not followed
    await wait_step(page, "card_confirm", task)
    preview = await page.evaluate("() => window.__onboard.state.preview")
    assert len(preview) == 8 and all(r["title"] and r["apply_url"] for r in preview)
    assert preview[0]["location"] == "Bengaluru, India"
    assert preview[0]["department"] == "Engineering"
    await press(page, "confirm")

    await wait_step(page, "next", task)  # wizard opened the job and came back on its own
    await page.click("a.pager-next")
    await wait_step(page, "done", task, timeout=60_000)
    await press(page, "finish")
    cfg = await task

    assert cfg.search.query == "Engineer"
    assert cfg.search.results_url.endswith("/dom/index.html?q={query}")
    assert cfg.pagination.type == "next"
    assert {"title", "apply_url", "location", "department"} <= set(cfg.dom.fields)
    assert cfg.onboarded_job_count == 19  # 19 "Engineer" matches across 2 pages
    saved = load_config(tmp_path / "configs" / "acme.json")
    assert saved.onboarded_job_count == 19

    capture = next((tmp_path / "captures" / "acme").glob("onboard_*"))
    index = [json.loads(line) for line in (capture / "index.jsonl").read_text().splitlines()]
    assert any(e["url"].endswith("/dom/index.html") and e.get("body_file") for e in index)
    assert list((capture / "screenshots").glob("*.png"))


async def test_js_click_cards_learn_url_template(browser_context, site, tmp_path):
    task = start(browser_context, tmp_path, "Initech", f"{site}/jsclick/index.html")
    page = await wizard_page(browser_context)

    await wait_step(page, "search", task)
    await press(page, "skip")
    await wait_step(page, "card", task)
    await page.locator(".posting-title").nth(1).click()
    await wait_step(page, "card_confirm", task)
    await press(page, "confirm")
    await wait_step(page, "next", task)
    await press(page, "none")
    await wait_step(page, "done", task, timeout=60_000)
    await press(page, "finish")
    cfg = await task

    assert cfg.dom.apply_url_template.endswith("/jsclick/job.html?jobId={job_id}")
    assert cfg.dom.fields["job_id"].attr == "data-job-id"
    assert "location" in cfg.dom.fields
    assert cfg.pagination.type == "none"

    result = await scrape_company(browser_context, cfg, speed=0)
    assert result.status == "ok" and len(result.jobs) == 5
    assert all(j["apply_url"].endswith(f"jobId={j['job_id']}") for j in result.jobs)


async def test_bot_check_that_clears_by_itself(browser_context, site, tmp_path):
    """Onboarding and the replay both wait out an interstitial instead of giving up."""
    task = start(browser_context, tmp_path, "Shielded", f"{site}/challenge/index.html")
    page = await wizard_page(browser_context)

    await wait_step(page, "search", task)  # got past the bot check without any help
    await press(page, "skip")
    await wait_step(page, "card", task)
    await page.locator("a.job-title").first.click()
    await wait_step(page, "card_confirm", task)
    await press(page, "confirm")
    await wait_step(page, "next", task)
    await press(page, "none")
    await wait_step(page, "done", task, timeout=60_000)
    await press(page, "finish")
    cfg = await task

    assert cfg.start_url.endswith("/challenge/index.html")
    assert cfg.onboarded_job_count == 10  # the verify run also waited out the check


async def test_popup_recorded_and_replayed(browser_context, site, tmp_path):
    """A cookie dialog that blocks the page on every load: recorded once via 'Record popup', closed on every page."""
    task = start(browser_context, tmp_path, "Cookies", f"{site}/dom/index.html?cookies=1")
    page = await wizard_page(browser_context)

    await wait_step(page, "search", task)
    await press(page, "__popup")
    await page.wait_for_function("() => window.__onboard.state.popupRecording === true")
    await page.click("#essential")  # goes through (closes the dialog) and is recorded
    await page.wait_for_function("() => window.__onboard.state.popupCount === 1")
    assert await page.locator("#backdrop").count() == 0
    await press(page, "skip")
    await wait_step(page, "card", task)
    await page.locator("a.job-title").first.click()
    await wait_step(page, "card_confirm", task)
    await press(page, "confirm")
    await wait_step(page, "next", task)  # the dialog came back after opening the job; the wizard closed it
    assert await page.locator("#backdrop").count() == 0
    await page.click("a.pager-next")
    await wait_step(page, "done", task, timeout=60_000)
    await press(page, "finish")
    cfg = await task

    assert len(cfg.popups) == 1 and "#essential" in cfg.popups[0].candidates
    assert cfg.onboarded_job_count == 20  # the verify run closed the dialog on both pages

    # Fallback: a next-page selector that no longer matches → the recorded URL pattern is used
    cfg.pagination.control.candidates = ["a.renamed-next-button"]
    assert cfg.pagination.url_template and "{page}" in cfg.pagination.url_template
    result = await scrape_company(browser_context, cfg, max_pages=3, speed=0)
    assert len(result.jobs) == 25  # all 3 pages via the recorded URL pattern


async def test_overlay_renders_under_trusted_types(browser_context, site, tmp_path):
    """Sites like Google enforce Trusted Types; the panel must not rely on innerHTML."""
    task = start(browser_context, tmp_path, "Trusted", f"{site}/trusted/index.html")
    page = await wizard_page(browser_context)
    await wait_step(page, "search", task)
    assert await page.locator('[data-onboard-btn="skip"]').is_visible()
    assert await page.locator("#__onboard-host").evaluate("h => h.shadowRoot.querySelector('.msg').textContent")
    await press(page, "skip")
    await wait_step(page, "card", task)
    await page.locator("a.title").first.click()
    await wait_step(page, "card_confirm", task)
    preview = await page.evaluate("() => window.__onboard.state.preview")
    assert [r["title"] for r in preview] == ["Software Engineer", "Backend Engineer", "Data Engineer"]
    task.cancel()


async def test_search_query_only_comes_from_the_search_box(browser_context, site, tmp_path):
    """Enter pressed on the page body / clicks on plain text must not become the query or the submit button."""
    task = start(browser_context, tmp_path, "Typist", f"{site}/dom/index.html")
    page = await wizard_page(browser_context)

    await wait_step(page, "search", task)
    await page.click("input[name=q]")
    await page.fill("input[name=q]", "Engineer")
    await asyncio.sleep(0.5)              # a person pauses after typing (typing is reported after 250 ms)
    await page.click("aside h4")          # plain text, not a button; focus leaves the input
    await page.keyboard.press("Enter")    # lands on <body>
    await asyncio.sleep(0.5)
    await press(page, "done")
    await wait_step(page, "card", task)
    await page.locator("a.job-title").first.click()
    await wait_step(page, "card_confirm", task)
    await press(page, "confirm")
    await wait_step(page, "next", task)
    await press(page, "none")
    await wait_step(page, "done", task, timeout=60_000)
    await press(page, "finish")
    cfg = await task

    assert cfg.search.query == "Engineer"
    assert cfg.search.submit_button is None


async def test_closing_the_window_aborts_cleanly(browser_context, site, tmp_path):
    from scraper.onboard.wizard import OnboardingError

    task = start(browser_context, tmp_path, "Quitter", f"{site}/dom/index.html")
    page = await wizard_page(browser_context)
    await wait_step(page, "search", task)
    await page.close()
    with pytest.raises(OnboardingError):
        await asyncio.wait_for(task, 10)
    assert not (tmp_path / "configs" / "quitter.json").exists()
