"""
Config-driven job scraper.
To add a new company, just add an entry to COMPANY_CONFIGS.

Two strategies:
  - "api"  : intercept XHR/fetch responses matching a URL pattern
  - "dom"  : parse the rendered DOM via CSS selectors

Scrolling / pagination is also fully configurable per company.
"""

import asyncio
from typing import Optional
from playwright.async_api import async_playwright
from openpyxl import Workbook
import datetime
import os

from logger import setup_logger

log = setup_logger()
from companies import COMPANY_CONFIGS
from jobAIEvaluator import JobAIEvaluator
from strategy import scrape_company_in_tab
from utils import load_jobs_from_excel, save_to_excel, flatten_jobs, deduplicate_jobs, add_scores, sort_jobs, \
    save_final_excel


def save_ai_excel(jobs):
    os.makedirs("runs", exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"runs/jobs_ai_{timestamp}.xlsx"

    wb = Workbook()
    ws = wb.active
    ws.title = "AI Jobs"

    headers = [
        "Company", "Title", "Location", "Department",
        "Score", "AI Fit", "AI Score", "AI Reason",
        "Apply URL"
    ]
    ws.append(headers)

    for job in jobs:
        ws.append([
            job.get("Company") or job.get("company"),
            job.get("Title") or job.get("title"),
            job.get("Location") or job.get("location"),
            job.get("Department") or job.get("department"),
            job.get("Score") or job.get("score"),
            job.get("ai_fit"),
            job.get("ai_score"),
            job.get("ai_reason"),
            job.get("Apply URL") or job.get("apply_url"),
        ])

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    wb.save(filename)
    log.info(f"\n🧠 Saved AI Excel: {filename}")


async def run_ai_on_excel(filepath, models=None, limit=None):
    jobs = load_jobs_from_excel(filepath)
    if limit is None:
        limit = len(jobs)

    models = models or [
        {"name": "qwen2.5:3b", "url": "http://localhost:11434"},
        {"name": "qwen2.5:7b", "url": "http://localhost:11434"},
    ]

    queue = asyncio.Queue()

    for i, job in enumerate(jobs[:limit]):
        await queue.put((i, job))

    async def worker(model_config):
        evaluator = JobAIEvaluator(
            model=model_config["name"],
            base_url=model_config["url"]
        )

        while not queue.empty():
            try:
                i, job = await queue.get()
            except Exception as e:
                log.error("Got error ", e)
                return

            log.info(f"🤖 [{model_config['name']}] {i + 1}: {job.get('Title')}")

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, evaluator.evaluate_job, job)

            queue.task_done()

    tasks = [
        asyncio.create_task(worker(m))
        for m in models
    ]

    await asyncio.gather(*tasks)

    return jobs


def sort_by_ai_score(jobs):
    return sorted(jobs, key=lambda x: x.get("ai_score", 0), reverse=True)


async def main(companies: Optional[list[str]] = None):
    """
    Run scraper for specified companies (by name), or all if not specified.
    e.g. main(["Uber", "Databricks"])
    """
    configs = COMPANY_CONFIGS
    if companies:
        configs = [c for c in configs if c.name in companies]

    all_results: dict[str, list[dict]] = {}

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir="user_data",
            headless=False,
        )

        tasks = [
            scrape_company_in_tab(context, cfg)
            for cfg in configs
        ]

        results_list = await asyncio.gather(*tasks)
        all_results = dict(results_list)
        await context.close()
    save_to_excel(all_results)
    jobs = flatten_jobs(all_results)
    jobs = deduplicate_jobs(jobs)
    jobs = add_scores(jobs)
    jobs = sort_jobs(jobs)
    final_path = save_final_excel(jobs)
    jobs = await run_ai_on_excel(
        final_path,
        models=[
            {"name": "qwen2.5:3b", "url": "http://localhost:11434"},
            # {"name": "qwen2.5:7b", "url": "http://localhost:11434"},
            # {"name": "gemma4:e2b", "url": "http://localhost:11434"},
        ],
    )

    jobs = sort_by_ai_score(jobs)

    save_ai_excel(jobs)
    return all_results


if __name__ == "__main__":
    # ── Edit this list to run only specific companies, or pass [] for all ──
    TARGET_COMPANIES = ["Google"]

    results = asyncio.run(main(TARGET_COMPANIES if TARGET_COMPANIES else None))

    for company, jobs in results.items():
        log.info(f"\n{'─' * 40}")
        log.info(f"  {company}: {len(jobs)} total jobs")
        log.info(f"{'─' * 40}")
