"""Alembic environment. Tables span the raw, core, rpt and app schemas (MySQL databases);
the version table lives in `app`. The dedicated migrator user arrives in M2."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from core.config import get_settings
from core.db import database_url
from core.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
SCHEMAS = {"raw", "core", "rpt", "app"}


def _include_name(name: str | None, type_: str, _parent_names: object) -> bool:
    return name in SCHEMAS if type_ == "schema" else True


def run_migrations_offline() -> None:
    url = database_url(get_settings()).render_as_string(hide_password=True)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        include_name=_include_name,
        version_table_schema="app",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url(get_settings()))
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_name=_include_name,
            version_table_schema="app",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
