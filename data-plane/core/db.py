"""SQLAlchemy engine for the data-plane database. Models arrive in M2."""

from functools import lru_cache

from sqlalchemy import URL, Engine, create_engine

from core.config import Settings, get_settings


def database_url(settings: Settings, database: str = "app") -> URL:
    return URL.create(
        "mysql+pymysql",
        username=settings.mysql_app_user,
        password=settings.mysql_app_password.get_secret_value(),
        host=settings.mysql_host,
        port=settings.mysql_port,
        database=database,
        query={"charset": "utf8mb4"},
    )


@lru_cache
def get_engine() -> Engine:
    return create_engine(database_url(get_settings()), pool_pre_ping=True)
