"""
Field inference on realistic markup: classless table cells, hashed classes, icon ligatures.
Calls the picker directly (no wizard), then extracts with the scraper's own extract.js.
"""

from pathlib import Path

import pytest

from scraper.config import DomConfig, FieldSpec, SelectorSpec
from scraper.scrape.dom import extract_cards

PICKER = Path(__file__).parent.parent / "scraper" / "onboard" / "picker.js"


@pytest.fixture
async def page(browser_context):
    page = await browser_context.new_page()
    await page.add_init_script(path=str(PICKER))
    yield page
    await page.close()


async def infer(page, title_selector):
    return await page.evaluate(
        "s => window.__onboard.inferCard(document.querySelector(s))", title_selector
    )


async def pick_field(page, cards, selector):
    return await page.evaluate(
        "([s, c]) => window.__onboard.inferField(document.querySelector(s), c)", [selector, cards]
    )


def dom_config(info, **overrides) -> DomConfig:
    fields = {k: FieldSpec(**v) for k, v in info["fields"].items()}
    fields.update({k: FieldSpec(**v) for k, v in overrides.items()})
    return DomConfig(card=SelectorSpec(candidates=info["card"]["candidates"]), fields=fields)


async def test_table_rows_with_classless_cells(page, site):
    await page.goto(f"{site}/table/index.html")
    info = await infer(page, "tbody tr:nth-child(2) a")
    assert info["count"] == 5
    rows = await extract_cards(page, dom_config(info))
    assert rows[1]["title"] == "Senior Backend Engineer"
    assert rows[1]["location"] == "Bengaluru, India"  # found automatically, by column position
    assert rows[1]["department"] == "Engineering"
    assert all(r["apply_url"].endswith(f"id={i + 1}") for i, r in enumerate(rows))

    # picking the location cell by hand gives the same column, not the title cell
    spec = await pick_field(page, info["card"]["candidates"], "tbody tr:nth-child(4) td:nth-child(3)")
    rows = await extract_cards(page, dom_config(info, location=spec))
    assert [r["location"] for r in rows] == [
        "Sydney, Australia", "Bengaluru, India", "Remote", "Amsterdam, Netherlands", "Austin, USA"]
    assert all("asc" not in s for s in spec["selectors"])


async def test_google_cards_hashed_classes_and_icons(page, site):
    await page.goto(f"{site}/google/index.html")
    info = await infer(page, "li:nth-child(2) h3")
    assert info["count"] == 3
    cards = info["card"]["candidates"]
    expected = ["Sunnyvale, CA, USA; Atlanta, GA, USA; +5 more", "Bengaluru, Karnataka, India",
                "Zürich, Switzerland; London, UK"]

    rows = await extract_cards(page, dom_config(info))
    assert [r["title"] for r in rows] == [
        "Software Engineer, Search", "Backend Engineer, Ads", "Data Scientist, YouTube"]
    assert [r.get("location") for r in rows] == expected  # auto-detected, icon text "place" left out
    assert rows[1]["apply_url"].endswith("/jobs/results/222-backend-engineer-ads")

    # by hand: clicking the city text, or the pin icon, both give the whole location
    for target in ("li:nth-child(3) span.r0wTof", "li:nth-child(1) span.pwO9Dc > i"):
        spec = await pick_field(page, cards, target)
        rows = await extract_cards(page, dom_config(info, location=spec))
        assert [r["location"] for r in rows] == expected, target
