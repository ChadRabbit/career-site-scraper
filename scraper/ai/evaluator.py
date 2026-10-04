"""
Ranks jobs against CANDIDATE_PROFILE with a local Ollama model.
One model for every job, so scores are comparable; output is schema-validated.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Literal

import requests
from pydantic import BaseModel, Field, ValidationError, field_validator

from scraper import settings
from scraper.log import get_logger

log = get_logger()


class Verdict(BaseModel):
    fit: Literal["Yes", "Maybe", "No"]
    score: int = Field(ge=0, le=10)
    reason: str

    @field_validator("fit", mode="before")
    @classmethod
    def _fit(cls, v):
        return str(v).strip().capitalize()

    @field_validator("score", mode="before")
    @classmethod
    def _score(cls, v):
        match = re.search(r"\d+", str(v))
        return max(0, min(10, int(match.group()))) if match else 0


_SCHEMA = {
    "type": "object",
    "properties": {
        "fit": {"type": "string", "enum": ["Yes", "Maybe", "No"]},
        "score": {"type": "integer", "minimum": 0, "maximum": 10},
        "reason": {"type": "string"},
    },
    "required": ["fit", "score", "reason"],
}


def build_prompt(job: dict) -> str:
    return f"""You are evaluating how relevant a job posting is for this candidate.

Candidate:
{settings.CANDIDATE_PROFILE}
Job:
Title: {job.get("title")}
Company: {job.get("company")}
Location: {job.get("location")}
Department: {job.get("department")}

Reply with JSON only: {{"fit": "Yes" | "Maybe" | "No", "score": 0-10, "reason": "one short sentence"}}"""


def ollama_available(base_url: str = settings.OLLAMA_URL) -> bool:
    try:
        return requests.get(f"{base_url}/api/tags", timeout=3).ok
    except requests.RequestException:
        return False


def _parse(text: str) -> Verdict:
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        raise ValueError("no JSON object in reply")
    return Verdict.model_validate(json.loads(match.group()))


def evaluate_job(job: dict, model: str = settings.AI_MODEL, base_url: str = settings.OLLAMA_URL) -> dict:
    last_error = None
    for _ in range(2):
        try:
            response = requests.post(
                f"{base_url}/api/generate",
                json={
                    "model": model,
                    "prompt": build_prompt(job),
                    "stream": False,
                    "format": _SCHEMA,  # not every model honours this, hence the validation below
                    "options": {"temperature": 0},
                },
                timeout=settings.AI_TIMEOUT_S,
            )
            response.raise_for_status()
            verdict = _parse(response.json().get("response", ""))
            job.update(ai_fit=verdict.fit, ai_score=verdict.score, ai_reason=verdict.reason)
            return job
        except (requests.RequestException, ValueError, ValidationError) as e:
            last_error = e
    log.warning(f"  AI failed for {job.get('title')!r}: {last_error}")
    job.update(ai_fit="Unknown", ai_score=0, ai_reason=f"evaluation failed: {str(last_error)[:80]}")
    return job


async def evaluate_jobs(
    jobs: list[dict],
    model: str = settings.AI_MODEL,
    concurrency: int = settings.AI_CONCURRENCY,
    limit: int | None = None,
) -> list[dict]:
    if not ollama_available():
        log.warning(f"Ollama is not reachable at {settings.OLLAMA_URL}; skipping AI ranking")
        return jobs
    targets = jobs[:limit] if limit else jobs
    semaphore = asyncio.Semaphore(concurrency)

    async def one(i: int, job: dict):
        async with semaphore:
            log.info(f"🤖 [{model}] {i + 1}/{len(targets)}: {job.get('title')}")
            await asyncio.to_thread(evaluate_job, job, model)

    await asyncio.gather(*(one(i, job) for i, job in enumerate(targets)))
    return sorted(jobs, key=lambda j: (j.get("ai_score") or 0, j.get("score") or 0), reverse=True)
