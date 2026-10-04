from scraper.onboard.url_tools import page_url_template, query_url_template, template_from_attributes
from scraper.pipeline.dedupe import deduplicate
from scraper.pipeline.normalize import canonical_url, normalize_job
from scraper.pipeline.scoring import score_job
from scraper.scrape.dom import fill_template
from scraper.scrape.search import is_plausible_query


# ── url templates ────────────────────────────────────────────────────────
def test_query_url_template():
    assert query_url_template("https://x.com/jobs?q=Software+Engineer&l=IN", "Software Engineer") == \
        "https://x.com/jobs?q={query}&l=IN"
    assert query_url_template("https://x.com/jobs/search/software-engineer", "Software Engineer") == \
        "https://x.com/jobs/search/{query}"
    assert query_url_template("https://x.com/jobs", "Software Engineer") is None


def test_page_url_template():
    assert page_url_template("https://x.com/jobs?q=a", "https://x.com/jobs?q=a&page=2") == "https://x.com/jobs?q=a&page={page}"
    assert page_url_template("https://x.com/jobs?start=0", "https://x.com/jobs?start=20") == "https://x.com/jobs?start={offset}"
    assert page_url_template("https://x.com/jobs", "https://x.com/jobs/page/2") == "https://x.com/jobs/page/{page}"
    assert page_url_template("https://x.com/jobs", "https://x.com/jobs") is None


def test_template_from_attributes_and_ids():
    attrs = [{"selectors": [], "attr": "class", "value": "posting"},
             {"selectors": [], "attr": "data-job-id", "value": "70002"}]
    template, spec = template_from_attributes("https://x.com/job.html?jobId=70002#top", attrs)
    assert template == "https://x.com/job.html?jobId={job_id}"
    assert spec == {"selectors": [], "attr": "data-job-id"}
    assert fill_template("https://x.com/{job_id}", {"job_id": "9"}) == "https://x.com/9"
    assert fill_template("https://x.com/{job_id}", {}) is None


# ── pipeline ─────────────────────────────────────────────────────────────
def test_scoring_uses_whole_words():
    assert score_job({"title": "Site Reliability Engineer (SRE)"}) > 0  # "sr" must not hit "SRE"
    assert score_job({"title": "Senior Software Engineer"}) < score_job({"title": "Software Engineer"})
    internal = score_job({"title": "Internal Tools Engineer"})
    assert internal == score_job({"title": "Tools Engineer"})  # "intern" must not hit "internal"
    assert score_job({"title": "Software Engineer", "location": "Bengaluru, India"}) > \
        score_job({"title": "Software Engineer", "location": "Berlin"})


def test_normalize_and_dedupe():
    raw = {"company": "Acme", "title": "Software Engineer\nNew", "location": "Location: Pune\nRemote",
           "apply_url": "https://x.com/jobs/1/?utm_source=li#apply"}
    job = normalize_job(raw)
    assert job["title"] == "Software Engineer"
    assert job["location"] == "Pune | Remote"
    assert job["apply_url"] == "https://x.com/jobs/1"
    assert canonical_url("/relative") == "/relative"
    other = {"company": "Acme", "title": "Other", "job_id": "9"}
    jobs = [job, dict(job), other, dict(other)]
    assert len(deduplicate(jobs)) == 2


def test_plausible_query():
    assert is_plausible_query("Software Engineer")
    assert not is_plausible_query("")
    assert not is_plausible_query("Opportunity Compatibility Emerging talent " * 100)  # page text
    assert not is_plausible_query("line one\nline two")
