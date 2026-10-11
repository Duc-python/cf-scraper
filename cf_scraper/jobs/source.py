"""mode=source - mirrors src/endpoints/getSource.js.

One addition the port needs: the Node original relies on
puppeteer-real-browser's `turnstile: true` auto-solver to click the
"Verify you are human" checkbox. That step is explicit here
(jobs._solve), everything else follows the original: resolve on the first
200/302 for the exact document URL, then return the page source.
"""
from __future__ import annotations

import asyncio
from typing import Any

from ._common import JobError, wait_document_response, wait_loaded
from . import _solve

_CHALLENGE_TITLE = ("just a moment", "chờ một chút")
_CHALLENGE_HTML = ("__cf_chl", "challenge-platform")


async def _read_settled_source(page: Any, tries: int = 6) -> str:
    """Return the page source, waiting out a post-solve navigation.

    The clearance cookie can land while Cloudflare is still submitting the
    challenge form, so the first content() may be the challenge page itself.
    """
    html = ""
    for _ in range(tries):
        html = await page.content()
        try:
            title = (await page.title() or "").lower()
        except Exception:
            title = ""
        lowered = html.lower()
        if not (
            any(marker in title for marker in _CHALLENGE_TITLE)
            or any(marker in lowered for marker in _CHALLENGE_HTML)
        ):
            return html
        await wait_loaded(page)
        await asyncio.sleep(2)
    return html


async def run(context: Any, url: str) -> str:
    if not url:
        raise JobError("Missing url parameter")
    page = await context.new_page()
    gate = asyncio.create_task(wait_document_response(page, url))
    try:
        await page.goto(url, wait_until="domcontentloaded")
    except BaseException:
        gate.cancel()
        raise
    try:
        solved = await _solve.click_until_clearance(page, context)
        if not gate.done():
            if solved:
                try:
                    await asyncio.wait_for(asyncio.shield(gate), timeout=10)
                except asyncio.TimeoutError:
                    pass
            else:
                await gate
        await wait_loaded(page)
        return await _read_settled_source(page)
    finally:
        if not gate.done():
            gate.cancel()
