"""mode=turnstile-max - mirrors src/endpoints/solveTurnstile.max.js."""
from __future__ import annotations

from typing import Any

from ._common import JobError, goto_document, wait_for_token
from . import _solve

_POLL_JS = """let token = null;
async function waitForToken() {
  while (!token) {
    try {
      token = window.turnstile.getResponse();
    } catch (e) {}
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  var c = document.createElement("input");
  c.type = "hidden";
  c.name = "cf-response";
  c.value = token;
  document.body.appendChild(c);
}
waitForToken();"""


async def run(context: Any, url: str) -> str:
    if not url:
        raise JobError("Missing url parameter")
    await context.add_init_script(_POLL_JS)
    page = await context.new_page()
    await goto_document(page, url, wait_until="domcontentloaded")
    await _solve.attempt_widget_clicks(page)
    return await wait_for_token(page, timeout_ms=60000)
