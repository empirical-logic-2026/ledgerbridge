"""Celery application. Real jobs arrive from M3 onwards."""

from celery import Celery

from core.config import get_settings

settings = get_settings()

celery_app = Celery("ledgerbridge", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(task_serializer="json", result_serializer="json", accept_content=["json"])


@celery_app.task(name="workers.ping")
def ping() -> str:
    return "pong"
