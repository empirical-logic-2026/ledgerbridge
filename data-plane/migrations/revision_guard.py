"""Refuse migrations when the database revision is absent from the checked-out history."""

from collections.abc import Iterable
from sys import stderr

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from core.config import get_settings
from core.db import database_url
from core.models.schemas import SYSTEM


def unknown_revisions(recorded: Iterable[str], known: Iterable[str]) -> list[str]:
    """Return recorded revision IDs that this checkout cannot resolve."""
    return sorted(set(recorded) - set(known))


def main() -> int:
    config = Config("alembic.ini")
    scripts = ScriptDirectory.from_config(config)
    known = {revision.revision for revision in scripts.walk_revisions()}
    engine = create_engine(database_url(get_settings(), "migrator"))
    with engine.connect() as connection:
        recorded = MigrationContext.configure(
            connection,
            opts={"version_table_schema": SYSTEM},
        ).get_current_heads()

    unknown = unknown_revisions(recorded, known)
    if unknown:
        print(
            "The database records Alembic revision(s) not present in this checkout: "
            f"{', '.join(unknown)}.",
            file=stderr,
        )
        print(
            "No migration was run. This can happen when the database was migrated with "
            "stashed or uncommitted migrations. Recover and renumber those migrations after "
            "the current branch's migrations, then back up and reconcile the Alembic stamp "
            "with the schema already applied before retrying.",
            file=stderr,
        )
        return 2

    revision = ", ".join(recorded) if recorded else "none (new database)"
    print(f"Database migration revision is present in this checkout: {revision}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
