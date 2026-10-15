"""Tally objects → canonical records (schema.md Section 7). All Tally knowledge lives here.

Signs: canonical amount = −(Tally amount) for every amount (schema.md 7.1).
Postings: connectors.tally.signs.postings implements the rules of schema.md 7.2.
"""

import re
import xml.etree.ElementTree as ET  # noqa: N817
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from typing import Any

from connectors.base import SourceRecord
from connectors.tally import parser
from connectors.tally.signs import postings, tally_amount
from core.canonical import (
    NO_STANDARD_ACCOUNT,
    CanonicalBill,
    CanonicalCompany,
    CanonicalCostCentre,
    CanonicalGodown,
    CanonicalGroup,
    CanonicalInventoryLine,
    CanonicalItem,
    CanonicalItemGroup,
    CanonicalLedger,
    CanonicalLine,
    CanonicalParty,
    CanonicalRecord,
    CanonicalUnit,
    CanonicalVoucher,
    CanonicalVoucherType,
)
from core.names import normalise

# Explicitly "no standard account": stops a sub-group from inheriting its parent's mapping.
UNMAPPED = NO_STANDARD_ACCOUNT

# Default standard accounts by Tally reserved group (approved for M3; schema.md 7.3).
# Duties & Taxes is mapped per ledger by tax type (STANDARD_ACCOUNT_BY_TAX_TYPE). Indirect
# Expenses stays unmapped: it holds ledgers for different standard accounts (rent, salaries).
STANDARD_ACCOUNT_BY_GROUP: dict[str, str] = {
    "Capital Account": "2100",
    "Reserves & Surplus": "2200",
    "Loans (Liability)": "3110",
    "Secured Loans": "3110",
    "Unsecured Loans": "3110",
    "Bank OD A/c": "3210",
    "Bank OCC A/c": "3210",
    "Sundry Creditors": "3220",
    "Provisions": "3280",
    "Current Liabilities": "3270",
    "Suspense A/c": "3290",
    # Debit balances → 1275, credit balances → 3275, decided at the reporting date (M6).
    "Branch / Divisions": "1275",
    "Fixed Assets": "1110",
    "Investments": "1150",
    "Stock-in-Hand": "1210",
    "Sundry Debtors": "1220",
    "Cash-in-Hand": "1231",
    "Bank Accounts": "1232",
    "Loans & Advances (Asset)": "1240",
    "Deposits (Asset)": "1160",
    "Current Assets": "1270",
    "Misc. Expenses (ASSET)": "1270",
    "Sales Accounts": "4110",
    "Direct Incomes": "4130",
    "Indirect Incomes": "4220",
    "Purchase Accounts": "5110",
    "Direct Expenses": "5130",
    "Duties & Taxes": UNMAPPED,
    "Indirect Expenses": UNMAPPED,
}
# Duties & Taxes ledgers by Tally TAXTYPE. Stored on the debit side; a credit balance at the
# reporting date is reported as GST payable (3230) or TDS and TCS payable (3240) (M6).
STANDARD_ACCOUNT_BY_TAX_TYPE = {"GST": "1250", "TDS": "1260", "TCS": "1260"}
EQUITY_GROUPS = {"Capital Account", "Reserves & Surplus"}
LEDGER_KIND_BY_GROUP = {
    "Bank Accounts": "bank",
    "Bank OD A/c": "bank",
    "Bank OCC A/c": "bank",
    "Cash-in-Hand": "cash",
    "Duties & Taxes": "tax",
    "Sundry Debtors": "party",
    "Sundry Creditors": "party",
    "Stock-in-Hand": "stock",
}
PARTY_TYPE_BY_GROUP = {"Sundry Debtors": "customer", "Sundry Creditors": "vendor"}

# Tally's "Primary" pseudo-parent. The Profit & Loss A/c ledger hangs directly under it, so a
# synthetic group per company carries it (mapped to Reserves and surplus).
PRIMARY = "Primary"
# What Tally writes where a reference (tracking number, order number) is empty.
NOT_APPLICABLE = "Not Applicable"
PRIMARY_GROUP_STANDARD_ACCOUNT = "2200"

VOUCHER_BASE_TYPES = {
    "Sales": "sales",
    "Purchase": "purchase",
    "Payment": "payment",
    "Receipt": "receipt",
    "Journal": "journal",
    "Contra": "contra",
    "Debit Note": "debit_note",
    "Credit Note": "credit_note",
    "Stock Journal": "stock_journal",
    "Delivery Note": "delivery_note",
    "Receipt Note": "receipt_note",
}
# Voucher types that don't post to the books: their ledger entries aren't effective.
NON_ACCOUNTING_VOUCHER_TYPES = {
    "Delivery Note", "Receipt Note", "Stock Journal", "Physical Stock", "Sales Order",
    "Purchase Order", "Job Work In Order", "Job Work Out Order", "Material In",
    "Material Out", "Rejections In", "Rejections Out", "Memorandum", "Reversing Journal",
    "Attendance",
}  # fmt: skip
# Voucher types whose inventory entries don't move stock (orders record what is ordered;
# memorandum vouchers aren't in the books).
NON_STOCK_VOUCHER_TYPES = {
    "Sales Order", "Purchase Order", "Job Work In Order", "Job Work Out Order", "Memorandum",
}  # fmt: skip
# Tally's predefined voucher types: every voucher type derives from one of them. Only these
# names are ever shown outside the test environment (they are Tally's, not the client's).
STANDARD_VOUCHER_TYPES = frozenset((
    *VOUCHER_BASE_TYPES, *NON_ACCOUNTING_VOUCHER_TYPES, "Payroll",
))  # fmt: skip
# Tally's predefined (reserved) groups.
RESERVED_GROUPS = frozenset(STANDARD_ACCOUNT_BY_GROUP)

GST_DUTY_HEADS = {
    "Central Tax": "cgst",
    "State Tax": "sgst",
    "UT Tax": "sgst",
    "Integrated Tax": "igst",
    "Cess": "cess",
}
TAX_TYPES = {"TDS": "tds", "TCS": "tcs", "VAT": "vat"}
BILL_TYPES = {
    "New Ref": "new_ref",
    "Agst Ref": "against_ref",
    "Advance": "advance",
    "On Account": "on_account",
}

# GST state codes (first two digits of a GSTIN), keyed by state name as Tally shows it.
GST_STATE_CODES = {
    "Jammu & Kashmir": "01", "Himachal Pradesh": "02", "Punjab": "03", "Chandigarh": "04",
    "Uttarakhand": "05", "Haryana": "06", "Delhi": "07", "Rajasthan": "08",
    "Uttar Pradesh": "09", "Bihar": "10", "Sikkim": "11", "Arunachal Pradesh": "12",
    "Nagaland": "13", "Manipur": "14", "Mizoram": "15", "Tripura": "16", "Meghalaya": "17",
    "Assam": "18", "West Bengal": "19", "Jharkhand": "20", "Odisha": "21",
    "Chhattisgarh": "22", "Madhya Pradesh": "23", "Gujarat": "24",
    "Dadra & Nagar Haveli and Daman & Diu": "26", "Maharashtra": "27", "Karnataka": "29",
    "Goa": "30", "Lakshadweep": "31", "Kerala": "32", "Tamil Nadu": "33", "Puducherry": "34",
    "Andaman & Nicobar Islands": "35", "Telangana": "36", "Andhra Pradesh": "37",
    "Ladakh": "38",
}  # fmt: skip

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


class MappingError(ValueError):
    """A Tally object can't be mapped. Messages name fields, never values."""


# --- small helpers ---------------------------------------------------------------------


def _text(element: ET.Element, path: str) -> str | None:
    value = element.findtext(path)
    return value.strip() if value is not None and value.strip() else None


def _flag(element: ET.Element, path: str) -> bool:
    return (_text(element, path) or "").lower() == "yes"


def _canonical(value: Decimal | None) -> Decimal:
    """Tally sign → canonical sign (schema.md 7.1)."""
    return -value if value else Decimal(0)


def quantity(text: str | None) -> tuple[Decimal, str | None]:
    """A Tally quantity: (number, unit)."""
    return _quantity(text)


def _quantity(text: str | None) -> tuple[Decimal, str | None]:
    """' 10 Nos' → (10, 'Nos'); ' 1.5 Kg' → (1.5, 'Kg')."""
    if not text:
        return Decimal(0), None
    match = _NUMBER.search(text)
    if not match:
        return Decimal(0), None
    unit = text[match.end() :].strip() or None
    return Decimal(match.group(0)), unit


def _rate(text: str | None) -> Decimal | None:
    """'200.00/Nos' → 200.00."""
    if not text:
        return None
    match = _NUMBER.search(text)
    try:
        return Decimal(match.group(0)) if match else None
    except InvalidOperation:
        return None


def _is_primary(name: str | None) -> bool:
    return name is None or normalise(name) == normalise(PRIMARY)


def _parent(element: ET.Element) -> str | None:
    parent = _text(element, "PARENT")
    return None if _is_primary(parent) else parent


def _aliases(element: ET.Element, name: str, *more: str | None) -> tuple[str, ...]:
    """Other names of a master: its alias names (LANGUAGENAME.LIST) and any given."""
    names = [(n.text or "").strip() for n in element.findall("LANGUAGENAME.LIST/NAME.LIST/NAME")]
    return tuple(dict.fromkeys(a for a in (*names, *more) if a and a != name))


def _reserved(element: ET.Element) -> str | None:
    """Tally's built-in name for predefined masters (empty for user-created ones)."""
    return (element.get("RESERVEDNAME") or "").strip() or None


def _name(element: ET.Element) -> str:
    name = parser.object_name(element)
    if not name:
        raise MappingError(f"{element.tag} without a name")
    return name


def _state_code(name: str | None) -> str | None:
    return GST_STATE_CODES.get(name) if name else None


# --- masters ---------------------------------------------------------------------------


def company(element: ET.Element, key: str) -> CanonicalCompany:
    books_from = parser.tally_date(_text(element, "BOOKSFROM"))
    starting = parser.tally_date(_text(element, "STARTINGFROM")) or books_from
    gstin = _text(element, "GSTREGISTRATIONNUMBER")
    return CanonicalCompany(
        source_key=key,
        name=_name(element),
        legal_name=_text(element, "BASICCOMPANYFORMALNAME"),
        books_from=books_from,
        fy_start_month=starting.month if starting else 4,
        state_code=_state_code(_text(element, "STATENAME")) or (gstin[:2] if gstin else None),
        gstin=gstin,
        pan=_text(element, "INCOMETAXNUMBER"),
    )


def group(element: ET.Element, key: str) -> CanonicalGroup:
    reserved = _reserved(element)
    parent = _parent(element)
    nature = None
    if parent is None:  # primary group: its flags decide the nature of everything below it
        if reserved in EQUITY_GROUPS:
            nature = "equity"
        elif _flag(element, "ISREVENUE"):
            nature = "expense" if _flag(element, "ISDEEMEDPOSITIVE") else "income"
        else:
            nature = "asset" if _flag(element, "ISDEEMEDPOSITIVE") else "liability"
    elif reserved in EQUITY_GROUPS:
        nature = "equity"
    name = _name(element)
    return CanonicalGroup(
        source_key=key,
        name=name,
        parent_name=parent,
        nature=nature,
        is_primary=parent is None,
        affects_gross_profit=_flag(element, "AFFECTSGROSSPROFIT"),
        standard_account_code=STANDARD_ACCOUNT_BY_GROUP.get(reserved or ""),
        ledger_kind=LEDGER_KIND_BY_GROUP.get(reserved or ""),
        party_type=PARTY_TYPE_BY_GROUP.get(reserved or ""),
        # A reserved group the user renamed is still known by its reserved name.
        aliases=_aliases(element, name, reserved),
    )


def _primary_group(entity_key: str) -> CanonicalGroup:
    return CanonicalGroup(
        source_key=f"primary:{entity_key}",
        name=PRIMARY,
        parent_name=None,
        nature="equity",
        is_primary=True,
        standard_account_code=PRIMARY_GROUP_STANDARD_ACCOUNT,
    )


EMPTY_DUTY_HEAD_WARNING = (
    "empty GST duty head, assumed Central Tax (cgst); assumption to verify on client data"
)


def _tax_type(element: ET.Element) -> tuple[str | None, tuple[str, ...]]:
    """(tax_type, warnings). Assumption (schema.md 7.3): Tally leaves fields at their default
    out of the export, and "Central Tax" is the default duty head, so ledgers created as
    Central Tax come back with it empty. Applied to GST ledgers only, and always reported."""
    tax = _text(element, "TAXTYPE")
    if tax == "GST":
        head = _text(element, "GSTDUTYHEAD")
        if head is None:
            return GST_DUTY_HEADS["Central Tax"], (EMPTY_DUTY_HEAD_WARNING,)
        return GST_DUTY_HEADS.get(head, "other"), ()
    return TAX_TYPES.get(tax or ""), ()


def ledger(element: ET.Element, key: str, entity_key: str) -> list[CanonicalRecord]:
    parent = _text(element, "PARENT")
    parent = PRIMARY if _is_primary(parent) else parent
    credit_days = _NUMBER.search(_text(element, "BILLCREDITPERIOD") or "")
    credit_limit = tally_amount(_text(element, "CREDITLIMIT"))
    gstin = _text(element, "PARTYGSTIN") or _text(element, ".//LEDGSTREGDETAILS.LIST/GSTIN")
    state = _text(element, "LEDSTATENAME") or _text(element, ".//LEDMAILINGDETAILS.LIST/STATE")
    tax_type, warnings = _tax_type(element)
    name = _name(element)
    record = CanonicalLedger(
        source_key=key,
        name=name,
        group_name=parent,
        opening_balance=_canonical(tally_amount(_text(element, "OPENINGBALANCE"))),
        is_bill_wise=_flag(element, "ISBILLWISEON"),
        is_cost_centre_applicable=_flag(element, "ISCOSTCENTRESON"),
        gstin=gstin,
        tax_type=tax_type,
        party=CanonicalParty(
            gstin=gstin,
            pan=_text(element, "INCOMETAXNUMBER"),
            state_code=_state_code(state) or (gstin[:2] if gstin else None),
            country_code="IN" if (_text(element, "COUNTRYNAME") or "India") == "India" else None,
            credit_days=int(credit_days.group(0)) if credit_days else None,
            credit_limit=abs(credit_limit) if credit_limit else None,
            email=_text(element, "EMAIL"),
            phone=_text(element, "LEDGERMOBILE") or _text(element, "LEDGERPHONE"),
        ),
        default_standard_account_code=STANDARD_ACCOUNT_BY_TAX_TYPE.get(
            _text(element, "TAXTYPE") or ""
        ),
        warnings=warnings,
        aliases=_aliases(element, name),
    )
    return [_primary_group(entity_key), record] if parent == PRIMARY else [record]


def voucher_type(element: ET.Element, key: str) -> CanonicalVoucherType:
    """A predefined type (RESERVEDNAME), or a type created under another (PARENT). A type
    under a custom type inherits its standard type through the voucher type tree (the
    transform resolves it), so e.g. a "Cash Sale 2" under "Cash Sale" under "Sales" is a
    sale, and one under "Sales Order" doesn't post to the books."""
    name = _name(element)
    parent = _text(element, "PARENT")
    parent = None if parent == name else parent
    standard = next(
        (n for n in (_reserved(element), parent, name) if n in STANDARD_VOUCHER_TYPES), None
    )
    if standard is None and parent is not None:  # under a custom type: inherited
        return CanonicalVoucherType(
            source_key=key,
            name=name,
            base_type=None,
            is_accounting=None,
            is_inventory=_flag(element, "AFFECTSSTOCK"),
            parent_name=parent,
            moves_stock=None,
        )
    return CanonicalVoucherType(
        source_key=key,
        name=name,
        base_type=VOUCHER_BASE_TYPES.get(standard or "", "other"),
        is_accounting=standard not in NON_ACCOUNTING_VOUCHER_TYPES,
        is_inventory=_flag(element, "AFFECTSSTOCK"),
        parent_name=parent,
        standard_type=standard,
        moves_stock=standard not in NON_STOCK_VOUCHER_TYPES,
    )


def unit(element: ET.Element, key: str) -> CanonicalUnit:
    symbol = _name(element)
    places = _text(element, "DECIMALPLACES")
    return CanonicalUnit(
        source_key=key,
        symbol=symbol,
        name=_text(element, "ORIGINALNAME") or symbol,
        decimal_places=int(places) if places and places.isdigit() else 0,
    )


def stock_item(element: ET.Element, key: str) -> CanonicalItem:
    quantity, _ = _quantity(_text(element, "OPENINGBALANCE"))
    return CanonicalItem(
        source_key=key,
        name=_name(element),
        group_name=_parent(element),
        unit_name=_text(element, "BASEUNITS"),
        opening_qty=quantity,
        opening_value=_canonical(tally_amount(_text(element, "OPENINGVALUE"))),
    )


# --- vouchers --------------------------------------------------------------------------


def _line(entry: ET.Element) -> CanonicalLine:
    bills = tuple(
        CanonicalBill(
            bill_type=BILL_TYPES.get(_text(bill, "BILLTYPE") or "", "on_account"),
            name=_text(bill, "NAME"),
            amount=_canonical(tally_amount(_text(bill, "AMOUNT"))),
        )
        for bill in entry.findall("BILLALLOCATIONS.LIST")
        if _text(bill, "AMOUNT") or _text(bill, "NAME")
    )
    cost_allocations = tuple(
        (name, _canonical(tally_amount(_text(alloc, "AMOUNT"))))
        for category in entry.findall("CATEGORYALLOCATIONS.LIST")
        for alloc in category.findall("COSTCENTREALLOCATIONS.LIST")
        if (name := _text(alloc, "NAME"))
    )
    return CanonicalLine(
        ledger_name=_text(entry, "LEDGERNAME") or "",
        amount=_canonical(tally_amount(_text(entry, "AMOUNT"))),
        is_party_line=_flag(entry, "ISPARTYLEDGER"),
        bills=bills,
        cost_allocations=cost_allocations,
    )


def _inventory(entry: ET.Element, inward: bool | None = None) -> CanonicalInventoryLine | None:
    """One inventory entry. `inward` is given for stock journal entries (in: produced or
    received; out: consumed or sent), otherwise ISDEEMEDPOSITIVE decides."""
    item = _text(entry, "STOCKITEMNAME")
    if not item:
        return None
    quantity, unit_name = _quantity(_text(entry, "ACTUALQTY") or _text(entry, "BILLEDQTY"))
    if inward is None:
        inward = _flag(entry, "ISDEEMEDPOSITIVE")
    batch = entry.find("BATCHALLOCATIONS.LIST")
    discount = _rate(_text(entry, "DISCOUNT"))
    tracked = _tracked(entry, abs(quantity))
    return CanonicalInventoryLine(
        item_name=item,
        quantity=abs(quantity) if inward else -abs(quantity),
        tracked_quantity=tracked if inward else -tracked,
        amount=_canonical(tally_amount(_text(entry, "AMOUNT"))),
        unit_name=unit_name,
        rate=_rate(_text(entry, "RATE")),
        godown_name=_text(batch, "GODOWNNAME") if batch is not None else None,
        batch_name=_text(batch, "BATCHNAME") if batch is not None else None,
        discount_pct=discount if discount else None,
    )


def _holding(godown: ET.Element) -> str:
    """Whose stock a godown holds (checked on the test company, 2026-10-15): Tally leaves
    stock at an "our stock with third party" godown (ISEXTERNAL, e.g. a job worker's) out
    of every item balance, the Stock Summary and the closing stock value; stock at a
    "third-party stock with us" godown (ISINTERNAL) is counted."""
    if _flag(godown, "ISEXTERNAL"):
        return "ours_with_third_party"
    if _flag(godown, "ISINTERNAL"):
        return "third_party_with_us"
    return "own"


def _inventory_lines(entry: ET.Element, inward: bool | None) -> list[CanonicalInventoryLine]:
    """An inventory entry as lines: one per batch allocation when its stock sits in more
    than one godown (each with its own quantity, amount and tracking), so stock is known
    per godown; otherwise one line. Tally keeps the stock at each batch's godown; a
    batch's destination godown (Material In/Out) doesn't move stock in Tally's balances."""
    line = _inventory(entry, inward)
    if line is None:
        return []
    batches = entry.findall("BATCHALLOCATIONS.LIST")
    godowns = {_text(b, "GODOWNNAME") for b in batches}
    if len(batches) < 2 or len(godowns) < 2:
        return [line]
    lines = []
    for batch in batches:
        quantity, _ = _quantity(_text(batch, "ACTUALQTY") or _text(batch, "BILLEDQTY"))
        if not quantity:
            return [line]  # quantities not split by batch: keep the entry whole
        signed = abs(quantity) if line.quantity >= 0 else -abs(quantity)
        amount = _canonical(tally_amount(_text(batch, "AMOUNT")))
        lines.append(
            replace(
                line,
                quantity=signed,
                amount=amount if _text(batch, "AMOUNT") else line.amount * signed / line.quantity,
                godown_name=_text(batch, "GODOWNNAME"),
                batch_name=_text(batch, "BATCHNAME"),
                tracked_quantity=signed if _tracking(batch) else Decimal(0),
            )
        )
    return lines


def _tracking(batch: ET.Element) -> str | None:
    number = _text(batch, "TRACKINGNUMBER")
    return None if number in (None, "", NOT_APPLICABLE) else number


def _tracked(entry: ET.Element, quantity: Decimal) -> Decimal:
    """How much of an inventory entry is tied to a tracking number (a delivery or receipt
    note, or a rejection), unsigned. Checked on the test company (2026-10-14): a sales,
    purchase, debit or credit note line with a tracking number never moves stock, whether
    the note came before or after it; the note does. The transform applies this to
    vouchers that post to the books only: a note's own lines carry its own number."""
    batches = entry.findall("BATCHALLOCATIONS.LIST")
    tracked = [b for b in batches if _tracking(b)]
    if not tracked:
        return Decimal(0)
    if len(tracked) == len(batches):
        return quantity
    total = Decimal(0)
    for batch in tracked:
        part, _ = _quantity(_text(batch, "ACTUALQTY") or _text(batch, "BILLEDQTY"))
        total += abs(part)
    return min(total, quantity)


def voucher(element: ET.Element, key: str) -> CanonicalVoucher:
    voucher_date = parser.tally_date(_text(element, "DATE"))
    if voucher_date is None:
        raise MappingError("voucher without DATE")
    voucher_type_name = _text(element, "VOUCHERTYPENAME")
    if not voucher_type_name:
        raise MappingError("voucher without VOUCHERTYPENAME")
    inventory_entries: list[tuple[ET.Element, bool | None]] = [
        (e, None)
        for e in element.findall("ALLINVENTORYENTRIES.LIST")
        or element.findall("INVENTORYENTRIES.LIST")
    ]
    if not inventory_entries:
        # Stock journals (and manufacturing journals) also list produced (in) and consumed
        # (out) items apart. TallyPrime repeats them in ALLINVENTORYENTRIES with the right
        # ISDEEMEDPOSITIVE (checked on the test company, 2026-10-15), so these lists are read
        # only when the full list is missing: reading both counted each entry twice.
        inventory_entries += [(e, True) for e in element.findall("INVENTORYENTRIESIN.LIST")]
        inventory_entries += [(e, False) for e in element.findall("INVENTORYENTRIESOUT.LIST")]
    return CanonicalVoucher(
        source_key=key,
        voucher_type_name=voucher_type_name,
        voucher_number=_text(element, "VOUCHERNUMBER") or "",
        voucher_date=voucher_date,
        lines=tuple(_line(entry) for entry in postings(element)),
        inventory=tuple(
            line for e, inward in inventory_entries for line in _inventory_lines(e, inward)
        ),
        reference_number=_text(element, "REFERENCE"),
        reference_date=parser.tally_date(_text(element, "REFERENCEDATE")),
        effective_date=parser.tally_date(_text(element, "EFFECTIVEDATE")),
        party_ledger_name=_text(element, "PARTYLEDGERNAME"),
        narration=_text(element, "NARRATION"),
        is_cancelled=_flag(element, "ISCANCELLED"),
        is_optional=_flag(element, "ISOPTIONAL"),
        is_post_dated=_flag(element, "ISPOSTDATED"),
    )


# --- fields the mapping doesn't use (ADR-025) ---------------------------------------------

_IDENTITY = (
    "GUID", "ALTERID", "MASTERID", "NAME",
    "LANGUAGENAME.LIST/NAME.LIST/NAME", "LANGUAGENAME.LIST/LANGUAGEID",
)  # fmt: skip
_MASTER = (*_IDENTITY, "PARENT")
_LEDGER_ENTRY = (
    "LEDGERNAME", "AMOUNT", "ISDEEMEDPOSITIVE", "ISPARTYLEDGER",
    "BILLALLOCATIONS.LIST/NAME", "BILLALLOCATIONS.LIST/BILLTYPE", "BILLALLOCATIONS.LIST/AMOUNT",
    "CATEGORYALLOCATIONS.LIST/CATEGORY",
    "CATEGORYALLOCATIONS.LIST/COSTCENTREALLOCATIONS.LIST/NAME",
    "CATEGORYALLOCATIONS.LIST/COSTCENTREALLOCATIONS.LIST/AMOUNT",
)  # fmt: skip
_INVENTORY_ENTRY = (
    "STOCKITEMNAME", "ACTUALQTY", "BILLEDQTY", "RATE", "AMOUNT", "ISDEEMEDPOSITIVE",
    "DISCOUNT", "BATCHALLOCATIONS.LIST/GODOWNNAME", "BATCHALLOCATIONS.LIST/BATCHNAME",
    "BATCHALLOCATIONS.LIST/TRACKINGNUMBER", "BATCHALLOCATIONS.LIST/ACTUALQTY",
    *(f"ACCOUNTINGALLOCATIONS.LIST/{path}" for path in _LEDGER_ENTRY),
)  # fmt: skip
# Paths (below the object; list levels included) each object type's mapping reads.
USED_FIELDS: dict[str, frozenset[str]] = {
    "company": frozenset((
        *_IDENTITY, "BOOKSFROM", "STARTINGFROM", "BASICCOMPANYFORMALNAME", "STATENAME",
        "GSTREGISTRATIONNUMBER", "INCOMETAXNUMBER",
    )),
    "group": frozenset((*_MASTER, "ISREVENUE", "ISDEEMEDPOSITIVE", "AFFECTSGROSSPROFIT")),
    "ledger": frozenset((
        *_MASTER, "OPENINGBALANCE", "ISBILLWISEON", "ISCOSTCENTRESON", "TAXTYPE",
        "GSTDUTYHEAD", "PARTYGSTIN", "LEDGSTREGDETAILS.LIST/GSTIN", "INCOMETAXNUMBER",
        "LEDSTATENAME", "LEDMAILINGDETAILS.LIST/STATE", "COUNTRYNAME", "EMAIL",
        "LEDGERPHONE", "LEDGERMOBILE", "BILLCREDITPERIOD", "CREDITLIMIT",
    )),
    "voucher_type": frozenset((*_MASTER, "AFFECTSSTOCK")),
    "unit": frozenset((*_IDENTITY, "ORIGINALNAME", "DECIMALPLACES")),
    "stock_group": frozenset(_MASTER),
    "godown": frozenset((*_MASTER, "ISEXTERNAL", "ISINTERNAL")),
    "stock_item": frozenset((*_MASTER, "BASEUNITS", "OPENINGBALANCE", "OPENINGVALUE")),
    "cost_centre": frozenset((*_MASTER, "CATEGORY")),
    "voucher": frozenset((
        *_IDENTITY, "DATE", "EFFECTIVEDATE", "VOUCHERTYPENAME", "VOUCHERNUMBER", "REFERENCE",
        "REFERENCEDATE",
        "PARTYLEDGERNAME", "NARRATION", "ISCANCELLED", "ISOPTIONAL", "ISPOSTDATED",
        *(f"{lst}/{path}" for lst in ("ALLLEDGERENTRIES.LIST", "LEDGERENTRIES.LIST")
          for path in _LEDGER_ENTRY),
        *(f"{lst}/{path}" for lst in (
            "ALLINVENTORYENTRIES.LIST", "INVENTORYENTRIES.LIST", "INVENTORYENTRIESIN.LIST",
            "INVENTORYENTRIESOUT.LIST",
        ) for path in _INVENTORY_ENTRY),
    )),
}  # fmt: skip


# Tally's own bookkeeping, with no meaning in the books: left out of `extra` (still in the raw
# record). A ledger entry's INVENTORYALLOCATIONS repeat the voucher's inventory entries.
_TALLY_INTERNAL = frozenset((
    "VOUCHERKEY", "VOUCHERRETAINKEY", "REUSEHOLEID", "PERSISTEDVIEW", "NUMBERINGSTYLE",
    "ASORIGINAL", "ASPAYSLIP", "ISNEGISPOSSET", "ISDELETEDVCHRETAINED", "ISLASTDEEMEDPOSITIVE",
    "ISDELETED",
))  # fmt: skip
_DUPLICATES = frozenset(
    f"{lst}/INVENTORYALLOCATIONS.LIST" for lst in ("ALLLEDGERENTRIES.LIST", "LEDGERENTRIES.LIST")
)


def unmapped_fields(element: ET.Element, object_type: str) -> dict[str, Any] | None:
    """Every field with a value that the mapping doesn't read, by path below the object,
    with prefixed names as the source wrote them (e.g. UDF:REFNO.LIST/UDF:REFNO). A path
    that repeats (e.g. one per ledger entry) holds a list. Attributes aren't fields."""
    used = USED_FIELDS.get(object_type, frozenset())
    found: dict[str, list[str]] = {}

    def walk(node: ET.Element, prefix: str) -> None:
        for child in node:
            tag = parser.restore_name(child.tag)
            path = f"{prefix}/{tag}" if prefix else tag
            if tag in _TALLY_INTERNAL or path in _DUPLICATES:
                continue
            if len(child):
                walk(child, path)
                continue
            value = (child.text or "").strip()
            if value and path not in used:
                found.setdefault(path, []).append(value)

    walk(element, "")
    return {path: v[0] if len(v) == 1 else v for path, v in found.items()} or None


# --- entry point -----------------------------------------------------------------------


def to_canonical(record: SourceRecord) -> list[CanonicalRecord]:
    """One raw Tally record → canonical records (usually one)."""
    try:
        # Stored as received, so custom fields keep their undeclared prefixes (e.g. UDF:).
        element = ET.fromstring(parser.neutralise_prefixes(record.payload))  # noqa: S314
    except ET.ParseError as exc:
        raise MappingError(f"{record.object_type} payload is not valid XML") from exc
    records = _records(record, element)
    extra = unmapped_fields(element, record.object_type)
    if extra is None:
        return records
    # The object's own record carries them (not e.g. the synthetic Primary group).
    return [replace(r, extra=extra) if r.source_key == record.source_key else r for r in records]


def _records(record: SourceRecord, element: ET.Element) -> list[CanonicalRecord]:
    key = record.source_key
    match record.object_type:
        case "company":
            return [company(element, key)]
        case "group":
            return [group(element, key)]
        case "ledger":
            return ledger(element, key, record.source_entity_key)
        case "voucher_type":
            return [voucher_type(element, key)]
        case "unit":
            return [unit(element, key)]
        case "stock_group":
            return [CanonicalItemGroup(key, _name(element), _parent(element))]
        case "godown":
            return [CanonicalGodown(key, _name(element), _parent(element), _holding(element))]
        case "stock_item":
            return [stock_item(element, key)]
        case "cost_centre":
            return [
                CanonicalCostCentre(
                    key, _name(element), _parent(element), _text(element, "CATEGORY")
                )
            ]
        case "voucher":
            return [voucher(element, key)]
    raise MappingError(f"no mapping for object type {record.object_type}")
