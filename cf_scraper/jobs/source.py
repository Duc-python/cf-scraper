"""mode=source - mirrors src/endpoints/getSource.js.

One addition the port needs: the Node original relies on
puppeteer-real-browser's `turnstile: true` auto-solver to click the
"Verify you are human" checkbox. That step is explicit here
(jobs._solve), everything else follows the original: resolve on the first
200/302 for the exact document URL, then return the page source.

The response gate and the solver race: plain pages resolve immediately
through the gate (no solve delay), challenged pages resolve through the
clearance cookie, then the post-solve navigation.
"""
from __future__ import annotations

import asyncio
from typing import Any

from ._common import JobError, goto_document, wait_document_response, wait_loaded
from . import _solve

_CHALLENGE_TITLE = ("just a moment", "chờ một chút")
_CHALLENGE_HTML = ("__cf_chl", "challenge-platform")


async def _read_settled_source(page: Any, tries: int = 6) -> str:
    """Return the page source, waiting out a post-solve navigation.

    The clearance cookie can land while Cloudflare is still submitting the
    challenge form, so the first content() may be the challenge page itself.
    Stops early once the job deadline is close, to stay under the ceiling.
    """
    from ._common import remaining_s

    html = ""
    for attempt in range(tries):
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
        if remaining_s(3) <= 0:
            break
        await wait_loaded(page)
        await asyncio.sleep(1 if attempt else 2)
    return html


async def run(context: Any, url: str) -> str:
    if not url:
        raise JobError("Missing url parameter")
    page = await context.new_page()
    gate = asyncio.create_task(wait_document_response(page, url))
    solve = asyncio.create_task(_solve.click_until_clearance(page, context))
    try:
        await goto_document(page, url, wait_until="domcontentloaded")
    except BaseException:
        gate.cancel()
        solve.cancel()
        raise
    try:
        done, pending = await asyncio.wait(
            {gate, solve}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        if solve in done and solve.result() and not gate.done():
            from ._common import remaining_s

            budget = min(10, remaining_s(6))
            if budget > 0:
                try:
                    await asyncio.wait_for(asyncio.shield(gate), timeout=budget)
                except asyncio.TimeoutError:
                    pass
        await wait_loaded(page)
        return await _read_settled_source(page)
    finally:
        for task in (gate, solve):
            if not task.done():
                task.cancel()
