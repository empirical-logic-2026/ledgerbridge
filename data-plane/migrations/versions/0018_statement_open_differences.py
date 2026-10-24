"""Statements: the view of open differences (VAL-015, ADR-043).

Lines taken from the source (labelled "(taken from the source)") where ours, the "(computed)"
detail line beside it, differs: one row per entity, date, statement and line, with both
figures and the difference (trial balance lines also by debit and credit). Validation warns
about the same dates (LB-VAL-026) when they differ by more than the connection's validation
tolerance (default 0, exact): the view lists every difference above zero.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# A complete statement (no SQL built from strings).
CREATE_VIEW = """CREATE VIEW ledgerbridge_reporting.v_statement_open_differences AS
    SELECT taken.entity_id, taken.as_of, taken.statement, taken.match_key, taken.label,
           taken.amount AS source_amount, computed.amount AS computed_amount,
           taken.amount - computed.amount AS difference,
           COALESCE(taken.debit, 0) - COALESCE(computed.debit, 0) AS debit_difference,
           COALESCE(taken.credit, 0) - COALESCE(computed.credit, 0) AS credit_difference
    FROM ledgerbridge_reporting.statement_lines AS taken
    JOIN ledgerbridge_reporting.statement_lines AS computed
      ON computed.entity_id = taken.entity_id AND computed.as_of = taken.as_of
     AND computed.statement = taken.statement AND computed.figures = 'ours'
     AND computed.level = 'detail' AND computed.match_key = taken.match_key
     AND computed.label LIKE '% (computed)'
    WHERE taken.figures = 'ours' AND taken.level = 'main'
      AND taken.label LIKE '% (taken from the source)'
      AND (taken.amount <> computed.amount
           OR COALESCE(taken.debit, 0) <> COALESCE(computed.debit, 0)
           OR COALESCE(taken.credit, 0) <> COALESCE(computed.credit, 0))"""
DROP_VIEW = "DROP VIEW IF EXISTS ledgerbridge_reporting.v_statement_open_differences"


def upgrade() -> None:
    op.execute(CREATE_VIEW)


def downgrade() -> None:
    op.execute(DROP_VIEW)
