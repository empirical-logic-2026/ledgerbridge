"""`GET /api/v1/ledgers` and `GET /api/v1/ledgers/{ledger_id}/statement`: the Ledger
statement page (Books › Ledger statement; ADR-055). The list finds a ledger by name for the
page's picker; the statement is one ledger's opening, entries with the running balance and
closing for the period. A ledger outside the companies the caller may see (or deleted) is
404, like a voucher. Read only. How: core/ledger_statement.py.
"""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from api.access import CurrentAccess
from api.v1.common import ReportSession, formula, parse_period
from core.ledger_statement import ledger_statement
from core.models import accounting as A  # noqa: N812

router = APIRouter(prefix="/ledgers", tags=["ledgers"])
LIST_LIMIT = 50


class LedgerOut(BaseModel):
    ledger_id: int
    name: str
    group: str
    company: int


class LedgerEntryOut(BaseModel):
    voucher_id: int | None  # None: the source's calculated revaluation row
    date: date
    voucher_type: str
    number: str | None
    particulars: str
    narration: str | None
    debit: Decimal | None = formula("F-LED-002")
    credit: Decimal | None = formula("F-LED-002")
    balance: Decimal = formula("F-LED-003")  # debit positive


class LedgerStatementOut(BaseModel):
    ledger_id: int
    name: str
    company: int
    groups: list[str]  # its group and those above, top first
    period_start: date
    period_end: date
    opening: Decimal = formula("F-LED-001")  # debit positive
    entries: list[LedgerEntryOut]
    total_debit: Decimal = formula("F-LED-002")
    total_credit: Decimal = formula("F-LED-002")
    closing: Decimal = formula("F-LED-004")  # debit positive
    truncated: bool  # more entries than shown; the totals cover them all


@router.get("")
def ledgers(
    session: ReportSession,
    access: CurrentAccess,
    company: list[int] | None = Query(default=None),  # noqa: B008
    q: str = Query(default="", max_length=100),
) -> list[LedgerOut]:
    """Ledgers whose name contains the text (the first 50, by name)."""
    companies = access.entities(company)
    query = (
        select(A.Ledger.id, A.Ledger.name, A.AccountGroup.name, A.Ledger.entity_id)
        .join(A.AccountGroup, A.AccountGroup.id == A.Ledger.group_id)
        .where(A.Ledger.entity_id.in_(companies), A.Ledger.is_deleted.is_(False))
        .order_by(A.Ledger.name, A.Ledger.entity_id)
        .limit(LIST_LIMIT)
    )
    if q.strip():
        query = query.where(A.Ledger.name.contains(q.strip(), autoescape=True))
    return [
        LedgerOut(ledger_id=lid, name=name, group=group, company=entity)
        for lid, name, group, entity in session.execute(query)
    ]


@router.get("/{ledger_id}/statement")
def statement(
    ledger_id: int,
    session: ReportSession,
    access: CurrentAccess,
    month: list[str] | None = Query(default=None),  # noqa: B008
    date_from: date | None = None,
    date_to: date | None = None,
) -> LedgerStatementOut:
    period = parse_period(month, date_from, date_to)
    owner = session.scalar(select(A.Ledger.entity_id).where(A.Ledger.id == ledger_id))
    found = None
    if owner is not None and owner in access.entities(None):
        found = ledger_statement(session, ledger_id, period)
    if found is None:
        raise HTTPException(404, "No such ledger in the companies you can see.")
    return LedgerStatementOut(
        ledger_id=found.ledger_id, name=found.name, company=found.company, groups=found.groups,
        period_start=period.start, period_end=period.end, opening=found.opening,
        entries=[
            LedgerEntryOut(
                voucher_id=e.voucher_id, date=e.on, voucher_type=e.voucher_type,
                number=e.number, particulars=e.particulars, narration=e.narration,
                debit=e.amount if e.amount > 0 else None,
                credit=-e.amount if e.amount < 0 else None, balance=e.running,
            )
            for e in found.entries
        ],
        total_debit=found.debit, total_credit=found.credit, closing=found.closing,
        truncated=found.truncated,
    )  # fmt: skip
