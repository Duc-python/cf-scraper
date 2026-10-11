"""mode=turnstile-max - mirrors src/endpoints/solveTurnstile.max.js.

Token capture strategy, in order of preference:

1. `cf-turnstile-response` - the hidden input Cloudflare itself creates next to
   every widget it renders. Reading it needs no cooperation from the page.
2. A captured render callback.

A note on what NOT to do: wrapping `window.turnstile.render` via a property
setter, to intercept the page's own callback. It does work in principle, but
it breaks the widget: with the wrapper installed, nopecha.com/demo/turnstile
renders nothing at all - Cloudflare's api.js does not survive having
`window.turnstile` turned into an accessor before it loads. Polling
`getResponse()` is no good either - with no widget argument it returns the
first widget's token, so a page carrying both a real sitekey and one of
Cloudflare's test keys hands back `XXXX.DUMMY.TOKEN.XXXX`.

Cloudflare's documented test sitekeys return that placeholder instead of a
token, so any captured placeholder is rejected rather than reported as
success - see jobs._common.is_dummy.
"""
from __future__ import annotations

from typing import Any

from ._common import JobError, goto_document, wait_for_token
from . import _solve

READ_TOKEN_JS = r"""() => {
  const inputs = document.querySelectorAll(
    'input[name="cf-turnstile-response"], textarea[name="cf-turnstile-response"]');
  const out = [];
  for (const el of inputs) {
    if (el.value) out.push({ container: el.id || 'cf-turnstile-response',
                             token: el.value });
  }
  // some pages copy the token into a cf-response field of their own
  for (const el of document.querySelectorAll('input[name="cf-response"]')) {
    if (el.value) out.push({ container: el.id || 'cf-response', token: el.value });
  }
  return out;
}"""


async def run(context: Any, url: str) -> str:
    if not url:
        raise JobError("Missing url parameter")
    page = await context.new_page()
    await goto_document(page, url, wait_until="domcontentloaded")
    await _solve.attempt_widget_clicks(page)
    return await wait_for_token(page, timeout_ms=60000, reader=READ_TOKEN_JS)