"""Cloudflare checkbox solver.

The Node original passes `turnstile: true` to puppeteer-real-browser, which
clicks the "Verify you are human" checkbox for you. invisible_playwright does
not auto-click anything, so this module does that step explicitly, with the
humanized mouse path the engine provides.

The widget iframe lives in a closed shadow root (invisible to page JS), but
the protocol-level frame list still exposes it, so no fingerprinting or DOM
tricks are needed: find the frame, read its box, click the checkbox square.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

WIDGET_HOST = "challenges.cloudflare.com"
_CHECKBOX_OFFSET_X = 28.0


async def has_clearance(context: Any) -> bool:
    try:
        return any(cookie.get("name") == "cf_clearance" for cookie in await context.cookies())
    except Exception:
        return False


async def _widget_box(page: Any) -> Optional[dict[str, float]]:
    for frame in page.frames:
        try:
            url = frame.url or ""
        except Exception:
            continue
        if WIDGET_HOST not in url:
            continue
        try:
            element = await frame.frame_element()
            try:
                await element.scroll_into_view_if_needed()
            except Exception:
                pass
            box = await element.bounding_box()
        except Exception:
            continue
        if box and box.get("width", 0) >= 50:
            return box
    return None


async def click_checkbox(page: Any) -> bool:
    """Click the checkbox square. Returns False when there is no widget."""
    box = await _widget_box(page)
    if not box:
        return False
    x = box["x"] + _CHECKBOX_OFFSET_X
    y = box["y"] + box["height"] / 2
    try:
        await page.mouse.click(x, y)
    except Exception:
        return False
    return True


async def click_until_clearance(page: Any, context: Any, budget_s: float = 20,
                                 reserve_s: float = 12) -> bool:
    """Best-effort solve: click, poll the cf_clearance cookie, repeat.

    The budget is capped by whatever the job deadline still allows, leaving
    `reserve_s` for the steps that follow (gate wait, load, settle reads).
    """
    from ._common import remaining_s

    budget_s = max(2.0, min(budget_s, remaining_s(reserve_s) - 2))
    if await has_clearance(context):
        return True
    loop = asyncio.get_running_loop()
    deadline = loop.time() + budget_s
    while loop.time() < deadline:
        await click_checkbox(page)
        await asyncio.sleep(2)
        if await has_clearance(context):
            return True
    return await has_clearance(context)


async def has_token_input(page: Any) -> bool:
    try:
        return bool(
            await page.evaluate("() => !!document.querySelector('[name=\"cf-response\"]')")
        )
    except Exception:
        return False


async def attempt_widget_clicks(page: Any, budget_s: float = 8) -> bool:
    """Click the widget until the token field appears. No cookie involved.

    Used by turnstile-min/max, where success is the token input, not a
    Cloudflare session cookie (the page may not even be behind Cloudflare).
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + budget_s
    while loop.time() < deadline:
        if await has_token_input(page):
            return True
        await click_checkbox(page)
        await asyncio.sleep(1.5)
    return await has_token_input(page)
