"""`GET /api/v1/parties/{customers|vendors}` and `.../{party_id}`: the Customers and Vendors
lists and one party's page (D2; docs/design/dashboard.md Section 0.3, screen 8).

For any combination of the companies the caller may see (`company`, repeatable; default all,
combined) and a period (`month`, repeatable, or `date_from` and `date_to`). A party is known by
its name across those companies; a party outside them is 404, like a company outside access.
`compare=true` adds last year's sales (purchases) to the page. How the figures are found:
core/parties.py.
"""

from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.access import CurrentAccess
from api.v1.common import ReportSession, parse_period
from api.v1.home import PeriodOut, change_pct
from api.v1.registers import RegisterRowOut, row_out
from core.parties import KINDS, Bill, PartyPage, find_party, party_list, party_page

router = APIRouter(prefix="/parties", tags=["parties"])
PartyKind = Literal["customers", "vendors"]


class PartyRowOut(BaseModel):
    party_id: int
    name: str
    companies: list[int]
    balance: Decimal  # due at the period's end; positive when owed in the usual direction
    net: Decimal  # net sales (purchases) in the period
    invoices: int
    last_invoice: date | None


class PartiesOut(BaseModel):
    kind: str
    companies: list[int]
    combined: bool
    period: PeriodOut
    parties: list[PartyRowOut]


class PartyFigure(BaseModel):
    value: Decimal | None
    last_year: Decimal | None = None
    change_pct: Decimal | None = None


class BillOut(BaseModel):
    company: int
    name: str
    date: date
    due: date
    amount: Decimal  # outstanding; negative: an advance or overpaid
    overdue_days: int  # 0 when not yet due


class EntryOut(BaseModel):
    voucher_id: int
    company: int
    date: date
    voucher_type: str
    number: str
    particulars: str  # the other side's first ledger
    debit: Decimal | None
    credit: Decimal | None
    balance: Decimal  # running, debit positive
    narration: str | None


class SettlementOut(BaseModel):
    voucher_id: int
    company: int
    date: date
    voucher_type: str
    number: str
    amount: Decimal
    narration: str | None


class PartyInvoiceOut(RegisterRowOut):
    status: Literal["paid", "due", "overdue", "no_bill"]
    days: int | None  # due in (status due) or overdue by (overdue)


class PartyMonthOut(BaseModel):
    month: date
    net: Decimal  # net sales (purchases)
    invoices: int
    settled: Decimal  # receipts (payments)


class PartyOut(BaseModel):
    kind: str
    party_id: int
    name: str
    companies: list[int]  # of the selected companies, where the party exists
    group_path: list[str]
    credit_days: int | None
    main_channel: str | None
    period: PeriodOut
    balance: Decimal
    overdue: Decimal
    bills_cover: Decimal  # what the stored bills add up to (opening bills aren't stored)
    net: PartyFigure
    invoices: PartyFigure
    settled: Decimal
    days_to_pay: Decimal | None
    invoices_list: list[PartyInvoiceOut]
    invoices_truncated: bool
    settlements: list[SettlementOut]
    statement_opening: Decimal  # debit positive
    statement: list[EntryOut]
    statement_truncated: bool
    bills: list[BillOut]
    monthly: list[PartyMonthOut]


@router.get("/{kind}")
def parties(
    kind: PartyKind,
    session: ReportSession,
    access: CurrentAccess,
    company: list[int] | None = Query(default=None),  # noqa: B008
    month: list[str] | None = Query(default=None),  # noqa: B008
    date_from: date | None = None,
    date_to: date | None = None,
) -> PartiesOut:
    companies = access.entities(company)
    period = parse_period(month, date_from, date_to)
    return PartiesOut(
        kind=kind,
        companies=companies,
        combined=len(companies) > 1,
        period=PeriodOut(start=period.start, end=period.end, months=list(period.months)),
        parties=[
            PartyRowOut(
                party_id=r.party_id,
                name=r.name,
                companies=r.companies,
                balance=r.balance,
                net=r.net,
                invoices=r.invoices,
                last_invoice=r.last_invoice,
            )
            for r in party_list(session, companies, period, kind)
        ],
    )


@router.get("/{kind}/{party_id}")
def party(
    kind: PartyKind,
    party_id: int,
    session: ReportSession,
    access: CurrentAccess,
    company: list[int] | None = Query(default=None),  # noqa: B008
    month: list[str] | None = Query(default=None),  # noqa: B008
    date_from: date | None = None,
    date_to: date | None = None,
    compare: bool = False,
) -> PartyOut:
    companies = access.entities(company)
    period = parse_period(month, date_from, date_to)
    found = find_party(session, companies, party_id)
    if found is None:
        raise HTTPException(404, "No such party in the selected companies.")
    page = party_page(session, companies, found, period, kind, compare)
    return _party_out(kind, page, period)


def _party_out(kind: str, page: PartyPage, period) -> PartyOut:  # noqa: ANN001
    side = KINDS[kind][1]
    now, before = page.totals, page.last_year
    return PartyOut(
        kind=kind,
        party_id=page.party.id,
        name=page.party.name,
        companies=page.party.companies,
        group_path=page.party.group_path,
        credit_days=page.party.credit_days,
        main_channel=page.main_channel,
        period=PeriodOut(start=period.start, end=period.end, months=list(period.months)),
        balance=page.balance,
        overdue=page.overdue,
        bills_cover=page.bills_cover,
        net=PartyFigure(
            value=now.net,
            last_year=before.net if before else None,
            change_pct=change_pct(now.net, before.net if before else None),
        ),
        invoices=PartyFigure(
            value=Decimal(now.invoices),
            last_year=Decimal(before.invoices) if before else None,
            change_pct=change_pct(
                Decimal(now.invoices), Decimal(before.invoices) if before else None
            ),
        ),
        settled=page.settled,
        days_to_pay=page.days_to_pay,
        invoices_list=[
            PartyInvoiceOut(
                **row_out(r, side).model_dump(),
                **_status(page.bills_by_voucher.get(r.voucher_id), page.as_of),
            )
            for r in page.invoices.rows
        ],
        invoices_truncated=page.invoices.truncated,
        settlements=[
            SettlementOut(
                voucher_id=s.voucher_id,
                company=s.company,
                date=s.on,
                voucher_type=s.voucher_type,
                number=s.number,
                amount=s.amount,
                narration=s.narration,
            )
            for s in page.settlements
        ],
        statement_opening=page.statement_opening,
        statement=[
            EntryOut(
                voucher_id=e.voucher_id,
                company=e.company,
                date=e.on,
                voucher_type=e.voucher_type,
                number=e.number,
                particulars=e.particulars,
                debit=e.amount if e.amount > 0 else None,
                credit=-e.amount if e.amount < 0 else None,
                balance=e.balance,
                narration=e.narration,
            )
            for e in page.statement
        ],
        statement_truncated=page.statement_truncated,
        bills=[
            BillOut(
                company=b.company,
                name=b.name,
                date=b.on,
                due=b.due,
                amount=b.amount,
                overdue_days=max(0, (page.as_of - b.due).days),
            )
            for b in page.bills
        ],
        monthly=[
            PartyMonthOut(month=m, net=t.net, invoices=t.invoices, settled=settled)
            for m, t, settled in page.monthly
        ],
    )


def _status(bill: Bill | None, as_of: date) -> dict:
    """An invoice's bill: paid (nothing outstanding), due in N days, or overdue by N days."""
    if bill is None:
        return {"status": "no_bill", "days": None}
    if abs(bill.amount) < Decimal("0.005"):
        return {"status": "paid", "days": None}
    if bill.due < as_of:
        return {"status": "overdue", "days": (as_of - bill.due).days}
    return {"status": "due", "days": (bill.due - as_of).days}
