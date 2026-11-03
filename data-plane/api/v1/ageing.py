"""`GET /api/v1/ageing/{customers|vendors}`: receivables and payables with ageing (RPT-004,
RPT-014; docs/design/dashboard.md Section 0.4), as at the period's end.

For any combination of the companies the caller may see (`company`, repeatable; default all,
combined) and a period (`month`, repeatable, or `date_from` and `date_to`): each party, known by
name across those companies, with its balance due, its outstanding bills by bucket and what
the bills don't cover (opening bills aren't stored yet). How: core/ageing.py.
"""

from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.access import CurrentAccess
from api.v1.common import ReportSession, formula, parse_period
from core.ageing import BUCKETS, AgeingRow, ageing

router = APIRouter(prefix="/ageing", tags=["ageing"])


class Buckets(BaseModel):
    """Outstanding bills by days past due (F-PTY-012)."""

    not_due: Decimal = formula("F-PTY-012")
    days_1_30: Decimal = formula("F-PTY-012")
    days_31_60: Decimal = formula("F-PTY-012")
    days_61_90: Decimal = formula("F-PTY-012")
    over_90: Decimal = formula("F-PTY-012")


class AgeingRowOut(BaseModel):
    party_id: int
    name: str
    balance: Decimal = formula("F-PTY-001")
    buckets: Buckets
    overdue: Decimal = formula("F-PTY-002")
    uncovered: Decimal = formula("F-PTY-013")  # the balance the stored bills don't cover
    status: Literal["overdue", "current"]


class AgeingOut(BaseModel):
    kind: str
    companies: list[int]
    combined: bool
    as_of: date
    rows: list[AgeingRowOut]
    total: AgeingRowOut  # every row added up (party_id 0)


def _row(r: AgeingRow) -> AgeingRowOut:
    return AgeingRowOut(
        party_id=r.party_id,
        name=r.name,
        balance=r.balance,
        buckets=Buckets(**r.buckets),
        overdue=r.overdue,
        uncovered=r.uncovered,
        status="overdue" if r.overdue > 0 else "current",
    )


@router.get("/{kind}")
def ageing_of(
    kind: Literal["customers", "vendors"],
    session: ReportSession,
    access: CurrentAccess,
    company: list[int] | None = Query(default=None),  # noqa: B008
    month: list[str] | None = Query(default=None),  # noqa: B008
    date_from: date | None = None,
    date_to: date | None = None,
) -> AgeingOut:
    companies = access.entities(company)
    period = parse_period(month, date_from, date_to)
    rows = ageing(session, companies, period.end, kind)
    total = AgeingRow(0, "Total", sum((r.balance for r in rows), Decimal(0)))
    for r in rows:
        for b in BUCKETS:
            total.buckets[b] += r.buckets[b]
    return AgeingOut(
        kind=kind,
        companies=companies,
        combined=len(companies) > 1,
        as_of=period.end,
        rows=[_row(r) for r in rows],
        total=_row(total),
    )
