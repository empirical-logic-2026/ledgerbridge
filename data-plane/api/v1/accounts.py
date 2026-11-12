"""`GET /api/v1/reports/trial-balance` and `GET /api/v1/reports/balance-sheet/drill`: the
Trial Balance page (P&L & KPIs › Trial Balance) and the Balance Sheet's drill-down (ADR-055).

Both are at the period's statement date: its end when a statement is stored for it, else the
last stored date within it (core/report_periods.py `windows`, as the Balance Sheet). The
selected companies are added up, without inter-company eliminations. Read only; amounts are
shown only for the companies the caller may see. How: core/trial_balance.py,
core/balance_sheet_drill.py.
"""

from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.access import CurrentAccess
from api.v1.common import ReportSession, formula, parse_period
from core.balance_sheet_drill import drill
from core.report_periods import Period, books_start, stored_dates, windows
from core.trial_balance import trial_balance

router = APIRouter(prefix="/reports", tags=["reports"])

RowKind = Literal["group", "ledger", "stock", "line", "difference"]


class TrialBalanceRowOut(BaseModel):
    key: str  # unique in the response; a group's names down the tree
    label: str
    kind: RowKind
    depth: int  # 0: a primary group or a line of its own
    parent: str | None
    debit: Decimal = formula("F-TB-001")
    credit: Decimal = formula("F-TB-001")
    ledger_id: int | None  # opens its Ledger statement
    company: int | None


class TrialBalanceOut(BaseModel):
    companies: list[int]
    combined: bool
    period_start: date
    period_end: date
    as_of: date | None  # the statement date the figures are at
    year_start: date | None  # the financial year shown; None: from the books' beginning
    rows: list[TrialBalanceRowOut]
    total_debit: Decimal = formula("F-TB-002")
    total_credit: Decimal = formula("F-TB-002")
    reason: str | None  # why there are no figures
    settings_missing: bool  # the statements must run again (netting and earlier profit)
    unproved: list[str]  # rows shown as the source's screen does, not yet proved


class DrillRowOut(BaseModel):
    key: str
    label: str
    kind: Literal["group", "ledger", "stock", "line"]
    depth: int  # 0: the Balance Sheet line itself
    parent: str | None
    amount: Decimal = formula("F-BS-012")
    ledger_id: int | None
    company: int | None


class DrillOut(BaseModel):
    companies: list[int]
    as_of: date | None
    line: str
    section: Literal["assets", "liabilities"]
    rows: list[DrillRowOut]
    reason: str | None


def _statement_date(session: ReportSession, companies: list[int], period: Period) -> tuple:
    found = windows(period, stored_dates(session, companies), books_start(session, companies))
    return found.end, found.reason


@router.get("/trial-balance")
def trial_balance_report(
    session: ReportSession,
    access: CurrentAccess,
    company: list[int] | None = Query(default=None),  # noqa: B008
    month: list[str] | None = Query(default=None),  # noqa: B008
    date_from: date | None = None,
    date_to: date | None = None,
) -> TrialBalanceOut:
    companies = access.entities(company)
    period = parse_period(month, date_from, date_to)
    on, reason = _statement_date(session, companies, period)
    base = {
        "companies": companies, "combined": len(companies) > 1,
        "period_start": period.start, "period_end": period.end,
    }  # fmt: skip
    if on is None:
        return TrialBalanceOut(
            **base, as_of=None, year_start=None, rows=[], total_debit=Decimal(0),
            total_credit=Decimal(0), reason=reason, settings_missing=False, unproved=[],
        )  # fmt: skip
    found = trial_balance(session, companies, on)
    return TrialBalanceOut(
        **base, as_of=found.as_of, year_start=found.year_start,
        rows=[
            TrialBalanceRowOut(
                key=r.key, label=r.label, kind=r.kind, depth=r.depth, parent=r.parent,
                debit=r.debit, credit=r.credit, ledger_id=r.ledger_id, company=r.company,
            )
            for r in found.rows
            if r.debit or r.credit
        ],
        total_debit=found.debit, total_credit=found.credit, reason=found.reason,
        settings_missing=found.settings_missing, unproved=found.unproved,
    )  # fmt: skip


@router.get("/balance-sheet/drill")
def balance_sheet_drill(
    session: ReportSession,
    access: CurrentAccess,
    line: str,
    company: list[int] | None = Query(default=None),  # noqa: B008
    month: list[str] | None = Query(default=None),  # noqa: B008
    date_from: date | None = None,
    date_to: date | None = None,
) -> DrillOut:
    companies = access.entities(company)
    period = parse_period(month, date_from, date_to)
    section = "assets" if line.startswith("assets:") else "liabilities"
    on, reason = _statement_date(session, companies, period)
    if on is None:
        return DrillOut(companies=companies, as_of=None, line=line, section=section, rows=[],
                        reason=reason)  # fmt: skip
    found = drill(session, companies, on, line)
    return DrillOut(
        companies=companies, as_of=found.as_of, line=found.line, section=section,
        rows=[
            DrillRowOut(
                key=r.key, label=r.label, kind=r.kind, depth=r.depth, parent=r.parent,
                amount=r.amount, ledger_id=r.ledger_id, company=r.company,
            )
            for r in found.rows
            if r.amount or r.depth == 0
        ],
        reason=found.reason,
    )  # fmt: skip
