"""Make the engine pool robust under concurrency.

Three defects found while running proxies in parallel:

1. `Engine.__aenter__` called `start()` unconditionally when the browser was
   None, so two workers picking the same engine key could both launch a
   browser and the second `__aenter__` would overwrite `_launcher`, leaking
   the first browser process. Now guarded by a per-engine lock and a
   refcount check, so a start happens once.
2. A worker killed mid-`stop()` left a half-closed engine in the pool with a
   live browser, and the next job inherited it. `stop()` now clears pool state
   before awaiting the teardown, so a failure cannot leave a zombie entry.
3. `close()` shut every engine down sequentially; with several engines each
   taking seconds to exit, the total exceeded the caller's patience. Engines
   now stop concurrently.
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
        self._lock = asyncio.Lock()
        self._closing = False
        self.refs = 0

    @property
    def key(self) -> str:
        if self.proxy is None:
            return f"direct|{self.timezone}|{self.locale}"
        auth = f"{self.proxy.username or ''}:{self.proxy.password or ''}@"
        return f"{auth}{self.proxy.host}:{self.proxy.port}|{self.timezone}|{self.locale}"

    async def start(self) -> Any:
        # One launch per engine. Concurrent workers that resolve the same key
        # must not both start a browser: the second would overwrite
        # _launcher and orphan the first process.
        async with self._lock:
            if self.browser is not None:
                return self.browser
            kwargs: dict[str, Any] = {"headless": self.mgr.headless}
            if self.proxy is not None:
                kwargs["proxy"] = proxy_config(self.proxy)
            if self.mgr.seed is not None:
                kwargs["seed"] = self.mgr.seed
            if self.mgr.quiet_canvas:
                kwargs["extra_prefs"] = {
                    "zoom.stealth.canvas.substitute_pixels": False}
            if self.timezone:
                kwargs["timezone"] = self.timezone
            if self.locale:
                kwargs["locale"] = self.locale
            launcher = InvisiblePlaywright(**kwargs)
            browser = await launcher.__aenter__()
            self._launcher = launcher
            self.browser = browser
            self._closing = False
            return browser

    async def stop(self) -> None:
        launcher, self._launcher, self.browser = self._launcher, None, None
        self._closing = True
        self.refs = 0
        if launcher is not None:
            try:
                await launcher.__aexit__(None, None, None)
            except Exception:
                pass

    async def __aenter__(self) -> Any:
        # start() takes the lock itself, so it must not be called while the
        # lock is held - asyncio.Lock is not reentrant and that deadlocks.
        browser = await self.start()
        async with self._lock:
            self.refs += 1
        return browser

    async def __aexit__(self, *exc: Any) -> None:
        self.refs = max(0, self.refs - 1)


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
        self._pool_lock = asyncio.Lock()
        self.active = 0

    async def launch(self) -> None:
        """Warm the direct-connection engine so `ready` is true."""
        engine = await self._engine_for(None)
        await engine.start()

    async def close(self) -> None:
        async with self._pool_lock:
            engines = list(self._pool.values())
            self._pool.clear()
        # Concurrent: each engine takes seconds to exit and there can be
        # several, so closing them one after another compounds.
        await asyncio.gather(*(e.stop() for e in engines), return_exceptions=True)

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

            resolved = await asyncio.gather(
                resolve_geo(proxy), return_exceptions=True
            )
            geo = resolved[0] if isinstance(resolved[0], dict) else {}
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
        async with self._pool_lock:
            # Always reuse the pooled object, even one that has not been
            # launched yet. Swapping it for a fresh Engine here handed each
            # concurrent caller its own browser to start.
            existing = self._pool.get(engine.key)
            if existing is not None and not existing._closing:
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
                async with self._pool_lock:
                    if self._pool.get(engine.key) is engine:
                        self._pool.pop(engine.key, None)
                await engine.stop()


def proxy_config(proxy: ProxyConfig) -> dict[str, Any]:
    entry: dict[str, Any] = {"server": f"http://{proxy.host}:{proxy.port}"}
    if proxy.username:
        entry["username"] = proxy.username
    if proxy.password:
        entry["password"] = proxy.password
    return entry