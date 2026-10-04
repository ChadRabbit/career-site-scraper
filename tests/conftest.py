import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from scraper.log import setup_logger

setup_logger(to_file=False)  # wizard/scraper logs show up in pytest's captured output on failure

from scraper import settings  # noqa: E402

settings.POPUP_CHECK_INTERVAL_S = 0.5

SITE_DIR = Path(__file__).parent / "fixtures" / "site"

API_JOBS = [
    {
        "id": 5001 + i,
        "title": title,
        "location": {"city": city, "countryName": country},
        "department": dept,
        "url": f"/api/job.html?id={5001 + i}",
    }
    for i, (title, city, country, dept) in enumerate(
        [
            ("Software Engineer", "Pune", "India", "Engineering"),
            ("Backend Engineer", "Bengaluru", "India", "Engineering"),
            ("Product Manager", "Berlin", "Germany", "Product"),
            ("Frontend Developer", "Austin", "United States", "Engineering"),
            ("Data Scientist", "Pune", "India", "Data"),
        ]
        * 6
    )
]


class FixtureHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/jobs":
            page = int(parse_qs(parsed.query).get("page", ["1"])[0])
            body = json.dumps({"data": {"results": API_JOBS[(page - 1) * 10 : page * 10], "total": len(API_JOBS)}})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body.encode())
            return
        super().do_GET()

    def log_message(self, *args):  # keep test output quiet
        pass


@pytest.fixture(scope="session")
def site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(FixtureHandler, directory=str(SITE_DIR)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture
async def browser_context(tmp_path):
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            str(tmp_path / "profile"), headless=True, viewport={"width": 1280, "height": 900}
        )
        context.set_default_timeout(15_000)
        yield context
        await context.close()
