"""
python -m scraper onboard "Stripe" https://stripe.com/jobs/search
python -m scraper scrape [stripe snowflake] [--max-pages 3] [--ai]
python -m scraper list
python -m scraper ai runs/<run>/jobs_ranked.xlsx
python -m scraper session
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from scraper import settings
from scraper.log import setup_logger


def cmd_onboard(args) -> int:
    from scraper.onboard.wizard import OnboardingError, onboard

    try:
        cfg = asyncio.run(onboard(args.name, args.url, headless=args.headless, verify=not args.no_verify,
                                  force=args.force))
    except OnboardingError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1
    print(f"✓ Onboarded {cfg.name} (pagination: {cfg.pagination.type}, "
          f"{cfg.onboarded_job_count} jobs in test run) → configs/{cfg.slug}.json")
    return 0


def cmd_scrape(args) -> int:
    from scraper.ai.evaluator import evaluate_jobs
    from scraper.config import load_configs
    from scraper.pipeline.dedupe import deduplicate
    from scraper.pipeline.export import write_jobs
    from scraper.pipeline.normalize import normalize_job
    from scraper.pipeline.scoring import rank_jobs
    from scraper.scrape.runner import scrape_all

    configs = load_configs(args.companies or None)
    if not configs:
        print("No onboarded companies match. Onboard one first:\n"
              '  python -m scraper onboard "Company" https://company.com/careers', file=sys.stderr)
        return 1

    results = asyncio.run(scrape_all(configs, max_pages=args.max_pages, headless=args.headless,
                                     speed=settings.HUMAN_SPEED * (0.4 if args.fast else 1.0), har=args.har))

    run_dir = settings.RUNS_DIR / time.strftime("%Y%m%d_%H%M%S")
    jobs = [normalize_job(job) for r in results for job in r.jobs]
    write_jobs(run_dir / "jobs_raw.xlsx", jobs, "Raw")
    ranked = [j for j in rank_jobs(deduplicate(jobs)) if j["score"] >= settings.MIN_HEURISTIC_SCORE]
    write_jobs(run_dir / "jobs_ranked.xlsx", ranked, "Ranked")
    if args.ai:
        ai_jobs = asyncio.run(evaluate_jobs(ranked, limit=args.ai_limit))
        write_jobs(run_dir / "jobs_ai.xlsx", ai_jobs, "AI ranked")

    print(f"\n{'Company':<22}{'Status':<10}{'Pages':>6}{'Jobs':>7}")
    for r in results:
        print(f"{r.name:<22}{r.status:<10}{r.pages:>6}{len(r.jobs):>7}" + (f"   {r.error}" if r.error else ""))
    print(f"\nOutputs in {run_dir}")
    return 0


def cmd_list(args) -> int:
    from scraper.config import load_configs
    from scraper.health import load_health

    configs = load_configs()
    if not configs:
        print("No companies onboarded yet.")
        return 0
    health = load_health()
    print(f"{'Slug':<20}{'Pagination':<13}{'Popups':>7}  {'Last status':<13}{'Last jobs':>9}")
    for c in configs:
        h = health.get(c.slug, {})
        print(f"{c.slug:<20}{c.pagination.type:<13}{len(c.popups):>7}  {h.get('status', '-'):<13}"
              f"{h.get('last_count', '-'):>9}")
    return 0


def cmd_ai(args) -> int:
    from scraper.ai.evaluator import evaluate_jobs
    from scraper.pipeline.export import read_jobs, write_jobs

    path = Path(args.excel)
    jobs = asyncio.run(evaluate_jobs(read_jobs(path), model=args.model, limit=args.limit))
    write_jobs(path.with_name(path.stem + "_ai.xlsx"), jobs, "AI ranked")
    return 0


def cmd_session(args) -> int:
    """Open the persistent profile so you can browse a bit / accept cookie banners by hand."""
    from scraper.browser import open_browser

    async def run():
        async with open_browser(headless=False) as context:
            page = await context.new_page()
            await page.goto(args.url)
            await asyncio.to_thread(input, "Browse as long as you like, then press Enter here to close… ")

    asyncio.run(run())
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scraper", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("onboard", help="interactively onboard a company career page")
    p.add_argument("name")
    p.add_argument("url")
    p.add_argument("--force", action="store_true", help="overwrite an existing config")
    p.add_argument("--headless", action="store_true")
    p.add_argument("--no-verify", action="store_true", help="skip the test run after saving")
    p.set_defaults(func=cmd_onboard)

    p = sub.add_parser("scrape", help="scrape onboarded companies (all by default)")
    p.add_argument("companies", nargs="*", help="names or slugs; default: all")
    p.add_argument("--max-pages", type=int, default=None)
    p.add_argument("--ai", action="store_true", help="rank with the local LLM afterwards")
    p.add_argument("--ai-limit", type=int, default=None)
    p.add_argument("--har", action="store_true", help="also record a full HAR of the run")
    p.add_argument("--headless", action="store_true")
    p.add_argument("--fast", action="store_true", help="shorter human-like pauses")
    p.set_defaults(func=cmd_scrape)

    p = sub.add_parser("list", help="show onboarded companies and their last run")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("ai", help="LLM-rank an existing Excel output")
    p.add_argument("excel")
    p.add_argument("--model", default=settings.AI_MODEL)
    p.add_argument("--limit", type=int, default=None)
    p.set_defaults(func=cmd_ai)

    p = sub.add_parser("session", help="open the persistent browser profile by hand")
    p.add_argument("url", nargs="?", default="https://www.google.com")
    p.set_defaults(func=cmd_session)

    args = parser.parse_args(argv)
    import logging

    setup_logger(logging.DEBUG if args.verbose else logging.INFO)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
