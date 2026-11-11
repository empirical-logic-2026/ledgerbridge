"""The Cash Flow module, a simple cash movement (RPT-014; docs/design/dashboard.md Section 0.4):
the money into and out of cash and bank in a period, by what it was for. Source-independent;
formulas F-CF-001 and F-CF-002 in docs/formula-sheet.md. The full statement (operating, investing,
financing) needs every ledger classified and is planned separately.

- **Opening and closing:** cash and bank (F-BAL-002) the day before the period and at its end.
- **Movements** (F-CF-001): every effective entry on the ledgers under Cash-in-Hand and Bank
  Accounts in the period, by voucher. A voucher's cash amount goes to the categories of its
  other ledgers (the nearest group with a known predefined role: customers, suppliers, income,
  expenses, taxes, loans, capital, fixed assets and investments, else other), split by their
  amounts, so a voucher with one other ledger is exact. A voucher with only cash and bank
  ledgers (a transfer, e.g. a contra) is "transfers", which nets to nothing.
- Opening + every movement = closing, exactly: the split's rounding remainder goes to the
  largest part.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.home import CASH_AND_BANK, balance, in_period, ledgers_under
from core.models import accounting as A  # noqa: N812
from core.report_periods import Period
from core.reporting_views import GROUP_ANCESTORS

ZERO = Decimal(0)
PAISA = Decimal("0.0001")
TRANSFERS, OTHER = "transfers", "other"
CATEGORIES: dict[str, str] = {
    # predefined role -> category
    "sundry_debtors": "customers",
    "sundry_creditors": "suppliers",
    "sales_accounts": "income",
    "direct_incomes": "income",
    "indirect_incomes": "income",
    "purchase_accounts": "expenses",
    "direct_expenses": "expenses",
    "indirect_expenses": "expenses",
    "duties_taxes": "taxes",
    "loans_liability": "loans",
    "secured_loans": "loans",
    "unsecured_loans": "loans",
    "bank_od_a_c": "loans",
    "bank_occ_a_c": "loans",
    "capital_account": "capital",
    "reserves_surplus": "capital",
    "fixed_assets": "assets",
    "investments": "assets",
}
LABELS = {
    "customers": "Customers",
    "suppliers": "Suppliers",
    "income": "Sales and other income",
    "expenses": "Purchases and expenses",
    "taxes": "Taxes",
    "loans": "Loans",
    "capital": "Capital",
    "assets": "Fixed assets and investments",
    TRANSFERS: "Transfers between cash and bank",
    OTHER: "Other",
}


@dataclass
class Movement:
    key: str
    label: str
    inflow: Decimal = ZERO
    outflow: Decimal = ZERO  # positive

    @property
    def net(self) -> Decimal:
        return self.inflow - self.outflow


@dataclass
class CashFlow:
    opening: Decimal
    closing: Decimal
    movements: list[Movement]  # in the order of LABELS, only those with money
    monthly: list[tuple[date, Decimal, Decimal]] = field(default_factory=list)  # in, out


def cash_flow(session: Session, companies: list[int], period: Period) -> CashFlow:
    cash = set(session.scalars(ledgers_under(companies, CASH_AND_BANK)))
    lines = _voucher_lines(session, companies, period, cash)
    categories = _categories(session, {ledger for rows in lines.values() for ledger, _ in rows[1]})
    moved = {key: Movement(key, label) for key, label in LABELS.items()}
    monthly: dict[date, list[Decimal]] = {m: [ZERO, ZERO] for m in period.month_starts()}
    for (on, cash_amount), others in lines.values():
        month = on.replace(day=1)
        if cash_amount > 0:
            monthly.setdefault(month, [ZERO, ZERO])[0] += cash_amount
        else:
            monthly.setdefault(month, [ZERO, ZERO])[1] -= cash_amount
        for key, part in split(cash_amount, others, categories):
            if part > 0:
                moved[key].inflow += part
            else:
                moved[key].outflow -= part
    opening = balance(session, companies, CASH_AND_BANK, period.start - timedelta(days=1))
    return CashFlow(
        opening=opening,
        closing=balance(session, companies, CASH_AND_BANK, period.end),
        movements=[m for m in moved.values() if m.inflow or m.outflow],
        monthly=[(m, i, o) for m, (i, o) in sorted(monthly.items())],
    )


def _voucher_lines(
    session: Session, companies: list[int], period: Period, cash: set[int]
) -> dict[int, tuple[tuple[date, Decimal], list[tuple[int, Decimal]]]]:
    """Each voucher touching cash or bank in the period: (its date, its cash amount, debit
    positive) and its other ledgers' entries."""
    if not cash:
        return {}
    touching = in_period(
        select(A.VoucherLine.voucher_id).where(
            A.VoucherLine.entity_id.in_(companies),
            A.VoucherLine.is_effective.is_(True),
            A.VoucherLine.ledger_id.in_(cash),
        ),
        period,
    )
    rows = session.execute(
        select(
            A.VoucherLine.voucher_id, A.VoucherLine.voucher_date,
            A.VoucherLine.ledger_id, A.VoucherLine.amount,
        )
        .join(A.Voucher, A.Voucher.id == A.VoucherLine.voucher_id)
        .where(
            A.VoucherLine.voucher_id.in_(touching),
            A.VoucherLine.is_effective.is_(True),
            A.Voucher.is_deleted.is_(False),
        )
    )  # fmt: skip
    found: dict[int, tuple[tuple[date, Decimal], list[tuple[int, Decimal]]]] = {}
    for voucher, on, ledger, amount in rows:
        (day, total), others = found.get(voucher, ((on, ZERO), []))
        if ledger in cash:
            total += Decimal(amount)
        else:
            others.append((ledger, Decimal(amount)))
        found[voucher] = ((day, total), others)
    return {v: lines for v, lines in found.items() if lines[0][1] != 0 or not lines[1]}


def _categories(session: Session, ledgers: set[int]) -> dict[int, str]:
    """Each ledger's category: the nearest of its groups with a role in CATEGORIES."""
    if not ledgers:
        return {}
    rows = session.execute(
        select(A.Ledger.id, A.AccountGroup.predefined_role, GROUP_ANCESTORS.c.depth)
        .join(GROUP_ANCESTORS, GROUP_ANCESTORS.c.group_id == A.Ledger.group_id)
        .join(A.AccountGroup, A.AccountGroup.id == GROUP_ANCESTORS.c.ancestor_id)
        .where(A.Ledger.id.in_(ledgers), A.AccountGroup.predefined_role.in_(list(CATEGORIES)))
    )
    nearest: dict[int, tuple[int, str]] = {}
    for ledger, role, depth in rows:
        if ledger not in nearest or depth < nearest[ledger][0]:
            nearest[ledger] = (depth, CATEGORIES[role])
    return {ledger: category for ledger, (_, category) in nearest.items()}


def split(
    cash_amount: Decimal, others: list[tuple[int, Decimal]], categories: dict[int, str]
) -> list[tuple[str, Decimal]]:
    """The voucher's cash amount by its other ledgers' categories, in proportion to their
    entries; exactly the cash amount in total (the remainder goes to the largest part)."""
    if not others:
        return [(TRANSFERS, cash_amount)]
    weights: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for ledger, amount in others:
        weights[categories.get(ledger, OTHER)] += abs(amount)
    total = sum(weights.values(), ZERO)
    if total == 0:
        return [(OTHER, cash_amount)]
    parts = {
        key: (cash_amount * weight / total).quantize(PAISA, ROUND_HALF_UP)
        for key, weight in weights.items()
    }
    largest = max(parts, key=lambda key: abs(parts[key]))
    parts[largest] += cash_amount - sum(parts.values(), ZERO)
    return list(parts.items())
