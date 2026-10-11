"""Owns the anti-detect engine pool.

The engine fixes its fingerprint when it starts - timezone, locale and the
WebRTC candidate are all decided there. Setting a proxy per-context
afterwards therefore leaves both on the host: measured, a context-level
proxy gave tz=Asia/Bangkok and a WebRTC candidate of the host's real public
IP, while the same proxy passed at launch gave tz=Asia/Hong_Kong and the
proxy's own IP as the candidate. A leaked WebRTC candidate and a timezone
that disagrees with the exit IP are both cheap cross-checks for a detector.

So: one engine per proxy, launched with that proxy. Engines are pooled and
reused, keyed by proxy, with a refcount so the last job closes them.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Optional

from invisible_playwright.async_api import InvisiblePlaywright

from . import config
from .jobs._common import JobError, set_deadline
from .schemas import ProxyConfig


class BrowserFull(Exception):
    """Raised when active contexts reach browserLimit (HTTP 429)."""


class Engine:
    """One browser process + the proxy it was launched with."""

    def __init__(self, manager: "BrowserManager", proxy: Optional[ProxyConfig],
                 timezone: str, locale: str) -> None:
        self.mgr = manager
        self.proxy = proxy
        self.timezone = timezone
        self.locale = locale
        self.browser: Any = None
        self._launcher: InvisiblePlaywright | None = None
        self.refs = 0

    @property
    def key(self) -> str:
        if self.proxy is None:
            return f"direct|{self.timezone}|{self.locale}"
        auth = f"{self.proxy.username or ''}:{self.proxy.password or ''}@"
        return f"{auth}{self.proxy.host}:{self.proxy.port}|{self.timezone}|{self.locale}"

    async def start(self) -> Any:
        kwargs: dict[str, Any] = {"headless": self.mgr.headless}
        if self.proxy is not None:
            kwargs["proxy"] = proxy_config(self.proxy)
        if self.mgr.seed is not None:
            kwargs["seed"] = self.mgr.seed
        if self.mgr.quiet_canvas:
            kwargs["extra_prefs"] = {"zoom.stealth.canvas.substitute_pixels": False}
        if self.timezone:
            kwargs["timezone"] = self.timezone
        if self.locale:
            kwargs["locale"] = self.locale
        self._launcher = InvisiblePlaywright(**kwargs)
        self.browser = await self._launcher.__aenter__()
        return self.browser

    async def stop(self) -> None:
        launcher, self._launcher, self.browser = self._launcher, None, None
        if launcher is not None:
            try:
                await launcher.__aexit__(None, None, None)
            except Exception:
                pass

    async def __aenter__(self) -> Any:
        if self.browser is None:
            await self.start()
        self.refs += 1
        return self.browser

    async def __aexit__(self, *exc: Any) -> None:
        self.refs -= 1


class BrowserManager:
    def __init__(
        self,
        *,
        limit: int = 20,
        timeout_ms: int = 60000,
        headless: bool = True,
        seed: Optional[int] = None,
        quiet_canvas: bool = True,
        timezone: str = "",
        locale: str = "",
        auto_geo: bool = True,
    ) -> None:
        self.limit = limit
        self.timeout_s = timeout_ms / 1000.0
        self.headless = headless
        self.seed = config.SEED if seed is None else seed
        self.quiet_canvas = quiet_canvas
        self.timezone = timezone
        self.locale = locale
        self.auto_geo = auto_geo
        self._pool: dict[str, Engine] = {}
        self._geo_cache: dict[str, dict] = {}
        self.active = 0

    async def launch(self) -> None:
        """Warm the direct-connection engine so `ready` is true."""
        engine = self._pool.get(Engine(self, None, self.timezone, self.locale).key)
        if engine is None:
            engine = Engine(self, None, self.timezone, self.locale)
            self._pool[engine.key] = engine
        await engine.start()

    async def close(self) -> None:
        for engine in list(self._pool.values()):
            await engine.stop()
        self._pool.clear()

    @property
    def ready(self) -> bool:
        return any(e.browser is not None for e in self._pool.values())

    def acquire(self) -> None:
        """Synchronous check-and-increment: atomic on the event loop."""
        if self.active >= self.limit:
            raise BrowserFull()
        self.active += 1

    def release(self) -> None:
        self.active = max(0, self.active - 1)

    async def _geo(self, proxy: ProxyConfig) -> dict:
        cache_key = f"{proxy.host}:{proxy.port}"
        geo = self._geo_cache.get(cache_key)
        if geo is None:
            from .geo import resolve_geo
            geo = await resolve_geo(proxy)
            self._geo_cache[cache_key] = geo
        return geo

    async def _engine_for(self, proxy: Optional[ProxyConfig]) -> Engine:
        timezone, locale = self.timezone, self.locale
        if proxy is not None and self.auto_geo and not timezone:
            geo = await self._geo(proxy)
            timezone = geo.get("timezone") or ""
            if not locale:
                locale = geo.get("locale") or ""
        engine = Engine(self, proxy, timezone, locale)
        existing = self._pool.get(engine.key)
        if existing is not None:
            return existing
        self._pool[engine.key] = engine
        return engine

    async def new_context(self, proxy: Optional[ProxyConfig] = None) -> Any:
        engine = await self._engine_for(proxy)
        try:
            async with engine:
                return await engine.browser.new_context()
        except Exception:
            raise JobError("Failed to create browser context")

    async def run(
        self, proxy: Optional[ProxyConfig], job: Callable[[Any], Awaitable[Any]]
    ) -> Any:
        """Run one job in a fresh context on a proxy-matched engine."""
        engine = await self._engine_for(proxy)
        context = None
        try:
            async with engine:
                try:
                    context = await engine.browser.new_context()
                except Exception:
                    raise JobError("Failed to create browser context")
                try:
                    reset_deadline = set_deadline(time.monotonic() + self.timeout_s)
                    try:
                        return await asyncio.wait_for(job(context), timeout=self.timeout_s)
                    except asyncio.TimeoutError:
                        raise JobError("Timeout Error")
                    except asyncio.CancelledError:
                        # an inner wait_for re-raises CancelledError, not TimeoutError
                        raise JobError("Timeout Error")
                finally:
                    reset_deadline()
        finally:
            if context is not None:
                try:
                    await asyncio.shield(asyncio.wait_for(context.close(), timeout=15))
                except Exception:
                    pass
            if engine.proxy is not None and engine.refs <= 0:
                # An idle proxy engine is dropped so a later job with a
                # different proxy cannot inherit a stale fingerprint. The
                # direct engine is kept: it is the one `ready` reports on,
                # and tearing it down would make the API look unavailable.
                self._pool.pop(engine.key, None)
                await engine.stop()


def proxy_config(proxy: ProxyConfig) -> dict[str, Any]:
    entry: dict[str, Any] = {"server": f"http://{proxy.host}:{proxy.port}"}
    if proxy.username:
        entry["username"] = proxy.username
    if proxy.password:
        entry["password"] = proxy.password
    return entry