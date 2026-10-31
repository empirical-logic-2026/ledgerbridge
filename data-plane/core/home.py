"""The dashboard home's figures (D1; RPT-001, RPT-006, RPT-008; docs/design/dashboard.md
Section 0.1) for any combination of companies and a period (core/report_periods.py).
Source-independent: groups are found by their predefined role (`predefined_role`, ADR-047),
never by name; amounts in the base currency, as the books keep them. Several companies are
added together: combined, without inter-company eliminations.

- **Profit & Loss card** (net sales, cost of sales, gross profit, net profit): our stored
  Profit & Loss (validated against the source's), over the period's statement windows. Net
  sales is the Sales Accounts line; cost of sales the other lines above gross profit that
  aren't income (the source's Cost of Sales block, or its purchase and direct expense lines
  when there is no stock).
- **Balance Sheet card** at the end of the last window: total assets (the assets side),
  current assets, current liabilities, capital and reserves (the capital account and the
  Profit & Loss A/c).
- **Stock value:** the source's closing stock stored for that date.
- **Cash and bank, receivables, payables:** each ledger's opening plus its effective entries
  up to the period's end (Cash-in-Hand and Bank Accounts, Sundry Debtors, Sundry Creditors).
- **Charts:** sales and purchases per month, sales per voucher type (channel) and per
  company, from the effective entries of the period itself (exact for any period).
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models import accounting as A  # noqa: N812
from core.models.reporting import StatementLine
from core.report_periods import Period, Windows, books_start, stored_dates, windows
from core.reporting_views import GROUP_ANCESTORS
from core.statements import GROSS_PROFIT, NET_PROFIT, PROFIT_LOSS_ACCOUNT, match_key

ZERO = Decimal(0)
SALES, PURCHASES = "sales_accounts", "purchase_accounts"
CASH_AND_BANK = ("cash_in_hand", "bank_accounts")
RECEIVABLES, PAYABLES = "sundry_debtors", "sundry_creditors"
CURRENT_ASSETS, CURRENT_LIABILITIES, CAPITAL = (
    "current_assets", "current_liabilities", "capital_account",
)  # fmt: skip
PL_FIGURES = ("net_sales", "cost_of_sales", "gross_profit", "net_profit")
BS_FIGURES = ("total_assets", "current_assets", "current_liabilities", "capital_and_reserves")


@dataclass
class StatementFigures:
    """Figures taken from stored statements, or why they aren't available."""

    values: dict[str, Decimal] = field(default_factory=dict)
    as_of: date | None = None  # the (last) statement date used
    shifted: bool = False  # a month ran to a later stored date (Educational mode)
    reason: str | None = None


@dataclass
class Home:
    period: Period
    profit_loss: StatementFigures
    profit_loss_last_year: StatementFigures | None
    balance_sheet: StatementFigures
    stock_value: Decimal | None
    cash_and_bank: Decimal
    receivables: Decimal
    payables: Decimal
    monthly: list[tuple[date, Decimal, Decimal]]  # month, sales, purchases
    channels: list[tuple[str, Decimal]]  # voucher type, net sales (largest first)
    by_company: list[tuple[int, Decimal]]  # entity id, net sales


def home(session: Session, companies: list[int], period: Period, compare: bool) -> Home:
    stored = stored_dates(session, companies)
    books_from = books_start(session, companies)
    found = windows(period, stored, books_from)
    profit_loss = profit_loss_figures(session, companies, found)
    last_year = None
    if compare:
        last_year = profit_loss_figures(
            session, companies, windows(period.last_year(), stored, books_from)
        )
    sheet = balance_sheet_figures(session, companies, found.end, found.reason)
    return Home(
        period=period,
        profit_loss=profit_loss,
        profit_loss_last_year=last_year,
        balance_sheet=sheet,
        stock_value=_stock_value(session, companies, found.end) if found.available else None,
        cash_and_bank=balance(session, companies, CASH_AND_BANK, period.end),
        receivables=balance(session, companies, (RECEIVABLES,), period.end),
        payables=-balance(session, companies, (PAYABLES,), period.end),
        monthly=_monthly(session, companies, period),
        channels=_channels(session, companies, period),
        by_company=_by_company(session, companies, period),
    )


# --- from the stored statements ----------------------------------------------------------


def profit_loss_figures(session: Session, companies: list[int], found: Windows) -> StatementFigures:
    if not found.available:
        return StatementFigures(reason=found.reason)
    totals: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for before, end in found.pairs:
        now = _profit_loss_at(session, companies, end)
        earlier = _profit_loss_at(session, companies, before) if before else {}
        for key in PL_FIGURES:
            totals[key] += now.get(key, ZERO) - earlier.get(key, ZERO)
    return StatementFigures(dict(totals), found.end, found.shifted)


def _profit_loss_at(session: Session, companies: list[int], on: date) -> dict[str, Decimal]:
    """Our Profit & Loss at the date (from the books' beginning), added up over the
    companies; a profit and sales positive."""
    roles = _primary_roles(session, companies)
    figures: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for entity, label, section, level, amount in _lines(session, companies, "profit_loss", on):
        role, nature = roles.get((entity, match_key(label)), (None, None))
        if label == GROSS_PROFIT:
            figures["gross_profit"] -= amount
        elif label == NET_PROFIT:
            figures["net_profit"] -= amount
        elif level == "main" and role == SALES:
            figures["net_sales"] -= amount
        if level == "main" and section == "gross" and nature != "income":
            figures["cost_of_sales"] += amount
    return figures


def balance_sheet_figures(
    session: Session, companies: list[int], on: date | None, reason: str | None
) -> StatementFigures:
    if on is None:
        return StatementFigures(reason=reason)
    roles = _primary_roles(session, companies)
    figures: dict[str, Decimal] = {key: ZERO for key in BS_FIGURES}
    for entity, label, section, level, amount in _lines(session, companies, "balance_sheet", on):
        if level != "main":
            continue
        role, _ = roles.get((entity, match_key(label)), (None, None))
        if section == "assets":
            figures["total_assets"] += amount
        if role == CURRENT_ASSETS:
            figures["current_assets"] += amount
        elif role == CURRENT_LIABILITIES:
            figures["current_liabilities"] -= amount
        elif role == CAPITAL or label == PROFIT_LOSS_ACCOUNT:
            figures["capital_and_reserves"] -= amount
    return StatementFigures(figures, on)


def _lines(session: Session, companies: list[int], statement: str, on: date) -> list[tuple]:
    return list(
        session.execute(
            select(
                StatementLine.entity_id,
                StatementLine.label,
                StatementLine.section,
                StatementLine.level,
                StatementLine.amount,
            ).where(
                StatementLine.entity_id.in_(companies),
                StatementLine.as_of == on,
                StatementLine.statement == statement,
                StatementLine.figures == "ours",
            )
        )
    )


def _primary_roles(session: Session, companies: list[int]) -> dict[tuple[int, str], tuple]:
    """(entity, line key) -> (predefined role, nature) of each primary group: statement lines
    are labelled with the group's current name."""
    rows = session.execute(
        select(
            A.AccountGroup.entity_id,
            A.AccountGroup.name,
            A.AccountGroup.predefined_role,
            A.AccountGroup.nature,
        ).where(A.AccountGroup.entity_id.in_(companies), A.AccountGroup.is_primary.is_(True))
    )
    return {(entity, match_key(name)): (role, nature) for entity, name, role, nature in rows}


def _stock_value(session: Session, companies: list[int], on: date | None) -> Decimal | None:
    """The source's closing stock stored for the date, added up; None unless every company
    has one."""
    rows = session.execute(
        select(A.StockValue.entity_id, A.StockValue.closing_value).where(
            A.StockValue.entity_id.in_(companies),
            A.StockValue.as_of == on,
            A.StockValue.scope == "total",
        )
    ).all()
    if {entity for entity, _ in rows} != set(companies):
        return None
    return sum((Decimal(value or 0) for _, value in rows), ZERO)


# --- from the entries --------------------------------------------------------------------


def ledgers_under(companies: list[int], roles: tuple[str, ...]):  # noqa: ANN201
    """Ids of the ledgers under the groups with these predefined roles, at any depth."""
    tops = select(A.AccountGroup.id).where(
        A.AccountGroup.entity_id.in_(companies), A.AccountGroup.predefined_role.in_(roles)
    )
    groups = select(GROUP_ANCESTORS.c.group_id).where(GROUP_ANCESTORS.c.ancestor_id.in_(tops))
    return select(A.Ledger.id).where(A.Ledger.group_id.in_(groups))


def _entries(companies: list[int], roles: tuple[str, ...], *columns: object):  # noqa: ANN202
    """The sum of the effective entries on those ledgers (debit positive), with `columns`."""
    return (
        select(func.coalesce(func.sum(A.VoucherLine.amount), 0), *columns)
        .join(A.Voucher, A.Voucher.id == A.VoucherLine.voucher_id)
        .where(
            A.VoucherLine.entity_id.in_(companies),
            A.VoucherLine.is_effective.is_(True),
            A.Voucher.is_deleted.is_(False),
            A.VoucherLine.ledger_id.in_(ledgers_under(companies, roles)),
        )
    )


def _in_period(query, period: Period):  # noqa: ANN001, ANN202
    day = A.VoucherLine.voucher_date
    query = query.where(day >= period.start, day <= period.end)
    if period.months:  # only the chosen months
        months = [m.year * 100 + m.month for m in period.months]
        query = query.where((func.year(day) * 100 + func.month(day)).in_(months))
    return query


def balance(session: Session, companies: list[int], roles: tuple[str, ...], on: date) -> Decimal:
    """The ledgers' openings plus their entries up to the date (debit positive)."""
    openings = select(func.coalesce(func.sum(A.Ledger.opening_balance), 0)).where(
        A.Ledger.id.in_(ledgers_under(companies, roles)), A.Ledger.is_deleted.is_(False)
    )
    entries = _entries(companies, roles).where(A.VoucherLine.voucher_date <= on)
    return Decimal(session.scalar(openings) or 0) + Decimal(session.scalar(entries) or 0)


def _monthly(
    session: Session, companies: list[int], period: Period
) -> list[tuple[date, Decimal, Decimal]]:
    year, month = func.year(A.VoucherLine.voucher_date), func.month(A.VoucherLine.voucher_date)
    found: dict[date, list[Decimal]] = {m: [ZERO, ZERO] for m in period.month_starts()}
    for index, roles, sign in ((0, (SALES,), -1), (1, (PURCHASES,), 1)):
        query = _in_period(_entries(companies, roles, year, month), period).group_by(year, month)
        for net, y, m in session.execute(query):
            found[date(int(y), int(m), 1)][index] = sign * Decimal(net or 0)
    return [(m, sales, purchases) for m, (sales, purchases) in sorted(found.items())]


def _channels(session: Session, companies: list[int], period: Period) -> list[tuple[str, Decimal]]:
    """Net sales per voucher type name (types of the same name in several companies
    together), largest first."""
    query = (
        _in_period(_entries(companies, (SALES,), A.VoucherType.name), period)
        .join(A.VoucherType, A.VoucherType.id == A.Voucher.voucher_type_id)
        .group_by(A.VoucherType.name)
    )
    found = [(name, -Decimal(net or 0)) for net, name in session.execute(query)]
    return sorted(found, key=lambda x: x[1], reverse=True)


def _by_company(
    session: Session, companies: list[int], period: Period
) -> list[tuple[int, Decimal]]:
    query = _in_period(_entries(companies, (SALES,), A.VoucherLine.entity_id), period).group_by(
        A.VoucherLine.entity_id
    )
    found = {int(entity): -Decimal(net or 0) for net, entity in session.execute(query)}
    return [(entity, found.get(entity, ZERO)) for entity in companies]
