import json
import zipfile

from scraper.browser import open_browser
from scraper.capture import NetworkRecorder
from scraper.pipeline.export import read_jobs, write_jobs


async def test_har_and_indexed_capture(site, tmp_path):
    har = tmp_path / "net.har.zip"
    async with open_browser(user_data_dir=tmp_path / "profile", headless=True, har_path=har) as context:
        recorder = NetworkRecorder(tmp_path / "cap").attach(context)
        page = await context.new_page()
        await page.goto(f"{site}/api/index.html")
        await page.wait_for_selector(".card")
        await recorder.close()

    entries = [json.loads(line) for line in (tmp_path / "cap" / "index.jsonl").read_text().splitlines()]
    api = next(e for e in entries if "/api/jobs" in e["url"])
    assert api["status"] == 200 and api["resource_type"] == "fetch"
    body = json.loads((tmp_path / "cap" / api["body_file"]).read_text())
    assert len(body["data"]["results"]) == 10

    with zipfile.ZipFile(har) as z:
        log = json.loads(z.read("har.har"))["log"]
    assert any("/api/jobs" in e["request"]["url"] for e in log["entries"])


def test_excel_round_trip(tmp_path):
    jobs = [{"company": "Acme", "title": "Engineer\x07", "score": 10, "apply_url": "https://x.com/1", "custom": "x"}]
    path = write_jobs(tmp_path / "out.xlsx", jobs)
    back = read_jobs(path)
    assert back == [{"company": "Acme", "title": "Engineer", "score": 10, "apply_url": "https://x.com/1"}]


async def test_flush_never_hangs_on_endless_responses(tmp_path):
    import asyncio
    import time

    recorder = NetworkRecorder(tmp_path / "cap")
    endless = asyncio.ensure_future(asyncio.sleep(3600))  # stands in for a streaming / long-poll body
    recorder._tasks.add(endless)
    start = time.monotonic()
    await recorder.flush(timeout=0.5)
    await recorder.close(timeout=0.5)
    assert time.monotonic() - start < 3
    endless.cancel()
