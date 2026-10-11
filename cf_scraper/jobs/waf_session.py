"""mode=waf-session - mirrors src/endpoints/wafSession.js.

Same checkbox-solving addition as source mode (see jobs.source); the
returned cookies/headers shape is unchanged.
"""
from __future__ import annotations

import asyncio
from typing import Any

from ._common import JobError, track_doc_responses, wait_document_response, wait_loaded
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
    try:
        await page.goto(url, wait_until="domcontentloaded")
    except BaseException:
        gate.cancel()
        raise
    try:
        solved = await _solve.click_until_clearance(page, context)
        response = None
        if gate.done():
            response = gate.result()
        elif solved:
            try:
                response = await asyncio.wait_for(asyncio.shield(gate), timeout=10)
            except asyncio.TimeoutError:
                response = None
        else:
            response = await gate
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
        if not gate.done():
            gate.cancel()
