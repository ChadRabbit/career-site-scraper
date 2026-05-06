from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PaginationConfig:
    """
    Controls how the scraper loads more results.

    type options:
      "click"        – click a button/link repeatedly (show-more or next-page)
      "scroll"       – keep scrolling down until no new content appears
      "page_number"  – click numbered page links (like Snowflake)
      "none"         – single-page, no action needed
    """
    type: str = "none"  # "click" | "scroll" | "page_number" | "none"

    # ── for type="click" ──────────────────────────────────────
    click_selectors: list[str] = field(default_factory=list)
    max_clicks: int = 5  # safety cap

    # ── for type="scroll" ────────────────────────────────────
    scroll_step_px: int = 4000
    scroll_rounds: int = 5  # how many wheel events per page
    scroll_pause_ms: int = 2000

    # ── for type="page_number" ───────────────────────────────
    page_number_selector_template: str = ""  # e.g. "[data-ph-at-text='{page}']"
    max_pages: int = 5
    page_load_wait_ms: int = 10000  # wait after each page navigation


@dataclass
class SearchConfig:
    selector: str  # CSS selector for input
    query: str = "Software Engineer"
    press_enter: bool = True
    type_delay_ms: int = 50
    wait_after_ms: int = 4000


@dataclass
class FieldMapping:
    """Maps a job dict key to one or more possible source keys in the raw payload."""
    title: list[str] = field(default_factory=lambda: ["title"])
    location: list[str] = field(default_factory=lambda: ["location", "locations", "primaryLocation"])
    job_id: list[str] = field(default_factory=lambda: ["id", "jobId", "req_id"])
    apply_url: list[str] = field(default_factory=lambda: ["applyUrl", "url", "jobUrl", "absolute_url"])
    department: list[str] = field(default_factory=lambda: ["department", "category", "categories"])


@dataclass
class ApiConfig:
    """Config for API-intercept strategy."""
    url_pattern: str  # substring to match in response URL
    data_path: list[str] = field(default_factory=list)
    # e.g. ["data", "results"] means data["data"]["results"]
    # leave empty if the root payload IS the list
    field_mapping: FieldMapping = field(default_factory=FieldMapping)
    content_type_filter: str = "application/json"


@dataclass
class DomConfig:
    """Config for DOM-parsing strategy."""
    job_card_selector: str  # locator for each job card
    fields: dict[str, str] = field(default_factory=dict)
    # key   = field name (title, location, apply_url, …)
    # value = CSS selector RELATIVE to each card; prefix "attr:ATTRNAME:" to get an attribute
    # e.g. {"title": "a.job-link", "location": ".job-location",
    #        "apply_url": "attr:href:a.job-link", "job_id": "attr:data-id:a.job-link"}
    base_url: str = ""  # prepended to relative hrefs when needed


@dataclass
class CompanyConfig:
    name: str
    url: str
    strategy: str  # "api" | "dom"
    api: Optional[ApiConfig] = None
    dom: Optional[DomConfig] = None
    pagination: PaginationConfig = field(default_factory=PaginationConfig)
    initial_wait_ms: int = 3000  # wait after page load before scraping
    search: Optional[SearchConfig] = None


COMPANY_CONFIGS: list[CompanyConfig] = [

    CompanyConfig(
        name="Uber",
        url="https://www.uber.com/careers/list/",
        strategy="api",
        initial_wait_ms=2000,
        api=ApiConfig(
            url_pattern="loadSearchJobsResults",
            data_path=["data", "results"],
            field_mapping=FieldMapping(
                title=["title"],
                location=["location"],
                job_id=["id"],
            ),
        ),
        pagination=PaginationConfig(
            type="click",
            click_selectors=[
                "button:has-text('Show more')",
                "button:has-text('Load more')",
                "[data-testid='load-more']",
            ],
            max_clicks=20,
        ),
        search=SearchConfig(
            selector="input[placeholder='Search Jobs']"
        ),
    ),

    CompanyConfig(
        name="Atlassian",
        url="https://www.atlassian.com/company/careers/all-jobs",
        strategy="api",
        initial_wait_ms=7000,
        api=ApiConfig(
            url_pattern="listings",
            data_path=[],  # root payload is the list
            field_mapping=FieldMapping(
                title=["title"],
                location=["locations"],
                job_id=["id"],
                apply_url=["applyUrl"],
            ),
        ),
        pagination=PaginationConfig(
            type="click",
            click_selectors=["button:has-text('Show more')", "button:has-text('Load more')"],
            max_clicks=5,
        ),
    ),

    CompanyConfig(
        name="Rippling",
        url="https://www.rippling.com/en-GB/careers/open-roles",
        strategy="api",
        initial_wait_ms=3000,
        api=ApiConfig(
            url_pattern="open-roles.json",
            data_path=["pageProps", "jobs", "items"],
            field_mapping=FieldMapping(
                title=["name"],
                location=["locations"],  # special-cased below (list of dicts)
                job_id=["id"],
                apply_url=["url"],
                department=["department"],
            ),
        ),
    ),

    CompanyConfig(
        name="Snowflake",
        url="https://careers.snowflake.com/us/en",
        strategy="dom",
        initial_wait_ms=6000,
        dom=DomConfig(
            job_card_selector="[data-ph-at-id='jobs-list-item']",
            fields={
                "title": "a[data-ph-at-id='job-link']",
                "apply_url": "attr:href:a[data-ph-at-id='job-link']",
                "job_id": "attr:data-ph-at-job-id-text:a[data-ph-at-id='job-link']",
                "location": ".job-location",
                "department": ".category",
            },
        ),
        pagination=PaginationConfig(
            type="page_number",
            page_number_selector_template="[data-ph-at-id='pagination-page-number-link'][data-ph-at-text='{page}']",
            max_pages=2,
            page_load_wait_ms=2000,
            scroll_step_px=4000,
            scroll_rounds=2,
            scroll_pause_ms=1000,
        ),
        search=SearchConfig(
            selector="[data-ph-at-id='globalsearch-input']"
        ),
    ),

    CompanyConfig(
        name="Stripe",
        url="https://stripe.com/jobs/search",
        strategy="dom",
        initial_wait_ms=3000,
        dom=DomConfig(
            job_card_selector="tr.TableRow",
            fields={
                "title": "a.JobsListings__link",
                "apply_url": "attr:href:a.JobsListings__link",
                "location": "span.JobsListings__locationDisplayName",
                "department": "li.JobsListings__departmentsListItem",
            },
        ),
        pagination=PaginationConfig(
            type="page_number",
            page_number_selector_template="a.JobsPagination__link:has-text('{page}')",
            max_pages=5,
            page_load_wait_ms=2000,
            scroll_step_px=4000,
            scroll_rounds=4,
            scroll_pause_ms=1000,
        ),
        search=SearchConfig(
            selector="input[name='jobsQueryInput']"
        ),
    ),

    CompanyConfig(
        name="Rubrik",
        url="https://www.rubrik.com/company/careers/departments/engineering",
        strategy="dom",
        initial_wait_ms=3000,
        dom=DomConfig(
            job_card_selector="div.careers_section_listing_job_item",
            base_url="https://www.rubrik.com",
            fields={
                "title": ".careers_section_listing_job_item_title",
                "apply_url": "attr:href:a.careers_section_listing_job_item_anchor",
                # location lives on the parent section — handled via special grouping below
            },
        ),
    ),

    CompanyConfig(
        name="Cohesity",
        url="https://www.cohesity.com/careers/open-positions/",
        strategy="api",
        initial_wait_ms=6000,
        api=ApiConfig(
            url_pattern="open-positions",
            content_type_filter="application/json",
            data_path=["job_data", "Engineering"],
            field_mapping=FieldMapping(
                title=["title"],
                location=["primaryLocation"],
                job_id=["req_id"],
                apply_url=["jobUrl"],
                department=["categories"],
            ),
        ),
        search=SearchConfig(
            selector="#hero-search-text-box"
        ),
    ),

    CompanyConfig(
        name="Databricks",
        url="https://www.databricks.com/company/careers/open-positions",
        strategy="api",
        initial_wait_ms=6000,
        api=ApiConfig(
            url_pattern="page-data",
            content_type_filter="application/json",
            data_path=["result", "pageContext", "data", "allGreenhouseJob", "nodes"],
            field_mapping=FieldMapping(
                title=["title"],
                location=["location"],  # special-cased: location is a dict with "name"
                job_id=["id"],
                apply_url=["absolute_url"],
                department=["departments"],  # special-cased: list of dicts
            ),
        ),
    ),
    CompanyConfig(
        name="Airbnb",
        url="https://careers.airbnb.com/positions/",
        strategy="dom",
        initial_wait_ms=3000,
        dom=DomConfig(
            job_card_selector="li[role='listitem']",  # li with attribute role with value 'listitem'
            fields={
                "title": "span.text-size-4 a",
                "apply_url": "attr:href:span.text-size-4 a",
                "location": "div.justify-end span",
                "department": "div.flex span:first-child",
            },
        ),
        pagination=PaginationConfig(
            type="page_number",
            page_number_selector_template="a.facetwp-page:has-text('{page}')",
            max_pages=5,
            page_load_wait_ms=2000,
            scroll_step_px=4000,
            scroll_rounds=4,
            scroll_pause_ms=1000,
        ),
        search=SearchConfig(
            selector="input.facetwp-search"
        ),
    ),
    CompanyConfig(
        name="Google",
        url="https://www.google.com/about/careers/applications/jobs/results",
        strategy="dom",
        initial_wait_ms=8000,

        dom=DomConfig(
            job_card_selector="div.sMn82b",
            base_url="https://www.google.com/about/careers/applications",

            fields={
                # Title
                "title": "h3.QJPWVe",

                # Apply URL (Learn more link)
                "apply_url": "attr:href:a[jsname='hSRGPd']",

                # Location
                "location": "span.r0wTof",

                # Department (hardcode since always Google)
                "department": "span.RP7SMd span"
            },
        ),

        search=SearchConfig(
            selector="input[placeholder*='Software']",
            query="Software Engineer"
        ),

        pagination=PaginationConfig(
            type="page_number",
            page_number_selector_template=
            "a[aria-label='Go to next page']",
            max_clicks=5,
            max_pages=5,
            page_load_wait_ms=2000,
            scroll_step_px=4000,
            scroll_rounds=2,
            scroll_pause_ms=1000,
        ),
    )
]
