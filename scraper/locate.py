from __future__ import annotations

from collections.abc import Iterable

from scraper.config import SelectorSpec


async def resolve(scope, spec: SelectorSpec | Iterable[str] | None, min_count: int = 1):
    """Return a Locator for the first candidate selector that matches at least min_count elements."""
    if spec is None:
        return None
    candidates = spec.candidates if isinstance(spec, SelectorSpec) else list(spec)
    for selector in candidates:
        try:
            locator = scope.locator(selector)
            if await locator.count() >= min_count:
                return locator
        except Exception:  # invalid selector for this engine, detached frame, ...
            continue
    return None


def find_frame(page, frame_url_contains: str | None):
    """The frame holding the job list (main frame unless the listing is embedded in an iframe)."""
    if not frame_url_contains:
        return page.main_frame
    for frame in page.frames:
        if frame_url_contains in frame.url:
            return frame
    return page.main_frame
