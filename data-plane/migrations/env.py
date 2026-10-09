"""Alembic environment. Tables span the four databases of ADR-016; the version table lives
in ledgerbridge_system. Migrations always run as the `migrator` user (schema.md 2.1), in the
one-off `migrate` container or from tests."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from core.config import get_settings
from core.db import database_url
from core.models import Base
from core.models.schemas import ALL, SYSTEM

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _include_name(name: str | None, type_: str, _parent_names: object) -> bool:
    return name in ALL if type_ == "schema" else True


_OPTIONS = {
    "target_metadata": target_metadata,
    "include_schemas": True,
    "include_name": _include_name,
    "version_table_schema": SYSTEM,
    "compare_type": True,
}


def run_migrations_offline() -> None:
    url = database_url(get_settings(), "migrator").render_as_string(hide_password=True)
    context.configure(url=url, literal_binds=True, **_OPTIONS)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url(get_settings(), "migrator"))
    with engine.connect() as connection:
        context.configure(connection=connection, **_OPTIONS)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
