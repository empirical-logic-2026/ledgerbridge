"""`GET /api/v1/registers/{side}`: the Sales register (`sales`: sales and credit notes) and the
Purchase register (`purchases`: purchases and debit notes), Day Book style (D2;
docs/design/dashboard.md Section 0.2).

For any combination of the companies the caller may see (`company`, repeatable; default all,
combined), a period (`month`, repeatable, or `date_from` and `date_to`) and the facets by name
(`party`, `voucher_type`, repeatable). One row per voucher, the earliest first, at most 20,000
(`truncated` says when there were more). How the rows are found: core/registers.py.
"""

from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.access import CurrentAccess
from api.v1.common import ReportSession, parse_period
from api.v1.home import PeriodOut
from api.v1.sales import facet_names
from core.registers import RegisterRow, register
from core.sales import PURCHASES_SIDE, SALES_SIDE, Facets, Side

router = APIRouter(prefix="/registers", tags=["registers"])
SIDES = {"sales": SALES_SIDE, "purchases": PURCHASES_SIDE}


class RegisterRowOut(BaseModel):
    voucher_id: int
    company: int
    date: date
    voucher_type: str
    is_return: bool  # a credit note (sales) or debit note (purchases)
    number: str
    ledger_id: int
    particulars: str  # the first ledger entry's ledger, as the source's Day Book shows
    party_id: int | None
    party: str | None
    debit: Decimal | None
    credit: Decimal | None
    side_value: Decimal  # on the Sales (Purchase) Accounts ledgers; returns negative
    narration: str | None


class RegisterOut(BaseModel):
    side: str
    companies: list[int]
    combined: bool
    period: PeriodOut
    rows: list[RegisterRowOut]
    truncated: bool  # more vouchers than shown: narrow the period


@router.get("/{side}")
def voucher_register(
    side: Literal["sales", "purchases"],
    session: ReportSession,
    access: CurrentAccess,
    company: list[int] | None = Query(default=None),  # noqa: B008
    month: list[str] | None = Query(default=None),  # noqa: B008
    date_from: date | None = None,
    date_to: date | None = None,
    party: list[str] | None = Query(default=None),  # noqa: B008
    voucher_type: list[str] | None = Query(default=None),  # noqa: B008
) -> RegisterOut:
    companies = access.entities(company)
    period = parse_period(month, date_from, date_to)
    chosen = SIDES[side]
    facets = Facets(facet_names(party, "party"), facet_names(voucher_type, "voucher type"))
    found = register(session, companies, period, chosen, facets)
    return RegisterOut(
        side=side,
        companies=companies,
        combined=len(companies) > 1,
        period=PeriodOut(start=period.start, end=period.end, months=list(period.months)),
        rows=[row_out(r, chosen) for r in found.rows],
        truncated=found.truncated,
    )


def row_out(r: RegisterRow, side: Side) -> RegisterRowOut:
    """A register row with its amount as Debit or Credit."""
    return RegisterRowOut(
        voucher_id=r.voucher_id,
        company=r.company,
        date=r.on,
        voucher_type=r.voucher_type,
        is_return=r.base_type == side.note,
        number=r.number,
        ledger_id=r.ledger_id,
        particulars=r.particulars,
        party_id=r.party_id,
        party=r.party,
        debit=r.amount if r.amount > 0 else None,
        credit=-r.amount if r.amount < 0 else None,
        side_value=r.side_value,
        narration=r.narration,
    )
