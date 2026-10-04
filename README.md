# Career Site Scraper

Onboard any company's career page in about a minute by clicking through it once, then scrape it on a schedule, one company at a time and at a human pace. Jobs are ranked with keyword scoring and a local LLM (Ollama).

```
onboard (once per company, ~1 min, you click)  →  configs/<company>.json
scrape  (any time, no human)                   →  runs/<timestamp>/jobs_raw / jobs_ranked / jobs_ai.xlsx
```

## Quick start

```bash
python -m scraper onboard "Stripe" "https://stripe.com/jobs/search"   # once per company: click through the page
python -m scraper scrape --ai                                         # any time: scrape every onboarded company
python -m scraper list                                                # what's onboarded + last run status
```

---

## Setup

Requires Python 3.10+ (macOS, Linux or Windows).

```bash
git clone https://github.com/ChadRabbit/career-site-scraper.git
cd career-site-scraper
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

Optional, for AI ranking: install [Ollama](https://ollama.com), then `ollama pull qwen2.5:7b`. The model and your candidate profile live in `scraper/settings.py`. Without Ollama, `--ai` is skipped with a warning and everything else still works.

For development (tests and lint): `pip install -r requirements-dev.txt`.

---

## Onboarding a company

```bash
python -m scraper onboard "Stripe" "https://stripe.com/jobs/search"
```

A browser opens with an instruction panel in the bottom-right corner (⇅ moves it, – collapses it). All traffic is recorded from the first request. Steps:

1. **Search (optional).** Click the search box, type a query, and submit it (Enter or the button), then press **Done**. If the query shows up in the URL, the URL is saved as a template and future runs skip the typing. If your start URL is already filtered (e.g. `?team=engineering`), press **Skip**.
2. **Pick one job (the main click).** Click any job title. The click is intercepted rather than followed. The tool then works out the rest:
   - finds the repeated job card around your click, even if the class names are hashed
   - outlines every card in orange
   - detects title, link, location, department, date and job ID
   - shows a preview table

   Fix a column with **Pick location / department / date**, or press **Looks right**.
3. **Learning the job link (automatic).** It opens the job you picked like a person would (it handles new tabs, normal navigation and single-page-app route changes), records the URL and comes back. If the cards have no links (click handlers only), it finds the card attribute that appears in the job URL and saves a template such as `…/jobs?jobId={job_id}`.
4. **Next page.** Click **Next**, page **2**, or **Load more**, or press **Infinite scroll** / **Single page**. The tool clicks it itself and confirms that new jobs appeared.
5. **Test run (automatic).** The config is saved and replayed for 2 pages; the result is shown. Press **Finish**.

**Popups (cookie banners, newsletter modals, chat prompts):** at any step, press **Record popup** in the panel, then click the popup's close/accept button. That click goes through, so the popup closes, and it's saved to the config. A background watcher then closes it whenever it reappears, every 5 s during onboarding and every scrape. Record as many as you need.

If the site shows a bot check, the wizard waits. If it asks you to verify, do it yourself in the window. **Pause** lets you click around freely without your clicks being recorded. Closing the window cancels onboarding without saving.

To re-onboard after a site redesign, add `--force`. To skip the test run, add `--no-verify`.

### What gets saved

`configs/<slug>.json`, a human-readable config that you can also edit by hand:

```json
{
  "name": "Initech",
  "dom": {
    "card":   {"candidates": ["section > div.posting", "div.posting"]},
    "fields": {
      "title":    {"selectors": ["h3.posting-title"]},
      "location": {"selectors": ["p.posting-loc"]},
      "job_id":   {"selectors": [], "attr": "data-job-id"}
    },
    "apply_url_template": "https://initech.com/job.html?jobId={job_id}"
  },
  "popups": [{"candidates": ["#onetrust-accept-btn-handler"]}],
  "pagination": {"type": "none", "max_pages": 5}
}
```

Every selector is a list of fallbacks, tried in order: a short readable selector when it's unambiguous, then an exact position path (`:scope > td:nth-of-type(3)`) for markup with no usable classes. Pagination also stores the page-2 URL pattern (`…?page={page}`), used as a fallback if the next-page control can't be found.

### Network capture

Every onboarding stores **all** traffic locally, under `captures/<slug>/onboard_<timestamp>/`:

| File | What |
|---|---|
| `network.har.zip` | Full HAR (every request/response, including bodies), recorded by Playwright. Open it in Chrome DevTools → Network → Import. |
| `index.jsonl` | One line per response: URL, method, status, headers, request body, and the path to the saved body |
| `bodies/` | Response bodies (JSON, HTML, JS…) |
| `screenshots/` | Page after load, the job page, page 2 |

Scrape runs keep a lighter capture (XHR/fetch/document bodies plus a screenshot per page) in `captures/<slug>/scrape_<timestamp>/`. Add `--har` to also record a full HAR.

---

## Scraping

```bash
python -m scraper scrape                     # every onboarded company
python -m scraper scrape stripe snowflake    # just these
python -m scraper scrape --max-pages 3 --ai  # + local LLM ranking
python -m scraper list                       # onboarded companies + last run status
python -m scraper ai runs/<run>/jobs_ranked.xlsx   # LLM-rank an existing sheet
python -m scraper session                    # open the browser profile by hand
```

How a run behaves:

- **One company at a time**, with a 20–45 s pause between companies and a 4–10 s pause between pages.
- **Human-like browsing:** eased scrolling with reading pauses (cards are read on every scroll step, so virtualised lists work), curved mouse movement before clicks, and per-character typing.
- **One browser profile** that persists between runs (`user_data/`), so cookie consent and reputation carry over.
- **Bot checks** (Cloudflare, DataDome, Akamai, 403/429) get up to 25 s to clear by themselves, with no interaction. If still blocked, the company is skipped and you're told to run `python -m scraper session <url>` once by hand.
- **Recorded popups** are closed by a background watcher every 5 s, and right before every search or page change.
- **Health tracking** in `state/health.json`. If a company returns nothing, or under half its usual count, you get a warning with the exact command to re-onboard it.

All tunables (delays, keyword weights, the LLM model, your candidate profile) live in `scraper/settings.py`.

---

## How it works

**Onboarding** (`python -m scraper onboard`): `onboard/wizard.py` drives the steps.

```
wizard.py ── opens persistent browser + HAR ──► NetworkRecorder (capture.py) writes all traffic to captures/
    │
    ├─ bridge.install(): injects picker.js into every frame + two bindings (__onboardEvent, __onboardHello)
    │       picker.js = panel UI, hover highlight, click capture (intercept / passive), card + field inference
    │       Python → page: bridge.show(step, mode, message, buttons, preview)   (re-sent after every navigation)
    │       page → Python: pick / click / input / key / button / popup events  (queued; "popup" handled aside)
    ├─ PopupWatcher (popups.py): closes recorded popups every 5 s
    ├─ wait_for_real_page   bot check → wait (or user verifies)
    ├─ step_search          passive clicks + typing → SearchConfig (results_url template if query is in URL)
    ├─ step_card            intercepted click → picker.inferCard(): repeated card + fields → preview (extract.js)
    ├─ step_open            click the job ourselves → detail URL → link field or URL template → go back
    ├─ step_pagination      intercepted click → classify (next / page number / load more) → verify new jobs
    └─ save configs/<slug>.json → replay 2 pages with the real scraper (runner.py) → Finish
```

**Scraping** (`python -m scraper scrape`): `scrape/runner.py`, one company at a time.

```
load configs/*.json ─► open browser ─► per company:
    goto start_url → bot check? wait up to 25 s, else skip
    → PopupWatcher → search (results URL or type + submit)
    → per page: wait for cards → human scroll; extract.js harvests cards on every step (dedup by job link)
              → next page: recorded control, else recorded URL pattern; stop when nothing new / max_pages
    → health.json (warns when a company drops to 0 or under half its usual count)
─► pipeline: normalize → dedupe → keyword score → Excel ─► optional Ollama ranking → Excel
```

## Project structure

```
scraper/
  __main__.py          CLI (onboard / scrape / list / ai / session)
  settings.py          all tunables
  config.py            CompanyConfig schema (pydantic) + load/save
  browser.py           persistent Chromium (optional: patchright), HAR recording
  capture.py           NetworkRecorder (traffic + bodies on disk), screenshots
  human.py             human-like scroll / mouse / typing
  popups.py            PopupWatcher: closes recorded popups
  blocking.py          bot-check detection + waiting
  health.py            per-company run health
  locate.py            resolve selector fallbacks, find the listing frame
  onboard/
    wizard.py          the onboarding steps
    picker.js          in-page panel, click capture, job-card + field inference
    bridge.py          Python ⇄ page messaging
    url_tools.py       search / pagination / job-link URL templates
  scrape/
    runner.py          replays configs, one company at a time
    dom.py, extract.js card extraction (extract.js is shared with the wizard preview)
    search.py          replay the recorded search
    navigation.py      next page, quiet-network waits
  pipeline/            normalize → dedupe → keyword score → Excel
  ai/evaluator.py      Ollama ranking with schema-validated output
tests/                 unit tests + end-to-end onboarding against local fixture sites
```

## Tests and lint

```bash
pytest
ruff check scraper tests
```

The end-to-end tests run the real wizard in headless Chromium against small local career sites, with the test playing the human:
- DOM listing with search and Next
- cards without links (JS click handlers)
- a self-clearing bot check
- a cookie popup that blocks every page
- a site enforcing Trusted Types
- closing the window mid-way

Field-picking tests use real-world markup: a table with no cell classes, and Google-style cards with hashed classes and icon fonts.

## Notes

- Sites with obfuscated class names are handled by preferring attributes/structure. If a config breaks after a redesign, re-onboard it (about a minute).
- Listings inside iframes (embedded job boards) are supported. Closed shadow DOM is not.
- Respect each site's terms of service and keep the rate low. The defaults are deliberately slow.
