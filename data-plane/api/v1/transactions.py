"""`GET /api/v1/transactions`: the Transactions page (RPT-014), one row per ledger line, for
any combination of the companies the caller may see (`company`, repeatable; default all,
combined) and a period (`month`, repeatable, or `date_from` and `date_to`). How:
core/transactions.py.
"""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.access import CurrentAccess
from api.v1.common import ReportSession, formula, parse_period
from api.v1.home import PeriodOut
from core.transactions import transactions

router = APIRouter(prefix="/transactions", tags=["transactions"])


class TransactionOut(BaseModel):
    line_id: int
    company: int
    date: date
    voucher_id: int
    voucher_type: str
    voucher_number: str
    reference: str | None  # e.g. the supplier's invoice number
    party_id: int | None
    party: str | None
    gstin: str | None  # the party's
    ledger_id: int
    ledger: str
    particulars: str | None  # the voucher's ledgers on the other side
    debit: Decimal | None = formula("F-TRN-001")
    credit: Decimal | None = formula("F-TRN-001")
    narration: str | None
    bills: str | None
    cost_centres: str | None
    order_number: str | None = None  # not fetched from the source yet: always empty
    cheque: str | None  # a bank line's cheque or instrument number
    utr: str | None  # only a value that looks like a bank's UTR
    utr_source: str | None  # where it was found: bank_field, udf or narration
    transaction_type: str | None  # Cheque, e-Fund Transfer, ...
    instrument_date: date | None
    bank_cleared_date: date | None  # the bank's date (bank reconciliation)
    tally_bank_entry_id: str | None  # the source's own id for the bank entry, not a UTR


class TransactionsOut(BaseModel):
    companies: list[int]
    combined: bool
    period: PeriodOut
    rows: list[TransactionOut]
    truncated: bool  # more lines than shown


@router.get("")
def list_transactions(
    session: ReportSession,
    access: CurrentAccess,
    company: list[int] | None = Query(default=None),  # noqa: B008
    month: list[str] | None = Query(default=None),  # noqa: B008
    date_from: date | None = None,
    date_to: date | None = None,
) -> TransactionsOut:
    companies = access.entities(company)
    period = parse_period(month, date_from, date_to)
    page = transactions(session, companies, period)
    return TransactionsOut(
        companies=companies,
        combined=len(companies) > 1,
        period=PeriodOut(start=period.start, end=period.end, months=list(period.months)),
        rows=[
            TransactionOut(
                line_id=r.line_id, company=r.company, date=r.on, voucher_id=r.voucher_id,
                voucher_type=r.voucher_type, voucher_number=r.voucher_number,
                reference=r.reference, party_id=r.party_id, party=r.party, gstin=r.gstin,
                ledger_id=r.ledger_id, ledger=r.ledger, particulars=r.particulars,
                debit=r.debit, credit=r.credit, narration=r.narration, bills=r.bills,
                cost_centres=r.cost_centres, cheque=r.cheque, utr=r.utr,
                utr_source=r.utr_source, transaction_type=r.transaction_type,
                instrument_date=r.instrument_date, bank_cleared_date=r.bank_cleared_date,
                tally_bank_entry_id=r.tally_bank_entry_id,
            )
            for r in page.rows
        ],
        truncated=page.truncated,
    )  # fmt: skip
