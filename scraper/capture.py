"""
Records network traffic to disk, for debugging a site after the fact:

    <out_dir>/index.jsonl     one line per response (url, method, status, headers, post data, body file)
    <out_dir>/bodies/         response bodies (json/html/js/...)
    <out_dir>/screenshots/    see screenshot()
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from pathlib import Path
from typing import Any

from scraper import settings
from scraper.log import get_logger

log = get_logger()

_EXTENSIONS = {
    "json": ".json",
    "html": ".html",
    "javascript": ".js",
    "css": ".css",
    "xml": ".xml",
    "text/plain": ".txt",
}


def _extension(content_type: str) -> str:
    for needle, ext in _EXTENSIONS.items():
        if needle in content_type:
            return ext
    return ".bin"


class NetworkRecorder:
    """
    mode="all":  store bodies of everything except images/media/fonts (onboarding)
    mode="data": store bodies of xhr/fetch/document only (lighter, for routine scrapes)
    """

    def __init__(self, out_dir: Path, mode: str = "all"):
        self.bodies_dir = out_dir / "bodies"
        self.bodies_dir.mkdir(parents=True, exist_ok=True)
        self.mode = mode
        self._index = (out_dir / "index.jsonl").open("a")
        self._tasks: set[asyncio.Task] = set()
        self._counter = 0
        self._targets: list = []
        self._closed = False

    def attach(self, target) -> NetworkRecorder:
        """target: a BrowserContext (all pages, popups and iframes) or a single Page."""
        target.on("response", self._on_response)
        self._targets.append(target)
        return self

    async def flush(self, timeout: float = 10) -> None:
        """Wait for in-flight body saves, but never forever (streaming / long-poll responses never finish)."""
        if self._tasks:
            await asyncio.wait(list(self._tasks), timeout=timeout)
        if not self._index.closed:
            self._index.flush()

    async def close(self, timeout: float = 10) -> None:
        for target in self._targets:
            with contextlib.suppress(Exception):
                target.remove_listener("response", self._on_response)
        self._targets.clear()
        await self.flush(timeout)
        self._closed = True
        self._index.close()

    def _on_response(self, response) -> None:
        if self._closed:
            return
        task = asyncio.ensure_future(self._record(response))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _record(self, response) -> None:
        self._counter += 1
        rid = self._counter
        request = response.request
        resource_type = request.resource_type
        headers = response.headers
        content_type = headers.get("content-type", "")
        try:
            post_data = request.post_data
        except Exception:  # binary post bodies can't be decoded as text
            post_data = None

        entry: dict[str, Any] = {
            "id": rid,
            "ts": time.time(),
            "url": response.url,
            "method": request.method,
            "status": response.status,
            "resource_type": resource_type,
            "content_type": content_type,
            "request_headers": request.headers,
            "response_headers": headers,
            "post_data": post_data,
            "frame_url": _safe_frame_url(response),
        }

        wants_body = resource_type not in settings.CAPTURE_SKIP_BODY_TYPES and (
            self.mode == "all" or resource_type in ("xhr", "fetch", "document")
        )
        if wants_body and not (300 <= response.status < 400):
            try:
                body = await response.body()
            except Exception as e:  # navigation aborted, body evicted, ...
                entry["body_error"] = str(e)[:200]
                body = None
            if body is not None:
                entry["body_bytes"] = len(body)
                if len(body) <= settings.CAPTURE_MAX_BODY_BYTES:
                    name = f"{rid:05d}{_extension(content_type)}"
                    (self.bodies_dir / name).write_bytes(body)
                    entry["body_file"] = f"bodies/{name}"
                else:
                    entry["body_skipped"] = "too large"

        if not self._closed:
            self._index.write(json.dumps(entry, default=str) + "\n")


def _safe_frame_url(response) -> str | None:
    try:
        return response.frame.url
    except Exception:
        return None


async def screenshot(page, out_dir: Path, name: str) -> Path | None:
    """Viewport screenshot for the run record; never fails the run."""
    path = out_dir / "screenshots" / f"{time.strftime('%H%M%S')}_{name}.png"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(path))
        return path
    except Exception as e:
        log.debug(f"screenshot failed: {e}")
        return None
