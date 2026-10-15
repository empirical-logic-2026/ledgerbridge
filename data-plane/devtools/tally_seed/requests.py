"""Builds Tally XML Import requests for the seed data.

Sign convention written here (verified independently afterwards with Tally's $$IsDr):
a debit is ISDEEMEDPOSITIVE=Yes with a negative AMOUNT; a credit is ISDEEMEDPOSITIVE=No
with a positive AMOUNT. Opening balances: debit negative, credit positive.
"""

from datetime import date
from decimal import Decimal
from xml.sax.saxutils import escape, quoteattr

from devtools.tally_seed.data import Entry, Godown, ItemLine, Ledger, Side, StockItem, Voucher

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


def stock_group_create(name: str) -> str:
    return f'<STOCKGROUP NAME={quoteattr(name)} ACTION="Create">{_names(name)}</STOCKGROUP>'


def godown_create(godown: Godown) -> str:
    return (
        f'<GODOWN NAME={quoteattr(godown.name)} ACTION="Create">{_names(godown.name)}'
        f"<ISEXTERNAL>{'Yes' if godown.external else 'No'}</ISEXTERNAL>"
        f"<ISINTERNAL>{'Yes' if godown.internal else 'No'}</ISINTERNAL></GODOWN>"
    )


def stock_item_create(item: StockItem) -> str:
    opening = ""
    if item.opening_qty:
        # An opening stock is an asset (debit): its value is negative in Tally's XML.
        value = f"{-item.opening_qty * item.opening_rate:.2f}"
        fields = (
            f"<OPENINGBALANCE> {item.opening_qty:.0f} {escape(item.unit)}</OPENINGBALANCE>"
            f"<OPENINGVALUE>{value}</OPENINGVALUE>"
            f"<OPENINGRATE>{item.opening_rate:.2f}/{escape(item.unit)}</OPENINGRATE>"
        )
        opening = (
            f"{fields}<BATCHALLOCATIONS.LIST><GODOWNNAME>{GODOWN}</GODOWNNAME>"
            f"<BATCHNAME>{BATCH}</BATCHNAME>{fields}</BATCHALLOCATIONS.LIST>"
        )
    parent = f"<PARENT>{escape(item.group)}</PARENT>" if item.group else ""
    return (
        f'<STOCKITEM NAME={quoteattr(item.name)} ACTION="Create">{_names(item.name)}'
        f"{parent}<BASEUNITS>{escape(item.unit)}</BASEUNITS>{opening}</STOCKITEM>"
    )


def voucher_type_create(name: str, parent: str) -> str:
    return (
        f'<VOUCHERTYPE NAME={quoteattr(name)} ACTION="Create">{_names(name)}'
        f"<PARENT>{escape(parent)}</PARENT><NUMBERINGMETHOD>Automatic</NUMBERINGMETHOD>"
        "<ISACTIVE>Yes</ISACTIVE></VOUCHERTYPE>"
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


def _qty(quantity: Decimal) -> str:
    return f"<ACTUALQTY> {quantity:.0f} Nos</ACTUALQTY><BILLEDQTY> {quantity:.0f} Nos</BILLEDQTY>"


def _inventory(line: ItemLine, tag: str = "ALLINVENTORYENTRIES.LIST") -> str:
    """One inventory entry: sent out is a credit (positive amount), received a debit. One
    batch allocation per (quantity, tracking number) of the line; a Material In/Out names
    the job worker's godown as its destination."""
    side: Side = "Dr" if line.inward else "Cr"
    amount = _amount(side, line.amount)
    destination = (
        f"<DESTINATIONGODOWNNAME>{escape(line.destination)}</DESTINATIONGODOWNNAME>"
        if line.destination
        else ""
    )
    batches = "".join(
        "<BATCHALLOCATIONS.LIST>"
        f"<GODOWNNAME>{escape(line.godown)}</GODOWNNAME>{destination}<BATCHNAME>{BATCH}</BATCHNAME>"
        + (f"<TRACKINGNUMBER>{escape(tracking)}</TRACKINGNUMBER>" if tracking else "")
        + f"<AMOUNT>{_amount(side, quantity * line.rate)}</AMOUNT>{_qty(quantity)}"
        "</BATCHALLOCATIONS.LIST>"
        for quantity, tracking in line.split()
    )
    accounting = ""
    if line.sales_ledger:
        accounting = (
            "<ACCOUNTINGALLOCATIONS.LIST>"
            f"<LEDGERNAME>{escape(line.sales_ledger)}</LEDGERNAME>"
            f"<ISDEEMEDPOSITIVE>{_deemed(side)}</ISDEEMEDPOSITIVE><AMOUNT>{amount}</AMOUNT>"
            "</ACCOUNTINGALLOCATIONS.LIST>"
        )
    return (
        f"<{tag}>"
        f"<STOCKITEMNAME>{escape(line.item)}</STOCKITEMNAME>"
        f"<ISDEEMEDPOSITIVE>{_deemed(side)}</ISDEEMEDPOSITIVE>"
        f"<RATE>{line.rate:.2f}/Nos</RATE><AMOUNT>{amount}</AMOUNT>{_qty(line.quantity)}"
        f"{batches}{accounting}"
        f"</{tag}>"
    )


def _voucher_body(voucher: Voucher, entries: tuple[Entry, ...]) -> str:
    head = (
        f"<DATE>{_date(voucher.on)}</DATE><EFFECTIVEDATE>{_date(voucher.on)}</EFFECTIVEDATE>"
        f"<VOUCHERTYPENAME>{escape(voucher.voucher_type)}</VOUCHERTYPENAME>"
    )
    if voucher.number:
        head += f"<VOUCHERNUMBER>{escape(voucher.number)}</VOUCHERNUMBER>"
    if voucher.reference:
        head += f"<REFERENCE>{escape(voucher.reference)}</REFERENCE>"
    head += f"<NARRATION>{escape(voucher.tagged_narration)}</NARRATION>"
    if voucher.optional:
        head += "<ISOPTIONAL>Yes</ISOPTIONAL>"
    if voucher.post_dated:
        head += "<ISPOSTDATED>Yes</ISPOSTDATED>"
    if not voucher.items:
        return head + "".join(_entry(e, "ALLLEDGERENTRIES.LIST") for e in entries)
    if voucher.stock_journal:
        return head + "".join(
            _inventory(
                line, "INVENTORYENTRIESIN.LIST" if line.inward else "INVENTORYENTRIESOUT.LIST"
            )
            for line in voucher.items
        )
    party_name = voucher.party or next(e for e in entries if e.bills).ledger
    return (
        head
        + f"<PARTYLEDGERNAME>{escape(party_name)}</PARTYLEDGERNAME>"
        + "<PERSISTEDVIEW>Invoice Voucher View</PERSISTEDVIEW><ISINVOICE>Yes</ISINVOICE>"
        + "".join(_inventory(line) for line in voucher.items)
        + "".join(_entry(e, "LEDGERENTRIES.LIST", party=e.ledger == party_name) for e in entries)
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


def voucher_delete(voucher: Voucher, master_id: int) -> str:
    return f"{_identify(voucher, master_id, 'Delete')}</VOUCHER>"


def voucher_cancel(voucher: Voucher, master_id: int) -> str:
    return (
        f"{_identify(voucher, master_id, 'Cancel')}"
        f"<NARRATION>{escape(voucher.tagged_narration)}</NARRATION></VOUCHER>"
    )
