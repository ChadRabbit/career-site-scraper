"""Python ⇄ page channel for the onboarding overlay (see picker.js)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from pathlib import Path

from scraper.log import get_logger

log = get_logger()

PICKER_JS = (Path(__file__).parent / "picker.js").read_text()


class OnboardingAborted(Exception):
    """The user closed the browser window mid-way."""


def button(id: str, label: str, primary: bool = False) -> dict:
    return {"id": id, "label": label, "primary": primary}


class Bridge:
    def __init__(self):
        self.state: dict = {"step": None, "mode": "off", "title": "", "message": "", "buttons": [],
                            "preview": None, "status": ""}
        self.events: asyncio.Queue = asyncio.Queue()
        self.page = None
        # "Record popup" works at any step, independently of what the wizard is waiting for
        self.popup_recording = False
        self.popups: list[dict] = []  # descriptors of recorded close buttons

    async def install(self, context) -> None:
        await context.expose_binding("__onboardEvent", self._on_event)
        await context.expose_binding("__onboardHello", lambda source: self._page_state())
        await context.add_init_script(script=PICKER_JS)

    def _page_state(self) -> dict:
        return {**self.state, "popupRecording": self.popup_recording, "popupCount": len(self.popups)}

    def watch(self, page) -> None:
        self.page = page
        page.on("close", lambda _: self.events.put_nowait({"type": "closed"}))

    def _on_event(self, source, payload) -> None:
        event = dict(payload or {})
        kind = event.get("type")
        if kind in ("record_popup", "cancel_popup"):
            self.popup_recording = kind == "record_popup"
            if self.popup_recording:
                log.info("[onboard] Recording a popup: click its close button")
            asyncio.ensure_future(self.broadcast())
            return
        if kind == "popup":
            self.popup_recording = False
            self.popups.append(event.get("descriptor") or {})
            log.info(f"[onboard] Popup recorded: {(event.get('descriptor') or {}).get('text', '')[:40]!r}")
            asyncio.ensure_future(self.broadcast())
            return
        event["_frame"] = source.get("frame")
        self.events.put_nowait(event)

    async def show(self, *, title: str | None = None, message: str = "", step: str | None = None,
                   mode: str = "off", buttons: Iterable[dict] = (), preview: list | None = None,
                   status: str = "") -> None:
        self.state = {
            "step": step or self.state.get("step") or "info",
            "mode": mode,
            "title": title if title is not None else self.state.get("title", ""),
            "message": message,
            "buttons": list(buttons),
            "preview": preview,
            "status": status,
        }
        if message:
            log.info(f"[onboard] {self.state['title']}: {message}" + (f"  ({status})" if status else ""))
        await self.broadcast()

    async def broadcast(self) -> None:
        if self.page is None or self.page.is_closed():
            return
        state = self._page_state()
        for frame in self.page.frames:
            try:
                await frame.evaluate("s => window.__onboard && window.__onboard.setState(s)", state)
            except Exception:  # frame navigating / detached
                pass

    async def next_event(self, types: set[str], step: str | None = None, timeout: float | None = None) -> dict:
        """Wait for the next event of the given types (picks/clicks are filtered by step)."""
        while True:
            event = await asyncio.wait_for(self.events.get(), timeout)
            if event["type"] == "closed":
                raise OnboardingAborted("browser window was closed")
            if event["type"] not in types:
                continue
            if step and event["type"] != "button" and event.get("step") != step:
                continue
            return event

    async def wait_button(self, ids: set[str], timeout: float | None = None) -> str:
        while True:
            event = await self.next_event({"button"}, timeout=timeout)
            if event.get("id") in ids:
                return event["id"]
