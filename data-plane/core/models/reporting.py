"""`ledgerbridge_reporting`: the semantic layer (schema.md Section 6). The only database the
AI can read; everything here is derived from the accounting tables and refreshed by workers.

`statement_lines` holds the Trial Balance, Profit & Loss and Balance Sheet, ours and the
source's (ADR-040), as of each date stored (month ends, year ends, validation dates); views
in migration 0017 (`v_trial_balance`, `v_profit_loss`, `v_balance_sheet`,
`v_statement_check`) sit on top.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, Enum, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base, Id, Money, Timestamp, TimestampMixin
from core.models.schemas import ACCOUNTING, REPORTING

STATEMENTS = ("trial_balance", "profit_loss", "balance_sheet")


class StatementLine(TimestampMixin, Base):
    """One line of a statement as of a date. `figures`: ours (built from the accounting
    tables and the source's stock and revaluation figures) or the source's own (its report
    export). `match_key` is the label as both sides are compared (e.g. without "Add: ").
    `level`: main, sub (inside a block) or detail (ours only, never compared). Amounts in
    the canonical sign (debit positive); trial balance lines also give debit and credit."""

    __tablename__ = "statement_lines"
    __table_args__ = (
        UniqueConstraint(
            "entity_id", "as_of", "statement", "figures", "line_no", name="uq_statement_lines_line"
        ),
        Index("ix_statement_lines_match", "entity_id", "as_of", "statement", "match_key"),
        {"schema": REPORTING},
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Id, ForeignKey(f"{ACCOUNTING}.entities.id"))
    as_of: Mapped[date] = mapped_column(Date)
    statement: Mapped[str] = mapped_column(Enum(*STATEMENTS, name="statement_kind"))
    figures: Mapped[str] = mapped_column(Enum("ours", "source", name="statement_figures"))
    line_no: Mapped[int] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(32), nullable=True)
    label: Mapped[str] = mapped_column(String(255))
    match_key: Mapped[str] = mapped_column(String(255))
    level: Mapped[str] = mapped_column(Enum("main", "sub", "detail", name="statement_level"))
    amount: Mapped[Decimal] = mapped_column(Money)
    debit: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    credit: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    refreshed_at: Mapped[datetime] = mapped_column(Timestamp)
