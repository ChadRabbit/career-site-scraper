"""
Company config schema. The onboarding wizard writes these as configs/<slug>.json,
and the scraper replays them without any human in the loop.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from scraper import settings
from scraper.log import get_logger

log = get_logger()

SCHEMA_VERSION = 2  # 2: recorded DOM flow only (v1 also had an "api" strategy)


class SelectorSpec(BaseModel):
    """Playwright selectors tried in order; the first one that matches wins."""

    candidates: list[str]
    fingerprint: dict = Field(default_factory=dict)  # what the element looked like at onboarding time


class FieldSpec(BaseModel):
    """How to read one field from a job card. Selectors are CSS, relative to the card."""

    selectors: list[str] = Field(default_factory=list)  # empty → the card element itself
    attr: str | None = None  # read an attribute instead of the text ("href" is resolved to an absolute URL)
    closest: bool = False  # look *up* from the card (card sits inside the matched element)


class DomConfig(BaseModel):
    card: SelectorSpec
    fields: dict[str, FieldSpec]
    apply_url_template: str | None = None  # e.g. "https://x.com/jobs/{job_id}"; filled from fields


class SearchConfig(BaseModel):
    query: str
    input: SelectorSpec | None = None
    submit: Literal["enter", "click", "none"] = "enter"
    submit_button: SelectorSpec | None = None
    results_url: str | None = None  # when the query lives in the URL: template containing {query}


class PaginationConfig(BaseModel):
    type: Literal["none", "next", "page_number", "load_more", "scroll"] = "none"
    control: SelectorSpec | None = None  # next / load-more control
    page_number_template: str | None = None  # selector containing {page}
    url_template: str | None = None  # URL seen for page 2 with a {page} placeholder; fallback if the control is gone
    max_pages: int = settings.DEFAULT_MAX_PAGES


class CompanyConfig(BaseModel):
    schema_version: int = SCHEMA_VERSION
    name: str
    slug: str
    start_url: str
    dom: DomConfig
    frame_url_contains: str | None = None  # listing lives in an iframe whose URL contains this
    popups: list[SelectorSpec] = Field(default_factory=list)  # close buttons of recorded popups (cookie banners, ...)
    search: SearchConfig | None = None
    pagination: PaginationConfig = Field(default_factory=PaginationConfig)
    onboarded_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    onboarded_job_count: int = 0
    notes: list[str] = Field(default_factory=list)


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "company"


def config_path(slug: str, config_dir: Path | None = None) -> Path:
    return (config_dir or settings.CONFIG_DIR) / f"{slug}.json"


def save_config(cfg: CompanyConfig, config_dir: Path | None = None) -> Path:
    path = config_path(cfg.slug, config_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cfg.model_dump_json(indent=2, exclude_none=True) + "\n")
    return path


def load_config(path: Path) -> CompanyConfig:
    return CompanyConfig.model_validate_json(path.read_text())


def load_configs(names: list[str] | None = None, config_dir: Path | None = None) -> list[CompanyConfig]:
    """Load every config; ones that no longer match the schema are skipped with a re-onboard hint."""
    directory = config_dir or settings.CONFIG_DIR
    wanted = {slugify(n) for n in names} if names else None
    configs = []
    for path in sorted(directory.glob("*.json")):
        if wanted and path.stem not in wanted:
            continue
        try:
            configs.append(load_config(path))
        except ValidationError:
            log.warning(f"Skipping {path.name}: written by an older version. Re-onboard it with --force.")
    return configs
