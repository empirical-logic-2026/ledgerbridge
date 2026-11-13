"""`GET /api/v1/day-book`: the Day Book page (Books › Day Book; ADR-057): every voucher of the
period as the source's Day Book lists it, optionally only some voucher types or parties, and
the vouchers of each type. Read only; only the companies the caller may see. How:
core/day_book.py.
"""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.access import CurrentAccess
from api.v1.common import ReportSession, formula, parse_period
from core.day_book import day_book

router = APIRouter(prefix="/day-book", tags=["day-book"])


class DayBookRowOut(BaseModel):
    voucher_id: int  # opens the voucher page
    company: int
    date: date
    particulars: str
    voucher_type: str
    number: str | None
    debit: Decimal | None = formula("F-DAY-001")
    credit: Decimal | None = formula("F-DAY-001")
    inward: Decimal | None = formula("F-DAY-001")  # a stock voucher's quantity
    outward: Decimal | None = formula("F-DAY-001")
    unit: str | None
    narration: str | None
    party: str | None
    tags: list[str]  # optional, memorandum, order: vouchers that don't change the books


class DayBookCountOut(BaseModel):
    voucher_type: str
    vouchers: int = formula("F-DAY-002")


class DayBookOut(BaseModel):
    companies: list[int]
    period_start: date
    period_end: date
    rows: list[DayBookRowOut]
    counts: list[DayBookCountOut]  # every voucher of the period, by type (not filtered)
    voucher_types: list[str]  # the types in the period, for the filter
    parties: list[str]  # the parties in the period, for the filter
    truncated: bool  # more vouchers than shown


@router.get("")
def day_book_page(
    session: ReportSession,
    access: CurrentAccess,
    company: list[int] | None = Query(default=None),  # noqa: B008
    month: list[str] | None = Query(default=None),  # noqa: B008
    date_from: date | None = None,
    date_to: date | None = None,
    voucher_type: list[str] | None = Query(default=None, max_length=50),  # noqa: B008
    party: list[str] | None = Query(default=None, max_length=50),  # noqa: B008
) -> DayBookOut:
    companies = access.entities(company)
    period = parse_period(month, date_from, date_to)
    found = day_book(session, companies, period)
    types, parties = set(voucher_type or []), set(party or [])
    rows = [
        r
        for r in found.rows
        if (not types or r.voucher_type in types) and (not parties or r.party in parties)
    ]
    return DayBookOut(
        companies=companies, period_start=period.start, period_end=period.end,
        rows=[
            DayBookRowOut(
                voucher_id=r.voucher_id, company=r.company, date=r.on, particulars=r.particulars,
                voucher_type=r.voucher_type, number=r.number, debit=r.debit, credit=r.credit,
                inward=r.inward, outward=r.outward, unit=r.unit, narration=r.narration,
                party=r.party, tags=r.tags,
            )
            for r in rows
        ],
        counts=[
            DayBookCountOut(voucher_type=t, vouchers=n) for t, n in sorted(found.counts.items())
        ],
        voucher_types=sorted({r.voucher_type for r in found.rows}),
        parties=sorted({r.party for r in found.rows if r.party}),
        truncated=found.truncated,
    )  # fmt: skip
