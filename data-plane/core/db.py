"""SQLAlchemy engines for the data-plane databases, one per MySQL user (schema.md 2.1)."""

from functools import lru_cache
from typing import Literal

from sqlalchemy import URL, Engine, create_engine

from core.config import Settings, get_settings
from core.models.schemas import ACCOUNTING, REPORTING, SYSTEM

Role = Literal["app", "migrator", "report", "ai"]

# A default database each user is allowed to use (tables are always qualified anyway).
# The migrator has none: otherwise Alembic sees tables of the default database as
# unqualified and fails to match them to the models' qualified names.
_DEFAULT_DATABASE: dict[Role, str | None] = {
    "app": SYSTEM,
    "migrator": None,
    "report": ACCOUNTING,
    "ai": REPORTING,
}
_UNSET = "<role default>"


def database_url(settings: Settings, role: Role = "app", database: str | None = _UNSET) -> URL:
    """Connection URL for one database user (schema.md 2.1)."""
    if database == _UNSET:
        database = _DEFAULT_DATABASE[role]
    user, password = {
        "app": (settings.mysql_app_user, settings.mysql_app_password),
        "migrator": (settings.mysql_migrator_user, settings.mysql_migrator_password),
        "report": (settings.mysql_report_user, settings.mysql_report_password),
        "ai": (settings.mysql_ai_user, settings.mysql_ai_password),
    }[role]
    return URL.create(
        "mysql+pymysql",
        username=user,
        password=password.get_secret_value(),
        host=settings.mysql_host,
        port=settings.mysql_port,
        database=database,
        query={"charset": "utf8mb4"},
    )


@lru_cache
def get_engine(role: Role = "app") -> Engine:
    return create_engine(database_url(get_settings(), role), pool_pre_ping=True)
