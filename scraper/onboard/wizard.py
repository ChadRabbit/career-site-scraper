"""
Interactive onboarding: open a career site, ask the user for a few clicks, write configs/<slug>.json.

    0. load     – wait out bot checks; the panel's "Record popup" button works from here on
    1. search   – optional: click the search box, type, submit (recorded; URL template if possible)
    2. card     – click one job → repeated cards + fields inferred, previewed, confirmed
    3. open     – we open that job ourselves to learn what job links look like, then come back
    4. next     – click "Next" / page "2" / "Load more" (or choose infinite scroll / single page)
    5. verify   – save the config and replay it for 2 pages
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from scraper import settings
from scraper.blocking import detect_block, wait_until_clear
from scraper.browser import open_browser
from scraper.capture import NetworkRecorder, screenshot
from scraper.config import (
    CompanyConfig,
    DomConfig,
    FieldSpec,
    PaginationConfig,
    SearchConfig,
    SelectorSpec,
    config_path,
    save_config,
    slugify,
)
from scraper.human import Human
from scraper.locate import find_frame
from scraper.log import get_logger
from scraper.onboard.bridge import Bridge, OnboardingAborted, button
from scraper.onboard.url_tools import page_url_template, query_url_template, template_from_attributes
from scraper.pipeline.normalize import normalize_job
from scraper.popups import PopupWatcher
from scraper.scrape.dom import count_cards, extract_cards
from scraper.scrape.navigation import QuietNetwork, settle
from scraper.scrape.runner import scrape_company
from scraper.scrape.search import apply_search, is_plausible_query

log = get_logger()


class OnboardingError(Exception):
    pass


@dataclass
class Session:
    """Everything one onboarding run shares between steps."""

    name: str
    start_url: str
    context: object
    page: object
    bridge: Bridge
    human: Human
    run_dir: Path
    watcher: PopupWatcher | None = None
    frame_marker: str | None = None  # set when the job list lives in an iframe
    notes: list[str] = field(default_factory=list)

    def popup_specs(self) -> list[SelectorSpec]:
        return [SelectorSpec(candidates=d["candidates"], fingerprint=_fingerprint(d))
                for d in self.bridge.popups if d.get("candidates")]

    async def close_popups(self) -> None:
        """Recorded popups often come back after navigation; close them before the next click."""
        if self.watcher:
            await self.watcher.check_now()

    def listing(self):
        """The frame holding the job list."""
        return find_frame(self.page, self.frame_marker)


def _fingerprint(descriptor: dict) -> dict:
    return {k: descriptor.get(k) for k in ("tag", "text", "attrs", "rect") if descriptor.get(k) is not None}


def _preview(rows: list[dict], company: str, limit: int = 8) -> list[dict]:
    return [normalize_job(dict(r, company=company)) for r in rows[:limit]]


# ── Step 0: bot check ────────────────────────────────────────────────────
async def wait_for_real_page(s: Session, status: int | None, timeout_s: float = 300) -> None:
    """If a bot check is showing, let it clear (or let the user complete it), then continue."""
    reason = await detect_block(s.page, status)
    if not reason:
        return
    await s.bridge.show(step="blocked", title="Bot check",
                        message=("The site is showing a bot check. Usually it clears by itself in a few seconds.\n"
                                 "If it asks you to verify, complete it yourself in this window — "
                                 "onboarding continues once the careers page loads."),
                        status=reason)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if s.page.is_closed():
            raise OnboardingAborted("browser window was closed")
        if not await wait_until_clear(s.page, 2):
            await settle(s.page)
            log.info("bot check cleared")
            return
    raise OnboardingError(f"The site kept showing a bot check ({reason}). Try again later.")


# ── Step 1: search ───────────────────────────────────────────────────────
def _is_button(desc: dict) -> bool:
    attrs = desc.get("attrs") or {}
    return (desc.get("tag") in ("button", "a") or attrs.get("role") == "button"
            or (desc.get("tag") == "input" and attrs.get("type") in ("submit", "button", "image")))


async def step_search(s: Session) -> SearchConfig | None:
    before_url = s.page.url
    await s.bridge.show(
        step="search", mode="passive", title="Search (optional)",
        message=("If you want to filter jobs with the site's search box: click it, type your query "
                 "(e.g. Software Engineer) and submit it (Enter or the search button). Then press Done.\n\n"
                 "Tip: if the URL you started from is already filtered, just press Skip."),
        buttons=[button("done", "Done", primary=True), button("skip", "Skip")],
    )
    input_desc = button_desc = query = None
    pressed_enter = False
    while True:
        event = await s.bridge.next_event({"click", "input", "key", "button"}, step="search")
        if event["type"] == "button":
            if event.get("id") in ("done", "skip"):
                break
            continue
        desc = event.get("descriptor") or {}
        if event["type"] == "click":
            if desc.get("inputLike"):
                input_desc = desc
            elif input_desc and _is_button(desc):  # only a real button counts as "submit"
                button_desc = desc
        elif event["type"] in ("input", "key") and desc.get("inputLike"):
            input_desc = input_desc or desc
            if is_plausible_query(event.get("value")):
                query = event["value"]
            if event["type"] == "key":
                pressed_enter = True

    if event.get("id") == "skip" or not input_desc or not (query or "").strip():
        return None
    await settle(s.page)
    query = query.strip()
    results_url = query_url_template(s.page.url, query) if s.page.url != before_url else None
    submit = "enter" if pressed_enter else ("click" if button_desc else "none")
    s.notes.append(f"search: '{query}' via {'URL template' if results_url else submit}")
    return SearchConfig(
        query=query,
        input=SelectorSpec(candidates=input_desc["candidates"], fingerprint=_fingerprint(input_desc)),
        submit=submit,
        submit_button=SelectorSpec(candidates=button_desc["candidates"], fingerprint=_fingerprint(button_desc))
        if button_desc and submit == "click" else None,
        results_url=results_url,
    )


# ── Step 2: pick a job card ──────────────────────────────────────────────
async def _dom_preview(frame, dom: DomConfig, company: str) -> list[dict]:
    try:
        return _preview(await extract_cards(frame, dom), company, limit=50)
    except Exception as e:  # frame navigated away mid-preview
        log.debug(f"preview failed: {e}")
        return []


async def step_card(s: Session) -> tuple[DomConfig, object, dict]:
    """Returns the DOM config, the frame holding the cards, and the raw inference (for step 3)."""
    status = ""
    while True:
        await s.bridge.show(
            step="card", mode="intercept", title="Pick one job",
            message=("Click the title of any job listing.\n"
                     "(A popup in the way? Use 'Record popup', or Pause to click around freely.)"),
            status=status,
        )
        event = await s.bridge.next_event({"pick"}, step="card")
        frame = event["_frame"]
        info = await frame.evaluate("() => window.__onboard.inferCard(window.__onboard.target('card'))")
        if not info:
            status = "Couldn't find repeated job cards around that element. Try clicking directly on a job title."
            continue

        dom = DomConfig(
            card=SelectorSpec(candidates=info["card"]["candidates"], fingerprint=_fingerprint(event["descriptor"])),
            fields={name: FieldSpec(**spec) for name, spec in info["fields"].items()},
        )
        status = ""
        while True:
            rows = await _dom_preview(frame, dom, s.name)
            await frame.evaluate("c => window.__onboard.highlight(c)", dom.card.candidates)
            missing = [f for f in ("location", "department") if f not in dom.fields]
            await s.bridge.show(
                step="card_confirm", title=f"Found {len(rows)} job cards",
                message=("They're outlined in orange on the page. Check the preview: does each row look like one job?"
                         + (f"\nNot detected: {', '.join(missing)} (optional — pick them if the cards show them)."
                            if missing else "")),
                preview=rows[:8], status=status,
                buttons=[button("confirm", "Looks right", primary=True),
                         button("pick_location", "Pick location"),
                         button("pick_department", "Pick department"),
                         button("pick_posted", "Pick date"),
                         button("retry", "Pick a different job")],
            )
            choice = await s.bridge.wait_button({"confirm", "retry", "pick_location", "pick_department", "pick_posted"})
            if choice in ("confirm", "retry"):
                await frame.evaluate("() => window.__onboard.clearHighlight()")
                if choice == "confirm":
                    return dom, frame, info
                break
            field_name = choice.removeprefix("pick_")
            await s.bridge.show(step="field", mode="intercept", title=f"Pick {field_name}",
                                message=f"Click the {field_name} text inside any orange-outlined job card.")
            pick = await s.bridge.next_event({"pick"}, step="field")
            spec = await pick["_frame"].evaluate(
                "c => window.__onboard.inferField(window.__onboard.target('field'), c)", dom.card.candidates
            )
            if spec:
                dom.fields[field_name] = FieldSpec(**spec)
                status = f"✓ {field_name} updated"
            else:
                status = f"That element isn't inside a job card — {field_name} unchanged."


# ── Step 3: open the picked job, learn its URL, come back ────────────────
async def open_and_return(s: Session, target, restore) -> str | None:
    """Click target like a person would; return where it led (new tab / navigation / SPA route), then go back."""
    before = s.page.url
    new_pages: list = []

    def on_page(p):  # Playwright can't wrap builtins like list.append as handlers
        new_pages.append(p)

    s.context.on("page", on_page)
    try:
        await s.human.click(target)
        for _ in range(40):
            if new_pages or s.page.url != before:
                break
            await asyncio.sleep(0.25)
    except Exception as e:
        log.warning(f"could not click the job: {e}")
        return None
    finally:
        s.context.remove_listener("page", on_page)

    detail_url = None
    if new_pages:  # opened in a new tab
        detail = new_pages[0]
        for _ in range(40):
            if detail.url not in ("", "about:blank"):
                break
            await asyncio.sleep(0.25)
        await settle(detail)
        detail_url = detail.url
        await screenshot(detail, s.run_dir, "detail")
        await detail.close()
    elif s.page.url != before:  # same tab (navigation or SPA route)
        await settle(s.page)
        detail_url = s.page.url
        await screenshot(s.page, s.run_dir, "detail")
        try:
            await s.page.go_back(wait_until="domcontentloaded")
            await settle(s.page)
        except Exception as e:
            log.debug(f"go_back failed: {e}")
    await restore()
    await s.close_popups()
    return detail_url


async def step_open(s: Session, frame, dom: DomConfig, info: dict, search: SearchConfig | None) -> None:
    await s.bridge.show(step="open", title="Opening that job…",
                        message="Learning what a job link looks like. We'll come back to the list automatically.")

    async def restore():
        if await count_cards(s.listing(), dom) == 0:  # back-navigation lost the list: rebuild it
            await s.page.goto(s.start_url, wait_until="domcontentloaded")
            await settle(s.page)
            if search:
                await apply_search(s.page, s.listing(), search, s.human)

    detail_url = await open_and_return(s, frame.locator('[data-onboard-target="card"]').first, restore)
    if not detail_url:
        s.notes.append("clicking a job did not open a page (modal/side panel?)")
        return
    s.notes.append(f"sample job page: {detail_url}")
    if "apply_url" in dom.fields:
        return
    # cards without links: find the card attribute that appears in the job URL → URL template
    template, id_spec = template_from_attributes(detail_url, info.get("attributes", []))
    if template:
        dom.apply_url_template = template
        dom.fields["job_id"] = FieldSpec(**id_spec)
        s.notes.append(f"job links built from template {template}")
    else:
        s.notes.append("cards have no links and no id matched the job page URL; apply_url will be empty")


# ── Step 4: pagination ───────────────────────────────────────────────────
def classify_pagination(desc: dict) -> PaginationConfig:
    text = (desc.get("text") or "").strip()
    attrs = desc.get("attrs") or {}
    blob = " ".join([text, attrs.get("aria-label", ""), attrs.get("class", ""), attrs.get("rel", "")]).lower()
    control = SelectorSpec(candidates=desc["candidates"], fingerprint=_fingerprint(desc))
    if re.fullmatch(r"\d+", text) and desc.get("pageTemplate"):
        return PaginationConfig(type="page_number", page_number_template=desc["pageTemplate"], control=control)
    if re.search(r"\b(load|show|view|see)\s*(more|all)\b|\bmore (jobs|results|roles|positions)\b", blob):
        return PaginationConfig(type="load_more", control=control)
    return PaginationConfig(type="next", control=control)


async def _job_keys(s: Session, dom: DomConfig) -> set:
    rows = await extract_cards(s.listing(), dom)
    return {(r.get("title"), r.get("apply_url")) for r in rows}


async def step_pagination(s: Session, dom: DomConfig) -> PaginationConfig:
    status = ""
    while True:
        await s.bridge.show(
            step="next", mode="intercept", title="Next page",
            message=("Scroll down and click whatever shows more jobs: 'Next', page '2', or 'Load more'.\n"
                     "More jobs appear as you scroll? Press Infinite scroll. "
                     "Everything on one page? Press Single page."),
            status=status,
            buttons=[button("scroll", "Infinite scroll"), button("none", "Single page")],
        )
        event = await s.bridge.next_event({"pick", "button"}, step="next")
        if event["type"] == "button":
            if event.get("id") in ("scroll", "none"):
                return PaginationConfig(type=event["id"])
            continue

        pagination = classify_pagination(event["descriptor"])
        await s.bridge.show(step="next_verify", title="Checking the next page…", message=f"Detected: {pagination.type}")
        before_url = s.page.url
        before = await _job_keys(s, dom)
        try:
            async with QuietNetwork(s.page):
                await s.human.click(event["_frame"].locator('[data-onboard-target="next"]').first)
        except Exception as e:
            status = f"Couldn't click that element ({str(e)[:80]}). Try again."
            continue

        new = 0
        for _ in range(16):  # slow sites: give new results up to ~8s to show up
            try:
                new = len(await _job_keys(s, dom) - before)
            except Exception:  # page mid-navigation
                new = 0
            if new:
                break
            await asyncio.sleep(0.5)
        pagination.url_template = page_url_template(before_url, s.page.url)
        await screenshot(s.page, s.run_dir, "page2")

        if new:
            s.notes.append(f"pagination '{pagination.type}' verified: {new} new jobs on page 2")
            return pagination
        await s.bridge.show(
            step="next_failed", title="Hmm",
            message="Couldn't confirm that new jobs appeared after that click.",
            buttons=[button("keep", "Keep it anyway"), button("retry", "Try again", primary=True),
                     button("none", "Single page")],
        )
        choice = await s.bridge.wait_button({"keep", "retry", "none"})
        if choice == "keep":
            s.notes.append(f"pagination '{pagination.type}' kept without verification")
            return pagination
        if choice == "none":
            return PaginationConfig(type="none")
        status = "Pick the next-page control again."


# ── Orchestration ────────────────────────────────────────────────────────
async def onboard(
    name: str,
    url: str,
    *,
    context=None,
    headless: bool = False,
    speed: float | None = None,
    verify: bool = True,
    force: bool = False,
    config_dir: Path | None = None,
    capture_dir: Path | None = None,
    verify_pages: int = 2,
) -> CompanyConfig:
    """Run the wizard. Pass `context` to reuse an existing browser context (tests do)."""
    slug = slugify(name)
    path = config_path(slug, config_dir)
    if path.exists() and not force:
        raise OnboardingError(f"{path} already exists — pass --force to re-onboard {name}")
    run_dir = (capture_dir or settings.CAPTURE_DIR) / slug / f"onboard_{time.strftime('%Y%m%d_%H%M%S')}"

    async def run(ctx) -> CompanyConfig:
        return await _onboard(ctx, name, url, run_dir, speed=speed, verify=verify, config_dir=config_dir,
                              verify_pages=verify_pages)

    if context is not None:
        return await run(context)
    async with open_browser(headless=headless, har_path=run_dir / "network.har.zip") as ctx:
        return await run(ctx)


async def _onboard(context, name: str, url: str, run_dir: Path, *, speed, verify, config_dir,
                   verify_pages) -> CompanyConfig:
    bridge = Bridge()
    await bridge.install(context)
    recorder = NetworkRecorder(run_dir, mode="all").attach(context)
    # persistent contexts start with an empty tab; use it instead of opening a second one
    page = next((p for p in context.pages if p.url == "about:blank"), None) or await context.new_page()
    bridge.watch(page)
    s = Session(name, url, context, page, bridge, Human(page, speed), run_dir)
    s.watcher = PopupWatcher(page, s.popup_specs).start()
    log.info(f"Onboarding {name} — capturing all traffic to {run_dir}")

    try:
        response = await page.goto(url, wait_until="domcontentloaded")
        await settle(page)
        await wait_for_real_page(s, response.status if response else None)
        await bridge.show(step="load", title=f"Onboarding {name}", message="Loading the page…")
        await s.human.scroll_page(max_steps=3)
        await settle(page, 4_000)
        await screenshot(page, run_dir, "loaded")

        await s.close_popups()
        search = await step_search(s)
        await s.close_popups()
        dom, frame, info = await step_card(s)
        if frame != page.main_frame:
            parsed = urlparse(frame.url)
            s.frame_marker = parsed.netloc + parsed.path
        await step_open(s, frame, dom, info, search)
        await s.close_popups()
        pagination = await step_pagination(s, dom)

        cfg = CompanyConfig(
            name=name, slug=slugify(name), start_url=url, frame_url_contains=s.frame_marker, popups=s.popup_specs(),
            dom=dom, search=search, pagination=pagination, notes=s.notes,
        )
        saved = save_config(cfg, config_dir)
        log.info(f"✅ Saved {saved}")

        if verify:
            await bridge.show(step="verify", title="Test run",
                              message=f"Config saved. Replaying it for {verify_pages} pages to check it works…")
            result = await scrape_company(context, cfg, max_pages=verify_pages, speed=speed,
                                          run_dir=run_dir / "verify")
            cfg.onboarded_job_count = len(result.jobs)
            save_config(cfg, config_dir)
            ok = result.status == "ok"
            await bridge.show(
                step="done", title="Done" if ok else "Saved, but the test run found nothing",
                message=(f"{name}: {len(result.jobs)} jobs over {result.pages} page(s).\nSaved to {saved}."
                         if ok else f"Status: {result.status} {result.error or ''}\nYou can re-onboard with --force."),
                preview=_preview(result.jobs, name),
                buttons=[button("finish", "Finish", primary=True)],
            )
        else:
            await bridge.show(step="done", title="Done", message=f"Saved to {saved}.",
                              buttons=[button("finish", "Finish", primary=True)])
        await bridge.wait_button({"finish"})
        return cfg

    except OnboardingAborted:
        raise OnboardingError("Onboarding cancelled: the browser window was closed") from None
    finally:
        await s.watcher.stop()
        await recorder.close()
        if not page.is_closed():
            await page.close()
