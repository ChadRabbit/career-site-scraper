from __future__ import annotations


def dedupe_key(job: dict) -> str | None:
    company = (job.get("company") or "").lower()
    if job.get("job_id"):
        return f"{company}|id|{job['job_id']}"
    if job.get("apply_url"):
        return f"url|{job['apply_url'].lower()}"
    if job.get("title"):
        return f"{company}|{job['title'].lower()}|{(job.get('location') or '').lower()}"
    return None


def deduplicate(jobs: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique = []
    for job in jobs:
        key = dedupe_key(job)
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique
