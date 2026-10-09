"""Builds Tally XML Import requests for the seed data.

Sign convention written here (verified independently afterwards with Tally's $$IsDr):
a debit is ISDEEMEDPOSITIVE=Yes with a negative AMOUNT; a credit is ISDEEMEDPOSITIVE=No
with a positive AMOUNT. Opening balances: debit negative, credit positive.
"""

from datetime import date
from decimal import Decimal
from xml.sax.saxutils import escape, quoteattr

from devtools.tally_seed.data import Entry, Ledger, Side, Voucher

GODOWN = "Main Location"
BATCH = "Primary Batch"
COST_CATEGORY = "Primary Cost Category"


def _amount(side: Side, value: Decimal) -> str:
    signed = -value if side == "Dr" else value
    return f"{signed:.2f}"


def _deemed(side: Side) -> str:
    return "Yes" if side == "Dr" else "No"


def _date(value: date) -> str:
    return value.strftime("%Y%m%d")


def tally_attr_date(value: date) -> str:
    return value.strftime("%d-%b-%Y")


def envelope(company: str, report: str, body: str) -> str:
    return (
        "<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>"
        "<BODY><IMPORTDATA><REQUESTDESC>"
        f"<REPORTNAME>{report}</REPORTNAME>"
        f"<STATICVARIABLES><SVCURRENTCOMPANY>{escape(company)}</SVCURRENTCOMPANY>"
        "</STATICVARIABLES></REQUESTDESC>"
        f'<REQUESTDATA><TALLYMESSAGE xmlns:UDF="TallyUDF">{body}</TALLYMESSAGE></REQUESTDATA>'
        "</IMPORTDATA></BODY></ENVELOPE>"
    )


def _names(name: str) -> str:
    return f"<NAME.LIST><NAME>{escape(name)}</NAME></NAME.LIST>"


def ledger_create(ledger: Ledger) -> str:
    gst = ""
    if ledger.gst_duty_head:
        gst = f"<TAXTYPE>GST</TAXTYPE><GSTDUTYHEAD>{escape(ledger.gst_duty_head)}</GSTDUTYHEAD>"
    return (
        f'<LEDGER NAME={quoteattr(ledger.name)} ACTION="Create">{_names(ledger.name)}'
        f"<PARENT>{escape(ledger.parent)}</PARENT>"
        f"<ISBILLWISEON>{'Yes' if ledger.bill_wise else 'No'}</ISBILLWISEON>"
        f"{gst}"
        f"<OPENINGBALANCE>{_amount(ledger.opening_side, ledger.opening)}</OPENINGBALANCE>"
        "</LEDGER>"
    )


def ledger_set_opening(ledger: Ledger) -> str:
    return (
        f'<LEDGER NAME={quoteattr(ledger.name)} ACTION="Alter">'
        f"<OPENINGBALANCE>{_amount(ledger.opening_side, ledger.opening)}</OPENINGBALANCE>"
        "</LEDGER>"
    )


def unit_create(name: str) -> str:
    return (
        f'<UNIT NAME={quoteattr(name)} ACTION="Create"><NAME>{escape(name)}</NAME>'
        "<ISSIMPLEUNIT>Yes</ISSIMPLEUNIT><DECIMALPLACES>0</DECIMALPLACES></UNIT>"
    )


def stock_item_create(name: str, unit: str) -> str:
    return (
        f'<STOCKITEM NAME={quoteattr(name)} ACTION="Create">{_names(name)}'
        f"<BASEUNITS>{escape(unit)}</BASEUNITS></STOCKITEM>"
    )


def cost_centre_create(name: str) -> str:
    return (
        f'<COSTCENTRE NAME={quoteattr(name)} ACTION="Create">{_names(name)}'
        f"<CATEGORY>{COST_CATEGORY}</CATEGORY></COSTCENTRE>"
    )


def _entry(entry: Entry, list_tag: str, party: bool = False) -> str:
    bills = "".join(
        "<BILLALLOCATIONS.LIST>"
        f"<NAME>{escape(b.name)}</NAME><BILLTYPE>{b.bill_type}</BILLTYPE>"
        f"<AMOUNT>{_amount(entry.side, b.amount)}</AMOUNT>"
        "</BILLALLOCATIONS.LIST>"
        for b in entry.bills
    )
    centres = ""
    if entry.cost_centres:
        allocations = "".join(
            "<COSTCENTREALLOCATIONS.LIST>"
            f"<NAME>{escape(name)}</NAME><AMOUNT>{_amount(entry.side, value)}</AMOUNT>"
            "</COSTCENTREALLOCATIONS.LIST>"
            for name, value in entry.cost_centres
        )
        centres = (
            f"<CATEGORYALLOCATIONS.LIST><CATEGORY>{COST_CATEGORY}</CATEGORY>"
            f"<ISDEEMEDPOSITIVE>{_deemed(entry.side)}</ISDEEMEDPOSITIVE>{allocations}"
            "</CATEGORYALLOCATIONS.LIST>"
        )
    return (
        f"<{list_tag}>"
        f"<LEDGERNAME>{escape(entry.ledger)}</LEDGERNAME>"
        f"<ISDEEMEDPOSITIVE>{_deemed(entry.side)}</ISDEEMEDPOSITIVE>"
        f"<ISPARTYLEDGER>{'Yes' if party else 'No'}</ISPARTYLEDGER>"
        f"<AMOUNT>{_amount(entry.side, entry.amount)}</AMOUNT>"
        f"{bills}{centres}"
        f"</{list_tag}>"
    )


def _voucher_body(voucher: Voucher, entries: tuple[Entry, ...]) -> str:
    head = (
        f"<DATE>{_date(voucher.on)}</DATE><EFFECTIVEDATE>{_date(voucher.on)}</EFFECTIVEDATE>"
        f"<VOUCHERTYPENAME>{escape(voucher.voucher_type)}</VOUCHERTYPENAME>"
        f"<NARRATION>{escape(voucher.tagged_narration)}</NARRATION>"
    )
    if not voucher.items:
        return head + "".join(_entry(e, "ALLLEDGERENTRIES.LIST") for e in entries)
    party = next(e for e in entries if e.bills)
    inventory = "".join(
        "<ALLINVENTORYENTRIES.LIST>"
        f"<STOCKITEMNAME>{escape(i.item)}</STOCKITEMNAME><ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>"
        f"<RATE>{i.rate:.2f}/Nos</RATE><AMOUNT>{i.amount:.2f}</AMOUNT>"
        f"<ACTUALQTY> {i.quantity:.0f} Nos</ACTUALQTY><BILLEDQTY> {i.quantity:.0f} Nos</BILLEDQTY>"
        "<BATCHALLOCATIONS.LIST>"
        f"<GODOWNNAME>{GODOWN}</GODOWNNAME><BATCHNAME>{BATCH}</BATCHNAME>"
        f"<AMOUNT>{i.amount:.2f}</AMOUNT>"
        f"<ACTUALQTY> {i.quantity:.0f} Nos</ACTUALQTY><BILLEDQTY> {i.quantity:.0f} Nos</BILLEDQTY>"
        "</BATCHALLOCATIONS.LIST>"
        "<ACCOUNTINGALLOCATIONS.LIST>"
        f"<LEDGERNAME>{escape(i.sales_ledger)}</LEDGERNAME><ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>"
        f"<AMOUNT>{i.amount:.2f}</AMOUNT>"
        "</ACCOUNTINGALLOCATIONS.LIST>"
        "</ALLINVENTORYENTRIES.LIST>"
        for i in voucher.items
    )
    return (
        head
        + f"<PARTYLEDGERNAME>{escape(party.ledger)}</PARTYLEDGERNAME>"
        + "<PERSISTEDVIEW>Invoice Voucher View</PERSISTEDVIEW><ISINVOICE>Yes</ISINVOICE>"
        + inventory
        + "".join(_entry(e, "LEDGERENTRIES.LIST", party=e is party) for e in entries)
    )


def voucher_create(voucher: Voucher) -> str:
    view = ' OBJVIEW="Invoice Voucher View"' if voucher.items else ""
    return (
        f'<VOUCHER VCHTYPE={quoteattr(voucher.voucher_type)} ACTION="Create"{view}>'
        f"{_voucher_body(voucher, voucher.entries)}</VOUCHER>"
    )


def _identify(voucher: Voucher, master_id: int, action: str) -> str:
    return (
        f'<VOUCHER DATE="{tally_attr_date(voucher.on)}" TAGNAME="MasterID" '
        f'TAGVALUE="{master_id}" VCHTYPE={quoteattr(voucher.voucher_type)} ACTION="{action}">'
    )


def voucher_alter(voucher: Voucher, master_id: int) -> str:
    if voucher.alter_to is None:
        raise ValueError(f"{voucher.marker} has no alteration")
    body = _voucher_body(voucher, voucher.alter_to)
    return f"{_identify(voucher, master_id, 'Alter')}{body}</VOUCHER>"


def voucher_cancel(voucher: Voucher, master_id: int) -> str:
    return (
        f"{_identify(voucher, master_id, 'Cancel')}"
        f"<NARRATION>{escape(voucher.tagged_narration)}</NARRATION></VOUCHER>"
    )
