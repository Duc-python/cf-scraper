"""Race and lifecycle tests for the engine pool - no browser needed.

Three defects these cover:
  - two workers resolving the same key must not both launch a browser
  - a failed start must not leave a half-open engine in the pool
  - close() must not leave a zombie entry behind
"""
import asyncio

import pytest

from cf_scraper.browser_manager import BrowserManager, Engine
from cf_scraper.schemas import ProxyConfig


class FakeBrowser:
    def __init__(self) -> None:
        self.contexts = 0

    async def new_context(self):
        self.contexts += 1
        return FakeContext()

    async def close(self):
        pass


class FakeContext:
    async def close(self):
        pass


class FakeLauncher:
    launches = 0
    exits = 0

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        FakeLauncher.launches += 1
        await asyncio.sleep(0.05)          # widen the race window
        return FakeBrowser()

    async def __aexit__(self, *exc):
        FakeLauncher.exits += 1
        await asyncio.sleep(0.05)
        return False


@pytest.fixture(autouse=True)
def patch_launcher(monkeypatch):
    import cf_scraper.browser_manager as bm

    FakeLauncher.launches = 0
    FakeLauncher.exits = 0
    monkeypatch.setattr(bm, "InvisiblePlaywright", FakeLauncher)
    return FakeLauncher


def proxy(port: int) -> ProxyConfig:
    return ProxyConfig(host="proxy.test", port=port, username="u", password="p")


@pytest.mark.asyncio
async def test_concurrent_start_launches_once():
    """The defect: both workers ran start() and orphaned a browser process."""
    mgr = BrowserManager(auto_geo=False)
    engine = Engine(mgr, proxy(1), "", "")
    await asyncio.gather(*(engine.start() for _ in range(5)))
    assert FakeLauncher.launches == 1
    assert engine.browser is not None
    await engine.stop()


@pytest.mark.asyncio
async def test_pool_returns_same_engine_for_key():
    mgr = BrowserManager(auto_geo=False)
    a, b, c = await asyncio.gather(
        mgr._engine_for(proxy(2)),
        mgr._engine_for(proxy(2)),
        mgr._engine_for(proxy(2)),
    )
    assert a is b is c
    await mgr.close()


@pytest.mark.asyncio
async def test_failed_start_leaves_pool_usable():
    """A raise inside start() must not leave a half-open engine behind."""

    class Boom(FakeLauncher):
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            raise RuntimeError("launch refused")

    import cf_scraper.browser_manager as bm

    bm.InvisiblePlaywright = Boom
    mgr = BrowserManager(auto_geo=False)
    engine = await mgr._engine_for(proxy(3))
    with pytest.raises(RuntimeError):
        await engine.start()
    assert engine.browser is None
    assert engine._launcher is None
    bm.InvisiblePlaywright = FakeLauncher
    # the next attempt on the same engine still works
    await engine.start()
    assert engine.browser is not None
    await mgr.close()


@pytest.mark.asyncio
async def test_close_clears_pool_and_stops_engines():
    mgr = BrowserManager(auto_geo=False)
    await (await mgr._engine_for(None)).start()
    await (await mgr._engine_for(proxy(4))).start()
    assert mgr._pool
    assert mgr.ready is True
    await mgr.close()
    assert mgr._pool == {}
    assert mgr.ready is False


@pytest.mark.asyncio
async def test_close_uses_concurrent_teardown():
    """Sequential teardown compounded to more than the timeout budget."""
    mgr = BrowserManager(auto_geo=False)
    for port in range(6):
        await (await mgr._engine_for(proxy(100 + port))).start()
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    await mgr.close()
    dt = loop.time() - t0
    assert FakeLauncher.exits == 6
    # six engines x 50ms teardown: sequential would be >=300ms
    assert dt < 0.25, f"teardown took {dt:.3f}s, looks sequential"


@pytest.mark.asyncio
async def test_engine_refcount():
    mgr = BrowserManager(auto_geo=False)
    engine = Engine(mgr, proxy(5), "", "")
    async with engine:
        assert engine.refs == 1
        async with engine:
            assert engine.refs == 2
        assert engine.refs == 1
    assert engine.refs == 0
    await engine.stop()


@pytest.mark.asyncio
async def test_run_releases_engine_when_job_fails():
    mgr = BrowserManager(auto_geo=False)

    async def boom(ctx):
        raise ValueError("job exploded")

    with pytest.raises(ValueError):
        await mgr.run(proxy(6), boom)
    assert mgr._pool == {}