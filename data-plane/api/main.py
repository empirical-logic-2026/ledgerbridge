"""FastAPI application entry point.

Until login (M5) the API is for this computer only (ADR-049): CORS allows only the
dashboard's dev server on localhost, GET only, and startup warns when the API is published
on, or expects a frontend from, any other address. Requests are logged as method, path,
status and time only: never query strings (they can hold filter values) or bodies.
"""

import logging
import time
from collections.abc import Awaitable, Callable
from ipaddress import ip_address
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from api import v1
from api.health import router as health_router
from api.validation import router as validation_router
from core.config import Settings, get_settings

# A child of uvicorn's logger, so its handlers (and level) print these lines.
logger = logging.getLogger("uvicorn.error.ledgerbridge")
LOOPBACK_NAMES = ("localhost", "127.0.0.1", "::1")


def is_loopback(host: str) -> bool:
    if host in LOOPBACK_NAMES:
        return True
    try:
        return ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def allowed_origins(settings: Settings) -> list[str]:
    """The frontend origin on localhost, by name and by address; none if it isn't local."""
    parts = urlsplit(settings.frontend_origin)
    if parts.scheme != "http" or not parts.hostname or not is_loopback(parts.hostname):
        return []
    port = f":{parts.port}" if parts.port else ""
    return [f"http://localhost{port}", f"http://127.0.0.1{port}"]


def exposure_warnings(settings: Settings) -> list[str]:
    """What breaks ADR-049's localhost-only rule (no names or secrets)."""
    warnings = []
    if not is_loopback(settings.api_published_address):
        warnings.append(
            "The API is published on a non-loopback address: there is no login yet "
            "(ADR-049). Publish it on 127.0.0.1 only until M5."
        )
    if not allowed_origins(settings):
        warnings.append(
            "FRONTEND_ORIGIN isn't an http address on localhost: the dashboard is refused "
            "(CORS) until it is (ADR-049)."
        )
    return warnings


async def log_request(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    started = time.perf_counter()
    response = await call_next(request)
    elapsed = (time.perf_counter() - started) * 1000
    logger.info("%s %s %s %.0f ms", request.method, request.url.path, response.status_code, elapsed)
    return response


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="LedgerBridge data plane", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins(settings),
        allow_methods=["GET"],
        allow_headers=["Content-Type"],
        expose_headers=["X-Row-Limit-Reached", "Content-Disposition"],
    )
    app.middleware("http")(log_request)
    app.include_router(health_router)
    app.include_router(validation_router)
    app.include_router(v1.router)
    for warning in exposure_warnings(settings):
        logger.warning(warning)
    return app


app = create_app()
