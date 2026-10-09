"""Liveness and readiness endpoints."""

import logging
from typing import Literal

import httpx
import redis
from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import text

from core.config import get_settings
from core.db import get_engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])

CheckStatus = Literal["ok", "failed"]


class Health(BaseModel):
    status: Literal["ok"]
    env: str
    version: str


class Readiness(BaseModel):
    status: CheckStatus
    mysql: CheckStatus
    redis: CheckStatus
    qdrant: CheckStatus


@router.get("")
def health() -> Health:
    return Health(status="ok", env=get_settings().app_env, version="0.1.0")


def _check_mysql() -> CheckStatus:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("MySQL readiness check failed: %s", type(exc).__name__)
        return "failed"
    return "ok"


def _check_redis() -> CheckStatus:
    try:
        client = redis.Redis.from_url(get_settings().redis_url, socket_timeout=2)
        client.ping()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis readiness check failed: %s", type(exc).__name__)
        return "failed"
    return "ok"


def _check_qdrant() -> CheckStatus:
    try:
        response = httpx.get(f"{get_settings().qdrant_url}/readyz", timeout=2)
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Qdrant readiness check failed: %s", type(exc).__name__)
        return "failed"
    return "ok"


@router.get("/ready")
def ready(response: Response) -> Readiness:
    checks = {"mysql": _check_mysql(), "redis": _check_redis(), "qdrant": _check_qdrant()}
    overall: CheckStatus = "ok" if all(v == "ok" for v in checks.values()) else "failed"
    if overall != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return Readiness(status=overall, **checks)
