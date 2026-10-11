"""mode=turnstile-min - mirrors src/endpoints/solveTurnstile.min.js."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ._common import JobError, doc_targets, goto_document, wait_for_token
from . import _solve

_FAKE_PAGE = Path(__file__).resolve().parent.parent / "data" / "fake_page.html"


async def run(context: Any, url: str, site_key: str | None) -> str:
    if not url:
        raise JobError("Missing url parameter")
    if not site_key:
        raise JobError("Missing siteKey parameter")
    html = _FAKE_PAGE.read_text(encoding="utf-8").replace("<site-key>", site_key)
    want = doc_targets(url)

    async def _route(route: Any) -> None:
        request = route.request
        if request.url in want and request.resource_type == "document":
            await route.fulfill(status=200, content_type="text/html", body=html)
        else:
            await route.continue_()

    await context.route("**/*", _route)
    page = await context.new_page()
    await goto_document(page, url, wait_until="domcontentloaded")
    await _solve.attempt_widget_clicks(page)
    return await wait_for_token(page, timeout_ms=60000)
