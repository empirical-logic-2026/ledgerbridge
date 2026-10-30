"""The dashboard Overview's figures for companies, a financial year and an "as at" date (D1;
RPT-001, RPT-006). Source-independent: groups are found by their predefined role
(`account_groups.predefined_role`, ADR-047), never by name, and amounts are in the base
currency, as the books keep them (foreign-currency ledgers at book value).

- **Sales, purchases:** the effective entries (`is_effective`, voucher not deleted) on the
  ledgers under the Sales Accounts and Purchase Accounts groups (any depth), from the start
  of the financial year to the date. Sales is the net credit (returns and adjustments
  deducted, as `v_monthly_sales` computes it); purchases the net debit.
- **Gross and net profit:** from our stored Profit & Loss (`v_profit_loss`, the statements
  validated against the source's, ADR-040). It runs from the books' beginning, so the year's
  profit is the figure at the date less the figure at the previous financial year end
  (nothing to deduct in the books' first year). None when a statement isn't stored.
- **Cash and bank, receivables, payables:** each ledger's opening balance plus its effective
  entries up to the date, for the ledgers under Cash-in-Hand and Bank Accounts, Sundry
  Debtors, and Sundry Creditors. Receivables are the debit balance, payables the credit
  balance shown positive.
- **Monthly sales:** the same entries as sales, per month up to the date (whole months
  equal `v_monthly_sales`).

Several companies are added together: combined, without inter-company eliminations.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models import accounting as A  # noqa: N812
from core.models.reporting import StatementLine
from core.reporting_views import GROUP_ANCESTORS
from core.statements import GROSS_PROFIT, NET_PROFIT

ZERO = Decimal(0)
SALES, PURCHASES = "sales_accounts", "purchase_accounts"
CASH_AND_BANK = ("cash_in_hand", "bank_accounts")
RECEIVABLES, PAYABLES = "sundry_debtors", "sundry_creditors"


@dataclass
class Overview:
    period_start: date
    as_of: date
    sales: Decimal
    purchases: Decimal
    gross_profit: Decimal | None  # None: a statement for the date isn't stored
    net_profit: Decimal | None
    cash_and_bank: Decimal
    receivables: Decimal
    payables: Decimal
    monthly_sales: list[tuple[date, Decimal]] = field(default_factory=list)


def overview(session: Session, companies: list[int], year_start: date, as_of: date) -> Overview:
    """The figures for the companies, from `year_start` (the financial year's first day) to
    `as_of`."""
    previous_year_end = year_start - timedelta(days=1)
    gross_now, net_now = _profit(session, companies, as_of)
    gross_before, net_before = _profit_before(session, companies, previous_year_end)
    return Overview(
        period_start=year_start,
        as_of=as_of,
        sales=-_movement(session, companies, (SALES,), year_start, as_of),
        purchases=_movement(session, companies, (PURCHASES,), year_start, as_of),
        gross_profit=_less(gross_now, gross_before),
        net_profit=_less(net_now, net_before),
        cash_and_bank=_balance(session, companies, CASH_AND_BANK, as_of),
        receivables=_balance(session, companies, (RECEIVABLES,), as_of),
        payables=-_balance(session, companies, (PAYABLES,), as_of),
        monthly_sales=_monthly_sales(session, companies, year_start, as_of),
    )


def _ledgers_under(companies: list[int], roles: tuple[str, ...]):  # noqa: ANN202
    """Ids of the ledgers under the groups with these predefined roles, at any depth."""
    tops = select(A.AccountGroup.id).where(
        A.AccountGroup.entity_id.in_(companies), A.AccountGroup.predefined_role.in_(roles)
    )
    groups = select(GROUP_ANCESTORS.c.group_id).where(GROUP_ANCESTORS.c.ancestor_id.in_(tops))
    return select(A.Ledger.id).where(A.Ledger.group_id.in_(groups))


def _effective_lines(companies: list[int], roles: tuple[str, ...]):  # noqa: ANN202
    return (
        select(func.coalesce(func.sum(A.VoucherLine.amount), 0))
        .join(A.Voucher, A.Voucher.id == A.VoucherLine.voucher_id)
        .where(
            A.VoucherLine.entity_id.in_(companies),
            A.VoucherLine.is_effective.is_(True),
            A.Voucher.is_deleted.is_(False),
            A.VoucherLine.ledger_id.in_(_ledgers_under(companies, roles)),
        )
    )


def _movement(
    session: Session, companies: list[int], roles: tuple[str, ...], start: date, end: date
) -> Decimal:
    """The net of the entries between the dates (canonical sign: debit positive)."""
    query = _effective_lines(companies, roles).where(
        A.VoucherLine.voucher_date >= start, A.VoucherLine.voucher_date <= end
    )
    return Decimal(session.scalar(query) or 0)


def _balance(session: Session, companies: list[int], roles: tuple[str, ...], on: date) -> Decimal:
    """The ledgers' openings plus their entries up to the date (debit positive)."""
    openings = select(func.coalesce(func.sum(A.Ledger.opening_balance), 0)).where(
        A.Ledger.id.in_(_ledgers_under(companies, roles)), A.Ledger.is_deleted.is_(False)
    )
    entries = _effective_lines(companies, roles).where(A.VoucherLine.voucher_date <= on)
    return Decimal(session.scalar(openings) or 0) + Decimal(session.scalar(entries) or 0)


def _profit(
    session: Session, companies: list[int], on: date
) -> tuple[Decimal | None, Decimal | None]:
    """Gross and net profit from the books' beginning to the date (a profit positive), from
    our stored Profit & Loss; None unless every company has one for the date."""
    rows = session.execute(
        select(StatementLine.entity_id, StatementLine.label, StatementLine.amount).where(
            StatementLine.entity_id.in_(companies),
            StatementLine.as_of == on,
            StatementLine.statement == "profit_loss",
            StatementLine.figures == "ours",
            StatementLine.label.in_((GROSS_PROFIT, NET_PROFIT)),
        )
    ).all()
    found = {(entity, label): -Decimal(amount) for entity, label, amount in rows}
    results = []
    for label in (GROSS_PROFIT, NET_PROFIT):
        values = [found.get((entity, label)) for entity in companies]
        results.append(None if None in values else sum(values, ZERO))  # type: ignore[arg-type]
    return results[0], results[1]


def _profit_before(
    session: Session, companies: list[int], previous_year_end: date
) -> tuple[Decimal | None, Decimal | None]:
    """The profit to deduct: at the previous year end, or nothing for companies whose books
    begin after it."""
    started = [
        entity
        for entity, books_from in session.execute(
            select(A.Entity.id, A.Entity.books_from).where(A.Entity.id.in_(companies))
        )
        if books_from is not None and books_from <= previous_year_end
    ]
    if not started:
        return ZERO, ZERO
    return _profit(session, started, previous_year_end)


def _less(now: Decimal | None, before: Decimal | None) -> Decimal | None:
    return None if now is None or before is None else now - before


def _monthly_sales(
    session: Session, companies: list[int], start: date, end: date
) -> list[tuple[date, Decimal]]:
    """Net sales per month from the same entries as `sales` (the last month up to `end`);
    for whole months they equal `v_monthly_sales`."""
    year = func.year(A.VoucherLine.voucher_date)
    month = func.month(A.VoucherLine.voucher_date)
    query = (
        _effective_lines(companies, (SALES,))
        .add_columns(year, month)
        .where(A.VoucherLine.voucher_date >= start, A.VoucherLine.voucher_date <= end)
        .group_by(year, month)
        .order_by(year, month)
    )
    return [(date(int(y), int(m), 1), -Decimal(net or 0)) for net, y, m in session.execute(query)]
