"""Cheap keyword pre-ranking before the (slow) LLM pass. Weights live in settings.py."""

from __future__ import annotations

import re

from scraper import settings


def _compile(weights: dict[str, int]) -> list[tuple[re.Pattern, int]]:
    # whole words only: "sr" must not match "SRE", "intern" must not match "internal"
    return [(re.compile(rf"\b(?:{pattern})\b", re.IGNORECASE), points) for pattern, points in weights.items()]


_TITLE = _compile(settings.TITLE_KEYWORDS)
_LOCATION = _compile(settings.LOCATION_KEYWORDS)


def score_job(job: dict) -> int:
    title = job.get("title") or ""
    location = job.get("location") or ""
    score = sum(points for rx, points in _TITLE if rx.search(title))
    score += sum(points for rx, points in _LOCATION if rx.search(location))
    return score


def rank_jobs(jobs: list[dict]) -> list[dict]:
    for job in jobs:
        job["score"] = score_job(job)
    return sorted(jobs, key=lambda j: j["score"], reverse=True)
