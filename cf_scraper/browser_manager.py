"""Owns the single shared anti-detect browser.

Mirrors the Node original: one browser for the process (global.browser),
one isolated context per request, a counter capped by browserLimit.
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Optional

from invisible_playwright.async_api import InvisiblePlaywright

from . import config
from .jobs._common import JobError
from .schemas import ProxyConfig


class BrowserFull(Exception):
    """Raised when active contexts reach browserLimit (HTTP 429)."""


class BrowserManager:
    def __init__(
        self,
        *,
        limit: int = 20,
        timeout_ms: int = 60000,
        headless: bool = True,
        seed: Optional[int] = None,
        quiet_canvas: bool = True,
    ) -> None:
        self.limit = limit
        self.timeout_s = timeout_ms / 1000.0
        self._headless = headless
        self._seed = config.SEED if seed is None else seed
        self._quiet_canvas = quiet_canvas
        self._launcher: InvisiblePlaywright | None = None
        self._browser: Any = None
        self.active = 0

    async def launch(self) -> None:
        kwargs: dict[str, Any] = {"headless": self._headless}
        if self._seed is not None:
            kwargs["seed"] = self._seed
        if self._quiet_canvas:
            kwargs["extra_prefs"] = {"zoom.stealth.canvas.substitute_pixels": False}
        self._launcher = InvisiblePlaywright(**kwargs)
        self._browser = await self._launcher.__aenter__()

    async def close(self) -> None:
        launcher, browser = self._launcher, self._browser
        self._launcher = None
        self._browser = None
        if launcher is not None:
            await launcher.__aexit__(None, None, None)
        elif browser is not None:  # pragma: no cover - defensive
            await browser.close()

    @property
    def ready(self) -> bool:
        return self._browser is not None

    def acquire(self) -> None:
        """Synchronous check-and-increment: atomic on the event loop."""
        if self.active >= self.limit:
            raise BrowserFull()
        self.active += 1

    def release(self) -> None:
        self.active = max(0, self.active - 1)

    @staticmethod
    def proxy_args(proxy: Optional[ProxyConfig]) -> dict[str, Any]:
        if proxy is None:
            return {}
        entry: dict[str, Any] = {"server": f"http://{proxy.host}:{proxy.port}"}
        if proxy.username:
            entry["username"] = proxy.username
        if proxy.password:
            entry["password"] = proxy.password
        return {"proxy": entry}

    async def new_context(self, proxy: Optional[ProxyConfig] = None) -> Any:
        try:
            return await self._browser.new_context(**self.proxy_args(proxy))
        except Exception:
            raise JobError("Failed to create browser context")

    async def run(
        self, proxy: Optional[ProxyConfig], job: Callable[[Any], Awaitable[Any]]
    ) -> Any:
        """Run one job in a fresh context, bounded by the global timeout."""
        context = await self.new_context(proxy)
        try:
            return await asyncio.wait_for(job(context), timeout=self.timeout_s)
        except asyncio.TimeoutError:
            raise JobError("Timeout Error")
        finally:
            await context.close()
