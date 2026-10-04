from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_LABEL_PREFIX = re.compile(
    r"^(location|locations|department|team|category|posted( on)?|date posted|job id|req(uisition)? id)\s*[:\-–]?\s+",
    re.IGNORECASE,
)
_TRACKING_PARAMS = re.compile(r"^(utm_.*|gh_src|source|src|ref|lever-source.*|trk.*)$", re.IGNORECASE)


def clean_text(value, single_line: bool = False) -> str | None:
    if value is None:
        return None
    text = str(value).replace(" ", " ")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return None
    text = lines[0] if single_line else " | ".join(dict.fromkeys(lines))
    text = _LABEL_PREFIX.sub("", text).strip()
    return text or None


def canonical_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url.strip())
    if not parsed.scheme:
        return url.strip()
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if not _TRACKING_PARAMS.match(k)]
    path = parsed.path.rstrip("/") or "/"
    return urlunparse(parsed._replace(path=path, query=urlencode(query), fragment=""))


def normalize_job(raw: dict) -> dict:
    job = {
        "company": clean_text(raw.get("company")),
        "title": clean_text(raw.get("title"), single_line=True),
        "location": clean_text(raw.get("location")),
        "department": clean_text(raw.get("department")),
        "posted": clean_text(raw.get("posted"), single_line=True),
        "employment_type": clean_text(raw.get("employment_type"), single_line=True),
        "job_id": clean_text(raw.get("job_id"), single_line=True),
        "apply_url": canonical_url(raw.get("apply_url")),
    }
    for key, value in raw.items():  # keep any extra fields a config extracted
        if key not in job:
            job[key] = value
    return {k: v for k, v in job.items() if v not in (None, "")}
