"""Shared job primitives."""
from __future__ import annotations

import asyncio
import contextvars
import time
from typing import Any, Callable

# Set by BrowserManager.run for the duration of a job, so the solver can
# size its own budget against what is actually left. A fixed 20s solve plus
# a 10s gate plus the settle reads can reach 47s, which leaves too little
# headroom under a 60s ceiling once the machine is busy.
_DEADLINE: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "cf_deadline", default=None
)


def set_deadline(when: float | None) -> Callable[[], None]:
    """Set the job deadline; returns a callable that restores the previous one."""
    token = _DEADLINE.set(when)

    def reset() -> None:
        _DEADLINE.reset(token)

    return reset


def remaining_s(reserve: float = 0.0) -> float:
    """Seconds left in this job, never negative."""
    when = _DEADLINE.get()
    if when is None:
        return float("inf")
    return max(0.0, when - reserve - time.monotonic())


class JobError(Exception):
    """A job failure. str(exc) becomes the response 'message'."""


async def goto_document(page: Any, url: str, **kwargs: Any) -> Any:
    """goto that also rejects failed loads.

    With a dead proxy Firefox shows an error page and goto resolves with a
    None response instead of raising, which would otherwise hang the job
    until the global timeout. Fail fast with a greppable message.
    """
    response = await page.goto(url, **kwargs)
    if response is None:
        try:
            title = await page.title()
        except Exception:
            title = "unknown"
        raise JobError(f"Navigation failed: {title}")
    return response


def doc_targets(url: str) -> tuple[str, str]:
    # mirrors [url, url + "/"]
    return (url, url + "/")


async def wait_document_response(page: Any, url: str) -> Any:
    """Resolve with the first 200/302 response for the exact document URL."""
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    want = doc_targets(url)

    def _on(response: Any) -> None:
        try:
            if response.status in (200, 302) and response.url in want:
                if not future.done():
                    future.set_result(response)
        except Exception:
            pass

    page.on("response", _on)
    return await future


def track_doc_responses(page: Any, url: str) -> list:
    """Keep every response for the exact document URL, any status."""
    seen: list = []
    want = doc_targets(url)

    def _on(response: Any) -> None:
        try:
            if response.url in want:
                seen.append(response)
        except Exception:
            pass

    page.on("response", _on)
    return seen


async def wait_loaded(page: Any, timeout_ms: int = 5000) -> None:
    try:
        await page.wait_for_load_state("load", timeout=timeout_ms)
    except Exception:
        pass


def read_token_js() -> str:
    return (
        "() => { try { return document.querySelector('[name=\"cf-response\"]').value; }"
        " catch (e) { return null; } }"
    )


async def wait_for_token(page: Any, timeout_ms: int = 60000) -> str:
    """Poll for the Turnstile token until the deadline.

    wait_for_selector is unusable here: a challenge solve reloads the document
    mid-wait and the destroyed execution context fails the wait with
    "Cannot find object with id". Discrete evaluate calls race cleanly
    instead - a failed poll is just skipped.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_ms / 1000.0
    while True:
        try:
            token = await page.evaluate(read_token_js())
        except Exception:
            token = None
        if token and len(token) >= 10:
            return token
        if loop.time() >= deadline:
            break
        await asyncio.sleep(1)
    raise JobError("Failed to get token")


def check_token(token: Any) -> str:
    if not token or len(token) < 10:
        raise JobError("Failed to get token")
    return token
