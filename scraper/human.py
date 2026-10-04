"""
Human-ish browser interactions: eased scrolling with reading pauses, curved mouse
movement before clicks, per-character typing.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable

from scraper import settings

_AT_BOTTOM_JS = """
([x, y]) => {
  let el = document.elementFromPoint(x, y);
  while (el && el !== document.body && el !== document.documentElement) {
    const s = getComputedStyle(el);
    if (/(auto|scroll)/.test(s.overflowY) && el.scrollHeight > el.clientHeight + 4) {
      return el.scrollTop + el.clientHeight >= el.scrollHeight - 8;
    }
    el = el.parentElement;
  }
  const d = document.scrollingElement || document.documentElement;
  return d.scrollTop + window.innerHeight >= d.scrollHeight - 8;
}
"""


class Human:
    def __init__(self, page, speed: float | None = None, seed: int | None = None):
        self.page = page
        self.speed = settings.HUMAN_SPEED if speed is None else speed
        self.rng = random.Random(seed)
        self.mouse = (self.rng.uniform(200, 600), self.rng.uniform(150, 400))

    async def pause(self, lo: float, hi: float) -> None:
        if self.speed > 0:
            await asyncio.sleep(self.rng.uniform(lo, hi) * self.speed)

    async def _viewport(self) -> tuple[float, float]:
        size = self.page.viewport_size
        if size:
            return size["width"], size["height"]
        dims = await self.page.evaluate("() => [window.innerWidth, window.innerHeight]")
        return dims[0], dims[1]

    async def move_to(self, x: float, y: float) -> None:
        """Move along a quadratic Bezier curve with a slightly random control point."""
        x0, y0 = self.mouse
        cx = (x0 + x) / 2 + self.rng.uniform(-120, 120)
        cy = (y0 + y) / 2 + self.rng.uniform(-80, 80)
        steps = self.rng.randint(12, 28) if self.speed > 0 else 3
        for i in range(1, steps + 1):
            t = i / steps
            t = t * t * (3 - 2 * t)  # ease in/out
            px = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t * t * x
            py = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t * t * y
            await self.page.mouse.move(px, py)
            if self.speed > 0:
                await asyncio.sleep(self.rng.uniform(0.004, 0.018) * self.speed)
        self.mouse = (x, y)

    async def click(self, locator) -> None:
        """Scroll the element into view, glide the mouse over it, then click."""
        await locator.scroll_into_view_if_needed(timeout=10_000)
        await self.pause(0.3, 0.9)
        box = await locator.bounding_box()
        if not box or box["width"] < 1 or box["height"] < 1:
            await locator.click()
            return
        x = box["x"] + box["width"] * self.rng.uniform(0.3, 0.7)
        y = box["y"] + box["height"] * self.rng.uniform(0.3, 0.7)
        await self.move_to(x, y)
        await self.pause(0.08, 0.35)
        try:
            # trial run first: raises if something (cookie banner, overlay) covers the element
            await locator.click(trial=True, timeout=3_000)
            await self.page.mouse.click(x, y)
        except Exception:
            await locator.click(timeout=10_000)

    async def type(self, locator, text: str) -> None:
        await self.click(locator)
        await locator.fill("")
        for ch in text:
            await self.page.keyboard.type(ch)
            if self.speed > 0:
                await asyncio.sleep(self.rng.uniform(0.05, 0.2) * self.speed)

    async def scroll_page(
        self,
        on_step: Callable[[], Awaitable[None]] | None = None,
        max_steps: int = 40,
        anchor: tuple[float, float] | None = None,
    ) -> int:
        """
        Read-and-scroll down until the bottom (of the page, or of the scroll container
        under the mouse). Calls on_step after every scroll so virtualised lists can be
        harvested while they are on screen. Returns the number of steps taken.
        """
        width, height = await self._viewport()
        ax, ay = anchor or (width * self.rng.uniform(0.35, 0.6), height * self.rng.uniform(0.4, 0.6))
        await self.move_to(ax, ay)
        if on_step:
            await on_step()

        bottom_hits = 0
        for step in range(1, max_steps + 1):
            if self.rng.random() < 0.08 and step > 2:
                await self.page.mouse.wheel(0, -self.rng.randint(120, 300))  # glance back up
                await self.pause(0.4, 1.0)
            distance = self.rng.randint(300, 700)
            chunks = self.rng.randint(3, 6)
            for _ in range(chunks):
                await self.page.mouse.wheel(0, distance / chunks)
                if self.speed > 0:
                    await asyncio.sleep(self.rng.uniform(0.02, 0.06) * self.speed)
            await self.pause(0.5, 1.8)
            if on_step:
                await on_step()
            try:
                at_bottom = await self.page.evaluate(_AT_BOTTOM_JS, [ax, ay])
            except Exception:
                at_bottom = True
            if at_bottom:
                bottom_hits += 1
                if bottom_hits >= 2:  # second hit: lazy loading had a chance to extend the page
                    return step
                await self.pause(0.8, 1.6)
            else:
                bottom_hits = 0
        return max_steps
