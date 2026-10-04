"""
Remembers how each company did last time, so a sudden drop to zero (site redesign,
block) is flagged for re-onboarding instead of silently producing empty sheets.
"""

from __future__ import annotations

import json
from datetime import datetime

from scraper import settings
from scraper.log import get_logger

log = get_logger()


def _path():
    return settings.STATE_DIR / "health.json"


def load_health() -> dict:
    try:
        return json.loads(_path().read_text())
    except (FileNotFoundError, ValueError):
        return {}


def update_health(cfg, result) -> dict:
    health = load_health()
    previous = health.get(cfg.slug, {})
    baseline = previous.get("count") or cfg.onboarded_job_count
    count = len(result.jobs)

    status = result.status
    if status == "ok" and baseline and count < baseline * 0.5:
        status = "degraded"
    if status == "blocked":
        log.warning(f"  {cfg.name}: blocked by a bot check. Open it once by hand to clear it, then re-run:\n"
                    f'    python -m scraper session "{cfg.start_url}"')
    elif status in ("empty", "degraded", "error"):
        log.warning(
            f"  {cfg.name}: {status} ({count} jobs, baseline {baseline}). If the site changed, re-run:\n"
            f'    python -m scraper onboard "{cfg.name}" "{cfg.start_url}" --force'
        )

    health[cfg.slug] = {
        "name": cfg.name,
        "last_run": datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "count": count if result.status == "ok" else previous.get("count", 0),
        "last_count": count,
        "pages": result.pages,
        "error": result.error,
    }
    _path().parent.mkdir(parents=True, exist_ok=True)
    _path().write_text(json.dumps(health, indent=2))
    return health[cfg.slug]
