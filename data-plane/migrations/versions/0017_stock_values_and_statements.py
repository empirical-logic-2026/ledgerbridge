"""Stock values and foreign-currency revaluations as source figures; the first reporting
tables: statement lines (ours and the source's) and the Trial Balance, Profit & Loss and
Balance Sheet views (ADR-033, ADR-040; DAT-013, VAL-015, RPT-012).

- `ledgerbridge_accounting.stock_values`: the source's stock value as of a date (total, and
  by stock group and godown where it gives them).
- `ledgerbridge_accounting.fx_revaluation_snapshots`: each foreign-currency ledger's balance
  as the source reports it, revalued, against its book value (FX-004).
- `ledgerbridge_reporting.statement_lines`: statement lines as of each date stored.
- Views on statement_lines: `v_trial_balance`, `v_profit_loss`, `v_balance_sheet` (ours)
  and `v_statement_check` (ours against the source's, line by line).

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCOUNTING = "ledgerbridge_accounting"
REPORTING = "ledgerbridge_reporting"
SYSTEM = "ledgerbridge_system"

ID = sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql")
TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
MONEY = sa.Numeric(20, 4)
ORIGIN = sa.Enum("live", "backup", "file", "manual", name="origin")

# Complete statements (no SQL built from strings), created in this order, dropped in reverse.
CREATE_VIEWS = (
    """CREATE VIEW ledgerbridge_reporting.v_trial_balance AS
        SELECT entity_id, as_of, line_no, label, debit, credit, amount
        FROM ledgerbridge_reporting.statement_lines
        WHERE statement = 'trial_balance' AND figures = 'ours'""",
    """CREATE VIEW ledgerbridge_reporting.v_profit_loss AS
        SELECT entity_id, as_of, line_no, section, label, level, amount
        FROM ledgerbridge_reporting.statement_lines
        WHERE statement = 'profit_loss' AND figures = 'ours'""",
    """CREATE VIEW ledgerbridge_reporting.v_balance_sheet AS
        SELECT entity_id, as_of, line_no, section, label, level, amount
        FROM ledgerbridge_reporting.statement_lines
        WHERE statement = 'balance_sheet' AND figures = 'ours'""",
    """CREATE VIEW ledgerbridge_reporting.v_statement_check AS
        SELECT entity_id, as_of, statement, match_key,
               SUM(CASE WHEN figures = 'ours' THEN amount ELSE 0 END) AS ours,
               SUM(CASE WHEN figures = 'source' THEN amount ELSE 0 END) AS source,
               SUM(CASE WHEN figures = 'ours' THEN amount ELSE -amount END) AS difference
        FROM ledgerbridge_reporting.statement_lines
        WHERE level <> 'detail'
        GROUP BY entity_id, as_of, statement, match_key""",
)
DROP_VIEWS = (
    "DROP VIEW IF EXISTS ledgerbridge_reporting.v_statement_check",
    "DROP VIEW IF EXISTS ledgerbridge_reporting.v_balance_sheet",
    "DROP VIEW IF EXISTS ledgerbridge_reporting.v_profit_loss",
    "DROP VIEW IF EXISTS ledgerbridge_reporting.v_trial_balance",
)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "stock_values",
        sa.Column("id", ID, primary_key=True, autoincrement=True),
        sa.Column("entity_id", ID, sa.ForeignKey(f"{ACCOUNTING}.entities.id"), nullable=False),
        sa.Column("connection_id", ID, sa.ForeignKey(f"{SYSTEM}.connections.id"), nullable=False),
        sa.Column("origin", ORIGIN, nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column(
            "scope",
            sa.Enum("total", "stock_group", "godown", name="stock_value_scope"),
            nullable=False,
        ),
        sa.Column("scope_name", sa.String(255), nullable=False),
        sa.Column("opening_value", MONEY, nullable=True),
        sa.Column("closing_value", MONEY, nullable=True),
        sa.Column("integrated", sa.Boolean(), nullable=True),
        sa.Column("read_at", TIMESTAMP, nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "entity_id", "as_of", "scope", "scope_name", name="uq_stock_values_entity_date"
        ),
        schema=ACCOUNTING,
    )
    op.create_table(
        "fx_revaluation_snapshots",
        sa.Column("id", ID, primary_key=True, autoincrement=True),
        sa.Column("entity_id", ID, sa.ForeignKey(f"{ACCOUNTING}.entities.id"), nullable=False),
        sa.Column("ledger_id", ID, sa.ForeignKey(f"{ACCOUNTING}.ledgers.id"), nullable=False),
        sa.Column("connection_id", ID, sa.ForeignKey(f"{SYSTEM}.connections.id"), nullable=False),
        sa.Column("origin", ORIGIN, nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("currency_code", sa.CHAR(3), nullable=True),
        sa.Column("balance_fc", MONEY, nullable=True),
        sa.Column("book_value", MONEY, nullable=False),
        sa.Column("revalued_value", MONEY, nullable=False),
        sa.Column("unrealised_gain_loss", MONEY, nullable=False),
        sa.Column("read_at", TIMESTAMP, nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("ledger_id", "as_of", name="uq_fx_revaluation_ledger_date"),
        schema=ACCOUNTING,
    )
    op.create_index(
        "ix_fx_revaluation_entity_date",
        "fx_revaluation_snapshots",
        ["entity_id", "as_of"],
        schema=ACCOUNTING,
    )
    op.create_table(
        "statement_lines",
        sa.Column("id", ID, primary_key=True, autoincrement=True),
        sa.Column("entity_id", ID, sa.ForeignKey(f"{ACCOUNTING}.entities.id"), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column(
            "statement",
            sa.Enum("trial_balance", "profit_loss", "balance_sheet", name="statement_kind"),
            nullable=False,
        ),
        sa.Column("figures", sa.Enum("ours", "source", name="statement_figures"), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(32), nullable=True),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("match_key", sa.String(255), nullable=False),
        sa.Column(
            "level", sa.Enum("main", "sub", "detail", name="statement_level"), nullable=False
        ),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("debit", MONEY, nullable=True),
        sa.Column("credit", MONEY, nullable=True),
        sa.Column("refreshed_at", TIMESTAMP, nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "entity_id", "as_of", "statement", "figures", "line_no", name="uq_statement_lines_line"
        ),
        schema=REPORTING,
    )
    op.create_index(
        "ix_statement_lines_match",
        "statement_lines",
        ["entity_id", "as_of", "statement", "match_key"],
        schema=REPORTING,
    )
    for statement in CREATE_VIEWS:
        op.execute(statement)


def downgrade() -> None:
    for statement in DROP_VIEWS:
        op.execute(statement)
    # Dropping a table drops its indexes; MySQL refuses to drop on its own an index a foreign
    # key needs (the ones starting with entity_id).
    op.drop_table("statement_lines", schema=REPORTING)
    op.drop_table("fx_revaluation_snapshots", schema=ACCOUNTING)
    op.drop_table("stock_values", schema=ACCOUNTING)
