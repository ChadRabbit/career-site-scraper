from __future__ import annotations

import re
from pathlib import Path

from scraper.config import DomConfig
from scraper.locate import resolve

EXTRACT_JS = (Path(__file__).parent / "extract.js").read_text()

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def fill_template(template: str, row: dict) -> str | None:
    """'https://x/jobs/{job_id}' + {'job_id': '42'} → 'https://x/jobs/42' (None if a value is missing)."""
    missing = False

    def sub(m):
        nonlocal missing
        value = row.get(m.group(1))
        if value in (None, ""):
            missing = True
            return ""
        return str(value)

    url = _PLACEHOLDER.sub(sub, template)
    return None if missing else url


async def extract_cards(scope, dom: DomConfig) -> list[dict]:
    """Read every visible job card in scope (a Page or Frame) using the config's field specs."""
    cards = await resolve(scope, dom.card)
    if cards is None:
        return []
    fields = {name: spec.model_dump() for name, spec in dom.fields.items()}
    rows = await cards.evaluate_all(EXTRACT_JS, fields)
    if dom.apply_url_template:
        for row in rows:
            if not row.get("apply_url"):
                url = fill_template(dom.apply_url_template, row)
                if url:
                    row["apply_url"] = url
    return [r for r in rows if r.get("title")]


async def count_cards(scope, dom: DomConfig) -> int:
    cards = await resolve(scope, dom.card)
    return await cards.count() if cards is not None else 0
