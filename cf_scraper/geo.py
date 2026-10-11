"""Derive timezone/locale from the proxy egress IP.

Measured problem: the engine derives its timezone from the host when the
proxy is set per-context, so an India proxy still reports Asia/Bangkok.
A zone that disagrees with the exit IP is a cheap cross-check for a
detector, so resolve it here and pin it per job.

The engine's own GeoIP pass is not reliable either (an India IP came back as
Asia/Hong_Kong), so this uses an external resolver and falls back silently.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from .schemas import ProxyConfig

# Small offline-ish map for the common exit ranges, used when the resolver
# is unreachable. Kept deliberately short: correctness beats coverage here.
_FALLBACK_OFFSETS = {
    "Asia/Kolkata": 330, "Asia/Dhaka": 360, "Asia/Bangkok": 420,
    "Asia/Jakarta": 420, "Asia/Singapore": 480, "Asia/Shanghai": 480,
    "Asia/Hong_Kong": 480, "Asia/Taipei": 480, "Asia/Tokyo": 540,
    "Asia/Seoul": 540, "Australia/Sydney": 600, "Europe/Moscow": 180,
    "Europe/Istanbul": 180, "Europe/Berlin": 120, "Europe/Paris": 120,
    "Europe/London": 0, "Europe/Kyiv": 120, "Africa/Lagos": 60,
    "America/New_York": -300, "America/Chicago": -360,
    "America/Denver": -420, "America/Los_Angeles": -480,
    "America/Sao_Paulo": -180,
}

# language that actually goes with each zone, for the locale pin
_ZONE_LANG = {
    "Asia/Kolkata": "en-IN", "Asia/Dhaka": "en-BD", "Asia/Bangkok": "th-TH",
    "Asia/Jakarta": "id-ID", "Asia/Singapore": "en-SG",
    "Asia/Shanghai": "zh-CN", "Asia/Hong_Kong": "zh-HK",
    "Asia/Taipei": "zh-TW", "Asia/Tokyo": "ja-JP", "Asia/Seoul": "ko-KR",
    "Australia/Sydney": "en-AU", "Europe/Moscow": "ru-RU",
    "Europe/Istanbul": "tr-TR", "Europe/Berlin": "de-DE",
    "Europe/Paris": "fr-FR", "Europe/London": "en-GB",
    "Europe/Kyiv": "uk-UA", "Africa/Lagos": "en-NG",
    "America/New_York": "en-US", "America/Chicago": "en-US",
    "America/Denver": "en-US", "America/Los_Angeles": "en-US",
    "America/Sao_Paulo": "pt-BR",
}


async def _resolver(proxy: Optional[ProxyConfig], timeout: float = 12.0):
    """ip-api.com over the proxy, so the answer describes the exit."""
    url = "http://ip-api.com/json/?fields=countryCode,country,timezone,query"
    try:
        import httpx
    except ImportError:  # pragma: no cover
        return None
    kwargs = {"timeout": timeout}
    if proxy is not None:
        kwargs["proxy"] = f"http://{proxy.host}:{proxy.port}"
        if proxy.username:
            kwargs["auth"] = (proxy.username, proxy.password or "")
    try:
        async with httpx.AsyncClient(**kwargs) as client:
            r = await client.get(url)
            if r.status_code != 200:
                return None
            return r.json()
    except Exception:
        return None


async def resolve_geo(proxy: Optional[ProxyConfig]) -> dict:
    """Return {ip, timezone, locale, country} for the proxy exit."""
    data = await _resolver(proxy)
    if not data or not data.get("timezone"):
        return {"ip": None, "timezone": "", "locale": "", "country": ""}
    zone = data["timezone"]
    return {
        "ip": data.get("query"),
        "timezone": zone,
        "locale": _ZONE_LANG.get(zone, ""),
        "country": data.get("country") or data.get("countryCode") or "",
    }