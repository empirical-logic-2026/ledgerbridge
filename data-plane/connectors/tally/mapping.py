"""Tally objects → canonical records (schema.md Section 7): what Tally's data means.

Where it fits: the sync stores Tally's objects unchanged (`parser.py`); the transform
(`core/transform.py`) later calls `to_canonical` on each stored record and writes the
canonical records it returns into the accounting tables. All Tally knowledge of meaning
lives here: reserved groups, voucher types, signs, quantities, bills, godowns.

Signs: canonical amount = −(Tally amount) for every amount (schema.md 7.1).
Postings: connectors.tally.signs.postings implements the rules of schema.md 7.2.
"""

import re
import xml.etree.ElementTree as ET  # noqa: N817
from dataclasses import replace
from decimal import Decimal
from typing import Any

from connectors.base import SourceRecord
from connectors.tally import parser
from connectors.tally.parser import text_of
from connectors.tally.signs import (
    postings,
    tally_amount,
    tally_foreign_parts,
    tally_foreign_unread,
)
from core.canonical import (
    NO_STANDARD_ACCOUNT,
    CanonicalBill,
    CanonicalCompany,
    CanonicalCostCentre,
    CanonicalCurrency,
    CanonicalGodown,
    CanonicalGroup,
    CanonicalInventoryLine,
    CanonicalItem,
    CanonicalItemGroup,
    CanonicalLedger,
    CanonicalLine,
    CanonicalParty,
    CanonicalRate,
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


def predefined_role(reserved: str | None) -> str | None:
    """A reserved group's role in our vocabulary: its reserved name in lower case, words
    joined by "_" ("Sales Accounts" -> "sales_accounts"); None for other groups."""
    if reserved not in RESERVED_GROUPS:
        return None
    return "_".join(re.findall(r"[a-z0-9]+", reserved.lower()))


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


def _foreign(text: str | None) -> tuple[str | None, Decimal | None, Decimal | None]:
    """(currency as written, foreign amount in the canonical sign, rate) of an amount in a
    foreign currency; (None, None, None) in the base currency."""
    parts = tally_foreign_parts(text)
    if parts is None or not parts[1]:
        return None, None, None
    symbol, amount, rate = parts
    return symbol or None, -amount, rate


def _flag(element: ET.Element, path: str) -> bool:
    return (text_of(element, path) or "").lower() == "yes"


def _canonical(value: Decimal | None) -> Decimal:
    """Tally sign → canonical sign (schema.md 7.1)."""
    return -value if value else Decimal(0)


def _amount(element: ET.Element, path: str) -> Decimal:
    """An amount field in the canonical sign (zero when empty)."""
    return _canonical(tally_amount(text_of(element, path)))


def quantity(text: str | None) -> tuple[Decimal, str | None]:
    """A Tally quantity, (number, unit): ' 10 Nos' → (10, 'Nos'); ' 1.5 Kg' → (1.5, 'Kg')."""
    if not text:
        return Decimal(0), None
    match = _NUMBER.search(text)
    if not match:
        return Decimal(0), None
    unit = text[match.end() :].strip() or None
    return Decimal(match.group(0)), unit


def _entry_quantity(entry: ET.Element) -> tuple[Decimal, str | None]:
    """An inventory entry's or batch's quantity: the actual quantity, else the billed one."""
    return quantity(text_of(entry, "ACTUALQTY") or text_of(entry, "BILLEDQTY"))


def _rate(text: str | None) -> Decimal | None:
    """'200.00/Nos' → 200.00."""
    if not text:
        return None
    match = _NUMBER.search(text)
    return Decimal(match.group(0)) if match else None  # the pattern only matches numbers


def _is_primary(name: str | None) -> bool:
    return name is None or normalise(name) == normalise(PRIMARY)


def _parent(element: ET.Element) -> str | None:
    parent = text_of(element, "PARENT")
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
    books_from = parser.tally_date(text_of(element, "BOOKSFROM"))
    starting = parser.tally_date(text_of(element, "STARTINGFROM")) or books_from
    gstin = text_of(element, "GSTREGISTRATIONNUMBER")
    return CanonicalCompany(
        source_key=key,
        name=_name(element),
        legal_name=text_of(element, "BASICCOMPANYFORMALNAME"),
        books_from=books_from,
        fy_start_month=starting.month if starting else 4,
        state_code=_state_code(text_of(element, "STATENAME")) or (gstin[:2] if gstin else None),
        gstin=gstin,
        pan=text_of(element, "INCOMETAXNUMBER"),
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
        predefined_role=predefined_role(reserved),
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
    tax = text_of(element, "TAXTYPE")
    if tax == "GST":
        head = text_of(element, "GSTDUTYHEAD")
        if head is None:
            return GST_DUTY_HEADS["Central Tax"], (EMPTY_DUTY_HEAD_WARNING,)
        return GST_DUTY_HEADS.get(head, "other"), ()
    return TAX_TYPES.get(tax or ""), ()


def ledger(element: ET.Element, key: str, entity_key: str) -> list[CanonicalRecord]:
    parent = text_of(element, "PARENT")
    parent = PRIMARY if _is_primary(parent) else parent
    credit_days = _NUMBER.search(text_of(element, "BILLCREDITPERIOD") or "")
    credit_limit = tally_amount(text_of(element, "CREDITLIMIT"))
    gstin = text_of(element, "PARTYGSTIN") or text_of(element, ".//LEDGSTREGDETAILS.LIST/GSTIN")
    state = text_of(element, "LEDSTATENAME") or text_of(element, ".//LEDMAILINGDETAILS.LIST/STATE")
    tax_type, warnings = _tax_type(element)
    name = _name(element)
    opening_currency, opening_fc, _ = _foreign(text_of(element, "OPENINGBALANCE"))
    record = CanonicalLedger(
        source_key=key,
        name=name,
        group_name=parent,
        opening_balance=_amount(element, "OPENINGBALANCE"),
        currency_name=text_of(element, "CURRENCYNAME"),
        opening_currency_name=opening_currency,
        opening_balance_fc=opening_fc,
        opening_foreign_unread=tally_foreign_unread(text_of(element, "OPENINGBALANCE")),
        is_bill_wise=_flag(element, "ISBILLWISEON"),
        is_cost_centre_applicable=_flag(element, "ISCOSTCENTRESON"),
        gstin=gstin,
        tax_type=tax_type,
        party=CanonicalParty(
            gstin=gstin,
            pan=text_of(element, "INCOMETAXNUMBER"),
            state_code=_state_code(state) or (gstin[:2] if gstin else None),
            country_code="IN" if (text_of(element, "COUNTRYNAME") or "India") == "India" else None,
            credit_days=int(credit_days.group(0)) if credit_days else None,
            credit_limit=abs(credit_limit) if credit_limit else None,
            email=text_of(element, "EMAIL"),
            phone=text_of(element, "LEDGERMOBILE") or text_of(element, "LEDGERPHONE"),
        ),
        default_standard_account_code=STANDARD_ACCOUNT_BY_TAX_TYPE.get(
            text_of(element, "TAXTYPE") or ""
        ),
        warnings=warnings,
        aliases=_aliases(element, name),
    )
    return [_primary_group(entity_key), record] if parent == PRIMARY else [record]


_ISO = re.compile(r"^[A-Z]{3}$")
RATE_LISTS = {
    "DAILYSTDRATES.LIST": "standard",
    "DAILYBUYINGRATES.LIST": "buying",
    "DAILYSELLINGRATES.LIST": "selling",
}


def currency(element: ET.Element, key: str) -> CanonicalCurrency:
    """A currency master: the name it is written with in amounts (ORIGINALNAME, else NAME),
    its ISO code (EXPANDEDSYMBOL or ISOCURRENCYCODE when three capital letters), formal name
    and decimals, and its rate lists. The lists' inner fields weren't known when this was
    written (none on the test company), so each entry is read as its first date field and
    its first other number: entries without both are left out (and counted by the fx-rules
    command, which reports what was read)."""
    code = next(
        (c for c in (text_of(element, "EXPANDEDSYMBOL"), text_of(element, "ISOCURRENCYCODE"))
         if c and _ISO.match(c.strip())),
        None,
    )  # fmt: skip
    decimals = _NUMBER.search(text_of(element, "DECIMALPLACES") or "")
    return CanonicalCurrency(
        source_key=key,
        name=text_of(element, "ORIGINALNAME") or _name(element),
        code=code.strip() if code else None,
        formal_name=text_of(element, "MAILINGNAME"),
        decimal_places=int(decimals.group(0)) if decimals else None,
        rates=tuple(_rates(element)),
    )


def _rates(element: ET.Element) -> list[CanonicalRate]:
    found = []
    for tag, kind in RATE_LISTS.items():
        for entry in element.findall(tag):
            on, rate = None, None
            for child in entry.iter():
                text = (child.text or "").strip()
                if not text or child is entry:
                    continue
                if on is None and "DATE" in child.tag.upper():
                    on = parser.tally_date(text)
                elif rate is None and "DATE" not in child.tag.upper():
                    value = tally_amount(text)
                    rate = abs(value) if value else None
            if on is not None and rate:
                found.append(CanonicalRate(kind, on, rate))
    return found


def voucher_type(element: ET.Element, key: str) -> CanonicalVoucherType:
    """A predefined type (RESERVEDNAME), or a type created under another (PARENT). A type
    under a custom type inherits its standard type through the voucher type tree (the
    transform resolves it), so e.g. a "Cash Sale 2" under "Cash Sale" under "Sales" is a
    sale, and one under "Sales Order" doesn't post to the books."""
    name = _name(element)
    parent = text_of(element, "PARENT")
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
    places = text_of(element, "DECIMALPLACES")
    return CanonicalUnit(
        source_key=key,
        symbol=symbol,
        name=text_of(element, "ORIGINALNAME") or symbol,
        decimal_places=int(places) if places and places.isdigit() else 0,
    )


def stock_item(element: ET.Element, key: str) -> CanonicalItem:
    opening_qty, _ = quantity(text_of(element, "OPENINGBALANCE"))
    return CanonicalItem(
        source_key=key,
        name=_name(element),
        group_name=_parent(element),
        unit_name=text_of(element, "BASEUNITS"),
        opening_qty=opening_qty,
        opening_value=_amount(element, "OPENINGVALUE"),
    )


# --- vouchers --------------------------------------------------------------------------


def _line(entry: ET.Element) -> CanonicalLine:
    bills = tuple(
        CanonicalBill(
            bill_type=BILL_TYPES.get(text_of(bill, "BILLTYPE") or "", "on_account"),
            name=text_of(bill, "NAME"),
            amount=_amount(bill, "AMOUNT"),
        )
        for bill in entry.findall("BILLALLOCATIONS.LIST")
        if text_of(bill, "AMOUNT") or text_of(bill, "NAME")
    )
    cost_allocations = tuple(
        (name, _amount(alloc, "AMOUNT"))
        for category in entry.findall("CATEGORYALLOCATIONS.LIST")
        for alloc in category.findall("COSTCENTREALLOCATIONS.LIST")
        if (name := text_of(alloc, "NAME"))
    )
    currency, amount_fc, rate = _foreign(text_of(entry, "AMOUNT"))
    return CanonicalLine(
        ledger_name=text_of(entry, "LEDGERNAME") or "",
        amount=_amount(entry, "AMOUNT"),
        amount_fc=amount_fc,
        currency_name=currency,
        exchange_rate=rate,
        foreign_unread=tally_foreign_unread(text_of(entry, "AMOUNT")),
        is_party_line=_flag(entry, "ISPARTYLEDGER"),
        bills=bills,
        cost_allocations=cost_allocations,
    )


def _inventory(entry: ET.Element, inward: bool | None = None) -> CanonicalInventoryLine | None:
    """One inventory entry. `inward` is given for stock journal entries (in: produced or
    received; out: consumed or sent), otherwise ISDEEMEDPOSITIVE decides."""
    item = text_of(entry, "STOCKITEMNAME")
    if not item:
        return None
    entry_qty, unit_name = _entry_quantity(entry)
    inward = _is_inward(entry, inward)
    batch = entry.find("BATCHALLOCATIONS.LIST")
    discount = _rate(text_of(entry, "DISCOUNT"))
    tracked = _tracked(entry, abs(entry_qty))
    return CanonicalInventoryLine(
        item_name=item,
        quantity=abs(entry_qty) if inward else -abs(entry_qty),
        tracked_quantity=tracked if inward else -tracked,
        amount=_amount(entry, "AMOUNT"),
        unit_name=unit_name,
        rate=_rate(text_of(entry, "RATE")),
        godown_name=text_of(batch, "GODOWNNAME") if batch is not None else None,
        batch_name=text_of(batch, "BATCHNAME") if batch is not None else None,
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


def _is_inward(entry: ET.Element, inward: bool | None) -> bool:
    """The entry's direction: given for stock journal entries, else ISDEEMEDPOSITIVE."""
    return _flag(entry, "ISDEEMEDPOSITIVE") if inward is None else inward


def _inventory_lines(entry: ET.Element, inward: bool | None) -> list[CanonicalInventoryLine]:
    """An inventory entry as lines: one per batch allocation when its stock sits in more
    than one godown (each with its own quantity, amount and tracking), so stock is known
    per godown; otherwise one line. Tally keeps the stock at each batch's godown; a
    batch's destination godown (Material In/Out) doesn't move stock in Tally's balances."""
    line = _inventory(entry, inward)
    if line is None:
        return []
    batches = entry.findall("BATCHALLOCATIONS.LIST")
    godowns = {text_of(b, "GODOWNNAME") for b in batches}
    if len(batches) < 2 or len(godowns) < 2:
        return [line]
    if not line.quantity and any(not text_of(b, "AMOUNT") for b in batches):
        # A batch without an amount gets its share by quantity, which needs the entry's
        # own quantity: without one the amount can't be shared, so keep the entry whole.
        return [line]
    # The direction comes from the entry itself: an entry quantity of zero has no sign.
    inward = _is_inward(entry, inward)
    lines = []
    for batch in batches:
        batch_qty, _ = _entry_quantity(batch)
        if not batch_qty:
            return [line]  # quantities not split by batch: keep the entry whole
        signed = abs(batch_qty) if inward else -abs(batch_qty)
        amount = _amount(batch, "AMOUNT")
        lines.append(
            replace(
                line,
                quantity=signed,
                amount=amount if text_of(batch, "AMOUNT") else line.amount * signed / line.quantity,
                godown_name=text_of(batch, "GODOWNNAME"),
                batch_name=text_of(batch, "BATCHNAME"),
                tracked_quantity=signed if _tracking(batch) else Decimal(0),
            )
        )
    return lines


def _tracking(batch: ET.Element) -> str | None:
    number = text_of(batch, "TRACKINGNUMBER")
    return None if number in (None, "", NOT_APPLICABLE) else number


def _tracked(entry: ET.Element, entry_qty: Decimal) -> Decimal:
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
        return entry_qty
    total = sum((abs(_entry_quantity(batch)[0]) for batch in tracked), Decimal(0))
    return min(total, entry_qty)


def voucher(element: ET.Element, key: str) -> CanonicalVoucher:
    voucher_date = parser.tally_date(text_of(element, "DATE"))
    if voucher_date is None:
        raise MappingError("voucher without DATE")
    voucher_type_name = text_of(element, "VOUCHERTYPENAME")
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
        voucher_number=text_of(element, "VOUCHERNUMBER") or "",
        voucher_date=voucher_date,
        lines=tuple(_line(entry) for entry in postings(element)),
        inventory=tuple(
            line for e, inward in inventory_entries for line in _inventory_lines(e, inward)
        ),
        reference_number=text_of(element, "REFERENCE"),
        reference_date=parser.tally_date(text_of(element, "REFERENCEDATE")),
        effective_date=parser.tally_date(text_of(element, "EFFECTIVEDATE")),
        party_ledger_name=text_of(element, "PARTYLEDGERNAME"),
        narration=text_of(element, "NARRATION"),
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
        "LEDGERPHONE", "LEDGERMOBILE", "BILLCREDITPERIOD", "CREDITLIMIT", "CURRENCYNAME",
    )),
    # Read whole (`native`): only the fields kept are listed; the rest stays in the raw
    # record without being catalogued (a currency master has dozens of internal fields).
    "currency": frozenset((
        *_MASTER, "ORIGINALNAME", "EXPANDEDSYMBOL", "ISOCURRENCYCODE", "MAILINGNAME",
        "DECIMALPLACES",
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
        case "currency":
            return [currency(element, key)]
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
                    key, _name(element), _parent(element), text_of(element, "CATEGORY")
                )
            ]
        case "voucher":
            return [voucher(element, key)]
    raise MappingError(f"no mapping for object type {record.object_type}")
