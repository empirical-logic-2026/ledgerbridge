"""The Overview's figures beyond the home page's (RPT-014; docs/design/dashboard.md Section
0.4): the key cards' twelve-month trends (sparklines) and the top customers with their balance
due and what is overdue. Source-independent; every formula in docs/formula-sheet.md.

- **Trend** (F-OVR-001): the twelve months up to the period's end month. Each month's net sales
  (F-SAL-004), gross and net profit (F-PL-003, F-PL-004: none for a month without its stored
  statements), cash and bank at the month's end (F-BAL-002, or the period's end in its last
  month) and customers (F-SAL-011).
- **Top customers** (F-OVR-002): the customers, known by name across the companies, with the
  largest net sales in the period; each with its balance due (F-PTY-001) and overdue
  (F-PTY-002) at the period's end, plus the outstanding bill states for the status summary.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from core.home import CASH_AND_BANK, balance, monthly_profit
from core.models import accounting as A  # noqa: N812
from core.parties import KINDS, due_and_overdue, find_party
from core.report_periods import Period, books_start, last_day, months_earlier, stored_dates
from core.sales import SALES_SIDE, Facets, lines, monthly_totals, split_columns, to_totals

ZERO = Decimal(0)
TREND_MONTHS = 12
TOP = 10


@dataclass
class TrendMonth:
    month: date
    net_sales: Decimal
    gross_profit: Decimal | None
    net_profit: Decimal | None
    cash_and_bank: Decimal
    customers: int


@dataclass
class TopCustomer:
    party_id: int
    name: str
    net_sales: Decimal
    balance: Decimal  # due at the period's end
    overdue: Decimal
    pending: Decimal
    advance: Decimal


def trend_period(end: date) -> Period:
    """The twelve whole months up to the end's month."""
    last = end.replace(day=1)
    return Period.of_months([months_earlier(last, n) for n in range(TREND_MONTHS)])


def trend(session: Session, companies: list[int], end: date) -> list[TrendMonth]:
    period = trend_period(end)
    stored = stored_dates(session, companies)
    profit = monthly_profit(session, companies, period, stored, books_start(session, companies))
    sales = dict(monthly_totals(session, companies, period, Facets(), SALES_SIDE))
    customers = _customers_by_month(session, companies, period)
    found = []
    for month in period.months:
        figures = profit.get(month)
        known = figures is not None and figures.reason is None
        month_end = min(last_day(month), end)
        found.append(
            TrendMonth(
                month=month,
                net_sales=sales[month].net,
                gross_profit=figures.values.get("gross_profit") if known else None,
                net_profit=figures.values.get("net_profit") if known else None,
                cash_and_bank=balance(session, companies, CASH_AND_BANK, month_end),
                customers=customers.get(month, 0),
            )
        )
    return found


def _customers_by_month(session: Session, companies: list[int], period: Period) -> dict[date, int]:
    year, month = func.year(A.VoucherLine.voucher_date), func.month(A.VoucherLine.voucher_date)
    named = func.count(func.distinct(A.Party.name))
    query = (
        lines(companies, period, Facets(), SALES_SIDE, year, month, named)
        .join(A.Party, A.Party.id == A.Voucher.party_id)
        .group_by(year, month)
    )
    return {date(int(y), int(m), 1): int(n) for y, m, n in session.execute(query)}


def top_customers(session: Session, companies: list[int], period: Period) -> list[TopCustomer]:
    query = (
        lines(
            companies, period, Facets(), SALES_SIDE,
            A.Party.name, func.min(A.Party.id), *split_columns(SALES_SIDE),
        )
        .join(A.Party, A.Party.id == A.Voucher.party_id)
        .group_by(A.Party.name)
    )  # fmt: skip
    ranked = sorted(
        (
            (name, int(party_id), to_totals(SALES_SIDE, *split).net)
            for name, party_id, *split in session.execute(query)
        ),
        key=lambda row: (-row[2], row[0]),
    )[:TOP]
    sign = KINDS["customers"][3]
    found = []
    for name, party_id, net in ranked:
        party = find_party(session, companies, party_id)
        if party is None:
            continue
        due, overdue, pending, advance = due_and_overdue(session, party, period.end, sign)
        found.append(TopCustomer(party.id, name, net, due, overdue, pending, advance))
    return found
