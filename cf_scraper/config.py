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

# Explicit fingerprint pins. Leave empty for the engine's own derivation,
# which reads the egress IP - but that lookup is only as good as its GeoIP
# database, so a proxy in India can come back as Asia/Hong_Kong. Pin these
# when the zone/language must match the proxy's country.
TIMEZONE: str = os.getenv("timezone", "")
LOCALE: str = os.getenv("locale", "")

# Derive timezone/locale from the proxy's exit IP and launch a matching
# engine. On by default: with the proxy set per-context instead, the browser
# kept the host's timezone and offered the host's real IP as a WebRTC
# candidate, both of which a detector can cross-check against the exit IP.
AUTO_GEO: bool = _bool("AUTO_GEO", True)
SKIP_LAUNCH: bool = _bool("SKIP_LAUNCH", False)
QUIET_CANVAS: bool = _bool("QUIET_CANVAS", True)

_SEED = os.getenv("SEED")
try:
    SEED: int | None = int(_SEED) if _SEED not in (None, "") else None
except ValueError:
    SEED = None
