"""Foreign currency, the core (FX-001, FX-003; schema.md 4.8, ADR-037).

- `currencies.symbol`: the symbol the source writes (e.g. `$`).
- `currency_sources` (new, [SRC]): each entity's currencies as its source names them (Tally:
  the currency masters), with the ISO code when the source gives one.
- `ledgers.currency_name`, `ledgers.opening_balance_fc`: the ledger's currency as the source
  names it and its opening in that currency.
- `voucher_lines.currency_name`, `voucher_lines.exchange_rate`: a foreign-currency line's
  currency and its rate as written (`amount_fc` is already there).
- `exchange_rates` is replaced: the M2 outline (global, from/to codes) was never written; the
  new table is per entity, with each rate's kind and source (the source's rate list, or
  voucher rates). Base-currency columns are untouched: they stay the books.

Existing rows get the new values on `transform rebuild` (the stored records hold them).

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCOUNTING = "ledgerbridge_accounting"
SYSTEM = "ledgerbridge_system"
ID = sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql").with_variant(
    sa.Integer(), "sqlite"
)
TS = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
TINY = sa.Integer().with_variant(mysql.TINYINT(), "mysql")
MONEY = sa.Numeric(20, 4)
RATE = sa.Numeric(20, 8)


def _timestamps() -> list[sa.Column]:
    return [sa.Column("created_at", TS, nullable=False), sa.Column("updated_at", TS, nullable=False)]


def upgrade() -> None:
    op.add_column("currencies", sa.Column("symbol", sa.String(16), nullable=True), schema=ACCOUNTING)
    op.create_table(
        "currency_sources",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("entity_id", ID, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("currency_code", sa.CHAR(3), nullable=True),
        sa.Column("formal_name", sa.String(255), nullable=True),
        sa.Column("decimal_places", TINY, nullable=True),
        sa.Column("source_key", sa.String(191), nullable=False),
        sa.Column("source_alter_id", sa.BigInteger(), nullable=True),
        sa.Column("origin", sa.Enum("live", "backup", "file", "manual", name="origin"), nullable=False),
        sa.Column("raw_record_id", ID, nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.Column("connection_id", ID, nullable=False),
        sa.Column("import_batch_id", ID, nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["connection_id"], [f"{SYSTEM}.connections.id"]),
        sa.ForeignKeyConstraint(["currency_code"], [f"{ACCOUNTING}.currencies.code"]),
        sa.ForeignKeyConstraint(["entity_id"], [f"{ACCOUNTING}.entities.id"]),
        sa.ForeignKeyConstraint(["import_batch_id"], [f"{SYSTEM}.import_batches.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connection_id", "source_key", name="uq_currency_sources_source"),
        schema=ACCOUNTING,
    )
    op.create_index(
        "ix_currency_sources_raw_record", "currency_sources", ["raw_record_id"], schema=ACCOUNTING
    )
    op.add_column("ledgers", sa.Column("currency_name", sa.String(64), nullable=True), schema=ACCOUNTING)
    op.add_column("ledgers", sa.Column("opening_balance_fc", MONEY, nullable=True), schema=ACCOUNTING)
    op.add_column(
        "voucher_lines", sa.Column("currency_name", sa.String(64), nullable=True), schema=ACCOUNTING
    )
    op.add_column("voucher_lines", sa.Column("exchange_rate", RATE, nullable=True), schema=ACCOUNTING)
    op.drop_table("exchange_rates", schema=ACCOUNTING)
    op.create_table(
        "exchange_rates",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("entity_id", ID, nullable=False),
        sa.Column("currency_name", sa.String(64), nullable=False),
        sa.Column("currency_code", sa.CHAR(3), nullable=True),
        sa.Column("rate_date", sa.Date(), nullable=False),
        sa.Column("rate", RATE, nullable=False),
        sa.Column(
            "rate_kind",
            sa.Enum("standard", "buying", "selling", "vouchers", name="rate_kind"),
            nullable=False,
        ),
        sa.Column("source", sa.Enum("source_rate_list", "vouchers", name="rate_source"), nullable=False),
        sa.Column("voucher_count", sa.Integer(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["currency_code"], [f"{ACCOUNTING}.currencies.code"]),
        sa.ForeignKeyConstraint(["entity_id"], [f"{ACCOUNTING}.entities.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "entity_id", "currency_name", "rate_date", "rate_kind", name="uq_exchange_rates_day"
        ),
        schema=ACCOUNTING,
    )


def downgrade() -> None:
    op.drop_table("exchange_rates", schema=ACCOUNTING)
    op.create_table(  # the M2 outline, as migration 0002 created it
        "exchange_rates",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("from_code", sa.CHAR(3), nullable=False),
        sa.Column("to_code", sa.CHAR(3), nullable=False),
        sa.Column("rate_date", sa.Date(), nullable=False),
        sa.Column("rate", RATE, nullable=False),
        sa.Column("source", sa.String(64), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["from_code"], [f"{ACCOUNTING}.currencies.code"]),
        sa.ForeignKeyConstraint(["to_code"], [f"{ACCOUNTING}.currencies.code"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("from_code", "to_code", "rate_date", name="uq_exchange_rates_day"),
        schema=ACCOUNTING,
    )
    op.drop_column("voucher_lines", "exchange_rate", schema=ACCOUNTING)
    op.drop_column("voucher_lines", "currency_name", schema=ACCOUNTING)
    op.drop_column("ledgers", "opening_balance_fc", schema=ACCOUNTING)
    op.drop_column("ledgers", "currency_name", schema=ACCOUNTING)
    op.drop_table("currency_sources", schema=ACCOUNTING)
    op.drop_column("currencies", "symbol", schema=ACCOUNTING)
