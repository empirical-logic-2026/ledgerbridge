"""Current assets, current liabilities and borrowings in the form of Schedule III (Companies
Act 2013), for the current ratio, the quick ratio and debt to equity (F-RAT-008 to F-RAT-010,
parts F-BS-007 to F-BS-009 in docs/formula-sheet.md).

The source's Balance Sheet nets each group: a debtor in credit makes the debtors smaller, a
creditor in debit (an advance paid) makes the creditors smaller, and Bank OD A/c sits under
Loans (Liability), not under Current Liabilities. Schedule III shows each balance on its own
side instead. So every ledger is classified on its own, by the predefined role of its group
(at any depth) and the sign of its balance at the date:

Ledger under (debit balance -> credit balance):
- Stock-in-Hand: left out; the closing stock is added once, below.
- Bank OD A/c: bank balances -> short-term borrowings.
- Loans (Liability), marked short-term: other current assets -> short-term borrowings.
- Loans (Liability), other: left out -> borrowings, not current.
- Bank Accounts: bank balances -> short-term borrowings.
- Sundry Debtors: trade receivables -> advances from customers.
- Sundry Creditors: advances to suppliers -> trade payables.
- Current Assets, other: cash, deposits, loans and advances or other -> other liabilities.
- Current Liabilities, other: other current assets -> duties and taxes, provisions or other.

Closing stock is added once, at the source's closing value stored for the date (as the
stored Balance Sheet takes it); without one, at the Stock-in-Hand ledgers' balances.
Balances are the stored Balance Sheet's: the opening plus the effective entries up to the
date, with a foreign-currency ledger at the source's revalued balance where one is stored.
Several companies are classified each on its own, then added up, without inter-company
eliminations. A ledger under Loans (Liability) is short-term when it is under Bank OD A/c or
marked (`short_term_borrowings`, `./dev.ps1 loans mark`).
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import accounting as A  # noqa: N812
from core.statements import ledger_balances

ZERO = Decimal(0)

# The parts, in the order the ratio tiles list them: key -> label.
ASSET_PARTS = {
    "cash": "Cash in hand",
    "bank": "Bank balances",
    "deposits": "Deposits",
    "loans_advances": "Loans and advances",
    "receivables": "Trade receivables (debtors in debit)",
    "supplier_advances": "Advances to suppliers (creditors in debit)",
    "stock": "Closing stock",
    "other_assets": "Other current assets",
}
LIABILITY_PARTS = {
    "payables": "Trade payables (creditors in credit)",
    "customer_advances": "Advances from customers (debtors in credit)",
    "short_term_borrowings": "Short-term borrowings (Bank OD, banks in credit, marked loans)",
    "duties_taxes": "Duties and taxes",
    "provisions": "Provisions",
    "other_liabilities": "Other current liabilities",
}
BORROWING_PARTS = {
    "short_term_borrowings": "Short-term borrowings",
    "long_term_borrowings": "Other loans (Loans (Liability), not short-term)",
}

_ASSET_SUB_PARTS = {
    "cash_in_hand": "cash",
    "deposits_asset": "deposits",
    "loans_advances_asset": "loans_advances",
}
_LIABILITY_SUB_PARTS = {"duties_taxes": "duties_taxes", "provisions": "provisions"}


@dataclass
class Position:
    """The parts at one date, for the companies added up (amounts positive)."""

    assets: dict[str, Decimal] = field(default_factory=lambda: defaultdict(lambda: ZERO))
    liabilities: dict[str, Decimal] = field(default_factory=lambda: defaultdict(lambda: ZERO))
    borrowings: dict[str, Decimal] = field(default_factory=lambda: defaultdict(lambda: ZERO))
    marked: int = 0  # ledgers marked as short-term in these companies
    equity: Decimal | None = None  # Capital Account + Profit & Loss A/c (core/balance_sheet.py)

    @property
    def current_assets(self) -> Decimal:
        return sum(self.assets.values(), ZERO)

    @property
    def current_liabilities(self) -> Decimal:
        return sum(self.liabilities.values(), ZERO)

    @property
    def stock(self) -> Decimal:
        return self.assets.get("stock", ZERO)

    @property
    def total_borrowings(self) -> Decimal:
        return sum(self.borrowings.values(), ZERO)


def classify(roles: set[str], balance: Decimal, marked: bool) -> tuple[str, str] | None:
    """Where a ledger's balance goes (debit positive): ("asset" | "liability" | "borrowing",
    part), or None when it is left out (F-BS-007, F-BS-008)."""
    debit = balance > 0
    if balance == 0 or "stock_in_hand" in roles:
        return None
    if "bank_od_a_c" in roles or ("loans_liability" in roles and marked):
        if debit:
            return ("asset", "bank" if "bank_od_a_c" in roles else "other_assets")
        return ("liability", "short_term_borrowings")
    if "loans_liability" in roles:
        return None if debit else ("borrowing", "long_term_borrowings")
    if "bank_accounts" in roles:
        return ("asset", "bank") if debit else ("liability", "short_term_borrowings")
    if "sundry_debtors" in roles:
        return ("asset", "receivables") if debit else ("liability", "customer_advances")
    if "sundry_creditors" in roles:
        return ("asset", "supplier_advances") if debit else ("liability", "payables")
    if "current_assets" in roles:
        if not debit:
            return ("liability", "other_liabilities")
        found = next((_ASSET_SUB_PARTS[r] for r in _ASSET_SUB_PARTS if r in roles), "other_assets")
        return ("asset", found)
    if "current_liabilities" in roles:
        if debit:
            return ("asset", "other_assets")
        found = next(
            (_LIABILITY_SUB_PARTS[r] for r in _LIABILITY_SUB_PARTS if r in roles),
            "other_liabilities",
        )
        return ("liability", found)
    return None


def position(session: Session, companies: list[int], on: date) -> Position:
    """Current assets, current liabilities and borrowings at the date (F-BS-007 to F-BS-009)."""
    found = Position()
    for entity_id in companies:
        _add_company(session, entity_id, on, found)
    return found


def _add_company(session: Session, entity_id: int, on: date, found: Position) -> None:
    roles = _roles_by_key(session, entity_id)
    marked = marked_ledgers(session, [entity_id])
    found.marked += len(marked)
    revalued = _revalued(session, entity_id, on)
    stock_ledgers = ZERO
    for ledger in ledger_balances(session, entity_id, on):
        ledger_roles = {roles[k] for k in ledger.groups if roles.get(k)}
        balance = revalued.get(ledger.id, ledger.balance)
        if "stock_in_hand" in ledger_roles:
            stock_ledgers += balance
            continue
        placed = classify(ledger_roles, balance, ledger.id in marked)
        if placed is None:
            continue
        side, part = placed
        if side == "asset":
            found.assets[part] += balance
        else:
            amount = -balance
            if side == "liability":
                found.liabilities[part] += amount
            if part in BORROWING_PARTS:
                found.borrowings[part] += amount
    stored = _stored_closing_stock(session, entity_id, on)
    stock = stored if stored is not None else stock_ledgers
    if stock:
        found.assets["stock"] += stock


def marked_ledgers(session: Session, companies: list[int]) -> set[int]:
    """Ids of the ledgers marked as short-term borrowings in these companies."""
    return set(
        session.scalars(
            select(A.ShortTermBorrowing.ledger_id).where(
                A.ShortTermBorrowing.entity_id.in_(companies)
            )
        )
    )


def _roles_by_key(session: Session, entity_id: int) -> dict[str, str | None]:
    """Group source key -> predefined role (None for the client's own groups)."""
    rows = session.execute(
        select(A.AccountGroup.source_key, A.AccountGroup.predefined_role).where(
            A.AccountGroup.entity_id == entity_id, A.AccountGroup.is_deleted.is_(False)
        )
    )
    return {key: role for key, role in rows}


def _revalued(session: Session, entity_id: int, on: date) -> dict[int, Decimal]:
    """Foreign-currency ledgers at the source's revalued balance stored for the date."""
    rows = session.execute(
        select(A.FxRevaluationSnapshot.ledger_id, A.FxRevaluationSnapshot.revalued_value).where(
            A.FxRevaluationSnapshot.entity_id == entity_id, A.FxRevaluationSnapshot.as_of == on
        )
    )
    return {ledger_id: Decimal(value) for ledger_id, value in rows}


def _stored_closing_stock(session: Session, entity_id: int, on: date) -> Decimal | None:
    value = session.scalar(
        select(A.StockValue.closing_value).where(
            A.StockValue.entity_id == entity_id,
            A.StockValue.as_of == on,
            A.StockValue.scope == "total",
        )
    )
    return None if value is None else Decimal(value)
