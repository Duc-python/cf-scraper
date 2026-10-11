"""mode=waf-session - mirrors src/endpoints/wafSession.js.

Same checkbox-solving addition as source mode (see jobs.source); the
returned cookies/headers shape is unchanged.
"""
from __future__ import annotations

import asyncio
from typing import Any

from ._common import JobError, goto_document, track_doc_responses, wait_document_response, wait_loaded
from . import _solve

_ACCEPT_LANGUAGE_JS = (
    "() => fetch('https://httpbin.org/get').then(r => r.json())"
    ".then(j => j.headers['Accept-Language'] || j.headers['accept-language'])"
    ".catch(() => null)"
)

_DROP_HEADERS = ("content-type", "accept-encoding", "accept", "content-length")


async def run(context: Any, url: str) -> dict[str, Any]:
    if not url:
        raise JobError("Missing url parameter")
    page = await context.new_page()
    accept_language = await page.evaluate(_ACCEPT_LANGUAGE_JS)
    gate = asyncio.create_task(wait_document_response(page, url))
    seen = track_doc_responses(page, url)
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
        response = None
        if gate in done:
            response = gate.result()
        elif solve.result():
            from ._common import remaining_s

            budget = min(10, remaining_s(6))
            if budget > 0:
                try:
                    response = await asyncio.wait_for(asyncio.shield(gate), timeout=budget)
                except asyncio.TimeoutError:
                    response = None
        if response is None and seen:
            response = seen[-1]
        await wait_loaded(page)
        cookies = await context.cookies()
        headers = dict(response.request.headers) if response is not None else {}
        for key in _DROP_HEADERS:
            headers.pop(key, None)
        headers["accept-language"] = accept_language
        return {"cookies": cookies, "headers": headers}
    finally:
        for task in (gate, solve):
            if not task.done():
                task.cancel()
