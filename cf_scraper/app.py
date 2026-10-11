"""HTTP API - Python port of src/index.js.

Same route, same request shape, same response shapes and status codes.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from . import config
from .browser_manager import BrowserFull, BrowserManager
from .jobs import source, turnstile_max, turnstile_min, waf_session
from .jobs._common import JobError
from .schemas import ProxyConfig, ScrapeRequest

NOT_READY = "The scanner is not ready yet. Please try again a little later."
_UNSET: Any = object()


def create_app(
    *,
    limit: Optional[int] = None,
    timeout_ms: Optional[int] = None,
    auth_token: Any = _UNSET,
    headless: Optional[bool] = None,
    seed: Optional[int] = None,
    quiet_canvas: Optional[bool] = None,
    timezone: Optional[str] = None,
    locale: Optional[str] = None,
    auto_geo: Optional[bool] = None,
    launch_browser: Optional[bool] = None,
) -> FastAPI:
    manager = BrowserManager(
        limit=config.BROWSER_LIMIT if limit is None else limit,
        timeout_ms=config.TIMEOUT_MS if timeout_ms is None else timeout_ms,
        headless=config.HEADLESS if headless is None else headless,
        seed=seed,
        quiet_canvas=config.QUIET_CANVAS if quiet_canvas is None else quiet_canvas,
        timezone=config.TIMEZONE if timezone is None else timezone,
        locale=config.LOCALE if locale is None else locale,
        auto_geo=config.AUTO_GEO if auto_geo is None else auto_geo,
    )
    token = config.AUTH_TOKEN if auth_token is _UNSET else auth_token
    launch = (not config.SKIP_LAUNCH) if launch_browser is None else launch_browser

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if launch:
            await manager.launch()
        try:
            yield
        finally:
            await manager.close()

    app = FastAPI(lifespan=lifespan)
    app.state.manager = manager
    app.state.auth_token = token

    @app.post("/cf-clearance-scraper")
    async def handle(request: Request):
        try:
            body = await request.json()
        except Exception:
            return _err(400, "Bad Request", schema=["invalid JSON body"])
        if not isinstance(body, dict):
            return _err(400, "Bad Request", schema=["body must be a JSON object"])
        try:
            data = ScrapeRequest(**body)
        except ValidationError as exc:
            return _err(400, "Bad Request", schema=jsonable_encoder(exc.errors()))

        if token and data.authToken != token:
            return _err(401, "Unauthorized")

        try:
            manager.acquire()
        except BrowserFull:
            return _err(429, "Too Many Requests")

        try:
            if not manager.ready:
                return _err(500, NOT_READY)
            result = await _dispatch(manager, data)
        finally:
            manager.release()
        return JSONResponse(result, status_code=result.get("code", 500))

    @app.exception_handler(404)
    async def _not_found(request: Request, exc: Exception):
        return _err(404, "Not Found")

    return app


async def _dispatch(manager: BrowserManager, data: ScrapeRequest) -> dict[str, Any]:
    proxy: Optional[ProxyConfig] = data.proxy
    try:
        if data.mode == "source":
            html = await manager.run(proxy, lambda ctx: source.run(ctx, data.url))
            return {"source": html, "code": 200}
        if data.mode == "turnstile-min":
            token = await manager.run(
                proxy, lambda ctx: turnstile_min.run(ctx, data.url, data.siteKey)
            )
            return {"token": token, "code": 200}
        if data.mode == "turnstile-max":
            token = await manager.run(proxy, lambda ctx: turnstile_max.run(ctx, data.url))
            return {"token": token, "code": 200}
        session = await manager.run(proxy, lambda ctx: waf_session.run(ctx, data.url))
        return {**session, "code": 200}
    except JobError as exc:
        return {"code": 500, "message": str(exc) or type(exc).__name__}
    except Exception as exc:  # noqa: BLE001 - message passthrough like err.message
        return {"code": 500, "message": str(exc) or type(exc).__name__}


def _err(status: int, message: str, **extra: Any) -> JSONResponse:
    return JSONResponse({"code": status, "message": message, **extra}, status_code=status)
