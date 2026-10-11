"""Runtime configuration.

Same env vars as the Node original (src/index.js):
PORT, browserLimit, timeOut, authToken. Plus headless / SEED / QUIET_CANVAS
for the invisible_playwright engine.
"""
from __future__ import annotations

import os


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


PORT: int = _int("PORT", 3000)
BROWSER_LIMIT: int = _int("browserLimit", 20)
TIMEOUT_MS: int = _int("timeOut", 60000)
AUTH_TOKEN: str | None = os.getenv("authToken") or None
HEADLESS: bool = _bool("headless", True)
SKIP_LAUNCH: bool = _bool("SKIP_LAUNCH", False)
QUIET_CANVAS: bool = _bool("QUIET_CANVAS", True)

_SEED = os.getenv("SEED")
try:
    SEED: int | None = int(_SEED) if _SEED not in (None, "") else None
except ValueError:
    SEED = None
