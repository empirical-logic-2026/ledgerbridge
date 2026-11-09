"""Source-independent canonical records (architecture.md 4.4, DAT-003).

Where it fits: the contract between a connector and the transform. A connector's
`to_canonical()` turns one raw record into one of these; the transform (core/transform.py)
writes them to ledgerbridge_accounting. Nothing here knows any source.

Conventions: amounts use the canonical sign (debit positive, credit negative, schema.md
Section 1). Other objects are referred to by name within the same entity, because sources
such as Tally refer to masters by name rather than by key.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

# A group's standard_account_code meaning "no standard account here": stops sub-groups and
# ledgers inheriting a mapping from further up the tree.
NO_STANDARD_ACCOUNT = "-"


def _extra() -> Any:
    """Fields the source sent that the mapping doesn't use (e.g. custom fields), by path:
    stored in the row's `extra` JSON and catalogued (ADR-025). Not part of equality."""
    return field(default=None, compare=False, hash=False)


@dataclass(frozen=True)
class CanonicalCompany:
    source_key: str
    name: str
    legal_name: str | None = None
    books_from: date | None = None
    fy_start_month: int = 4
    country_code: str = "IN"
    state_code: str | None = None
    gstin: str | None = None
    pan: str | None = None
    base_currency_code: str = "INR"
    # Settings (None: not read): accounts integrated with inventory, stock valued FIFO, and
    # the books audited up to a date.
    is_integrated: bool | None = None
    is_fifo: bool | None = None
    audited_upto: date | None = None
    extra: Mapping[str, Any] | None = _extra()


@dataclass(frozen=True)
class CanonicalGroup:
    source_key: str
    name: str
    parent_name: str | None
    nature: str | None = None  # asset/liability/equity/income/expense
    is_primary: bool = False
    affects_gross_profit: bool = False
    # The source's own predefined group this is, renamed or not, in our vocabulary (e.g.
    # "sales_accounts"); None for groups the user created. Not inherited.
    predefined_role: str | None = None
    # Hints inherited by sub-groups and ledgers (the transform walks the group tree):
    standard_account_code: str | None = None
    ledger_kind: str | None = None  # bank/cash/tax/party/stock
    party_type: str | None = None  # customer/vendor
    # Other names the source may refer to it by (e.g. the reserved name of a Tally group the
    # user renamed): references resolve to it by these if no other group has them (ADR-027).
    aliases: tuple[str, ...] = ()
    # Where the source lists it among its siblings (Tally SORTPOSITION; None: not read).
    sort_position: int | None = None
    extra: Mapping[str, Any] | None = _extra()


@dataclass(frozen=True)
class CanonicalParty:
    party_type: str | None = None  # None: taken from the group hint
    gstin: str | None = None
    pan: str | None = None
    state_code: str | None = None
    country_code: str | None = None
    credit_days: int | None = None
    credit_limit: Decimal | None = None
    email: str | None = None
    phone: str | None = None
    gst_registration_type: str | None = None  # Regular, Composition, Unregistered, ...


@dataclass(frozen=True)
class CanonicalLedger:
    source_key: str
    name: str
    group_name: str
    opening_balance: Decimal = Decimal(0)
    opening_balance_date: date | None = None
    currency_code: str = "INR"
    # The ledger's own currency as the source names it (e.g. "$"; Tally CURRENCYNAME), and
    # the currency and amount of its opening's foreign part when it has one (FX-001): a
    # ledger the source keeps in the base currency can still open in dollars (the test
    # company, 2026-10-24). The base-currency opening stays the books' figure.
    currency_name: str | None = None
    opening_currency_name: str | None = None
    opening_balance_fc: Decimal | None = None
    opening_foreign_unread: bool = False  # written in a foreign currency, but not readable
    is_bill_wise: bool = False
    is_cost_centre_applicable: bool = False
    gstin: str | None = None
    tax_type: str | None = None  # cgst/sgst/igst/cess/tds/tcs/vat/other for tax ledgers
    party: CanonicalParty | None = None  # details, used if the group makes it a party
    # Used only when the ledger's group tree gives no standard account (e.g. by tax type).
    default_standard_account_code: str | None = None
    # Assumptions the connector made for this record; reported in the sync output.
    warnings: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()  # other names references may use (ADR-027)
    sort_position: int | None = None  # where the source lists it (Tally SORTPOSITION)
    affects_stock: bool | None = None  # Tally AFFECTSSTOCK (None: not read)
    extra: Mapping[str, Any] | None = _extra()


@dataclass(frozen=True)
class CanonicalRate:
    """One dated rate from a currency's own rate list (base per unit)."""

    kind: str  # standard / buying / selling
    rate_date: date
    rate: Decimal


@dataclass(frozen=True)
class CanonicalCurrency:
    """A currency as a source keeps it (Tally: a currency master): the name it writes in
    amounts (e.g. "$"), its ISO code when the source gives one, and its rate lists."""

    source_key: str
    name: str
    code: str | None = None  # ISO 4217, e.g. USD
    # Other names records may refer to it by (Tally: the master's NAME when its ORIGINALNAME
    # differs): a ledger's currency is matched by any of them.
    aliases: tuple[str, ...] = ()
    formal_name: str | None = None
    decimal_places: int | None = None
    rates: tuple[CanonicalRate, ...] = ()
    extra: Mapping[str, Any] | None = _extra()


@dataclass(frozen=True)
class CanonicalVoucherType:
    source_key: str
    name: str
    # None: inherited from the parent type (the transform walks the voucher type tree).
    base_type: str | None
    is_accounting: bool | None = True
    is_inventory: bool = False
    parent_name: str | None = None
    # The source's own standard type this one derives from (e.g. Tally's "Sales Order"),
    # from a fixed list of the source's standard names; None for custom names.
    standard_type: str | None = None
    # Whether its inventory entries move stock (orders don't); None: inherited.
    moves_stock: bool | None = True
    # Its voucher numbering series, all of them (replacing the ones stored).
    number_series: tuple["CanonicalNumberSeries", ...] = ()
    extra: Mapping[str, Any] | None = _extra()


@dataclass(frozen=True)
class CanonicalNumberSeries:
    """A voucher type's numbering series (Tally: VOUCHERNUMBERSERIES.LIST), e.g. "Default"."""

    name: str
    numbering_method: str | None = None  # Automatic, Manual, ...
    numbering_sub_method: str | None = None  # Auto Retain, Auto Renumber, ...
    beginning_number: int | None = None
    width: int | None = None
    prefill_zero: bool = False
    prevent_duplicates: bool = False


@dataclass(frozen=True)
class CanonicalUnit:
    source_key: str
    symbol: str
    name: str
    decimal_places: int = 0
    extra: Mapping[str, Any] | None = _extra()


@dataclass(frozen=True)
class CanonicalStockCategory:
    """A stock category: a second way of grouping stock items, across their groups."""

    source_key: str
    name: str
    parent_name: str | None
    extra: Mapping[str, Any] | None = _extra()


@dataclass(frozen=True)
class CanonicalItemPrice:
    """A price in a stock item's price list: for a price level, from a date, for a quantity
    range (both ends None: any quantity), with its discount."""

    price_level: str
    applicable_from: date | None
    rate: Decimal | None
    from_quantity: Decimal | None = None
    to_quantity: Decimal | None = None
    discount_pct: Decimal | None = None


@dataclass(frozen=True)
class CanonicalBudgetLine:
    """A ledger's budget for a period: on its net transactions or its closing balance."""

    ledger_name: str
    period_from: date | None
    period_to: date | None
    basis: str  # net_transactions / closing_balance
    amount: Decimal  # as the source writes it (see schema.md: source_budget_lines)


@dataclass(frozen=True)
class CanonicalBudget:
    """A budget kept in the source (Tally: Budget), with its lines, all of them."""

    source_key: str
    name: str
    parent_name: str | None
    use_actuals: bool | None = None
    lines: tuple[CanonicalBudgetLine, ...] = ()
    extra: Mapping[str, Any] | None = _extra()


@dataclass(frozen=True)
class CanonicalItemGroup:
    source_key: str
    name: str
    parent_name: str | None
    extra: Mapping[str, Any] | None = _extra()


@dataclass(frozen=True)
class CanonicalOpeningBatch:
    """Part of a stock item's opening: its quantity, rate and value at one godown and batch
    (canonical sign: stock on hand is a positive value)."""

    godown_name: str | None
    batch_name: str | None
    quantity: Decimal
    rate: Decimal | None
    value: Decimal


@dataclass(frozen=True)
class CanonicalItem:
    source_key: str
    name: str
    group_name: str | None
    unit_name: str | None
    opening_qty: Decimal = Decimal(0)
    opening_value: Decimal = Decimal(0)
    # The opening by godown and batch, all of it (replacing the one stored).
    opening_batches: tuple[CanonicalOpeningBatch, ...] = ()
    # GST: the HSN/SAC code, the integrated rate (IGST, or CGST + SGST), taxability
    # (Taxable, Exempt, Nil Rated, ...) and the HSN classification the item uses.
    hsn_code: str | None = None
    gst_rate: Decimal | None = None
    gst_taxability: str | None = None
    gst_classification: str | None = None
    # Its stock category, reorder level and minimum order quantity (base units), and its
    # price list, all of it (replacing the one stored).
    category_name: str | None = None
    reorder_level: Decimal | None = None
    min_order_quantity: Decimal | None = None
    prices: tuple[CanonicalItemPrice, ...] = ()
    extra: Mapping[str, Any] | None = _extra()


@dataclass(frozen=True)
class CanonicalGodown:
    source_key: str
    name: str
    parent_name: str | None
    # Whose stock it holds: own; ours_with_third_party (e.g. a job worker's location: the
    # source leaves it out of stock balances); third_party_with_us (counted by the source).
    holding: str = "own"
    extra: Mapping[str, Any] | None = _extra()


@dataclass(frozen=True)
class CanonicalTaxUnit:
    """A tax registration of the company (Tally: Tax Unit), e.g. one GSTIN per state."""

    source_key: str
    name: str
    gstin: str | None = None
    state: str | None = None
    registration_type: str | None = None
    registered_from: date | None = None
    used_for: str | None = None  # GST, TDS, ...
    is_primary: bool = False
    extra: Mapping[str, Any] | None = _extra()


@dataclass(frozen=True)
class CanonicalGstRate:
    """A GST rate on a voucher line, per duty head (CGST, SGST/UTGST, IGST, Cess, ...)."""

    duty_head: str
    rate: Decimal


@dataclass(frozen=True)
class CanonicalCostCategory:
    """A cost category: a set of cost centres a line's amount is allocated over (one line
    can be allocated in several categories, each in full)."""

    source_key: str
    name: str
    extra: Mapping[str, Any] | None = _extra()


@dataclass(frozen=True)
class CanonicalCostCentre:
    source_key: str
    name: str
    parent_name: str | None
    category: str | None = None
    extra: Mapping[str, Any] | None = _extra()


@dataclass(frozen=True)
class CanonicalCostAllocation:
    """A line's amount allocated to a cost centre in a cost category (canonical sign, as
    the line's)."""

    category: str | None
    cost_centre: str
    amount: Decimal


@dataclass(frozen=True)
class CanonicalBill:
    bill_type: str  # new_ref/against_ref/advance/on_account
    name: str | None
    amount: Decimal
    bill_date: date | None = None
    due_date: date | None = None  # the credit period applied to the bill's date, or a date


@dataclass(frozen=True)
class CanonicalOpeningBill:
    """One bill of a ledger's opening balance (canonical sign, debit positive)."""

    name: str
    amount: Decimal
    bill_date: date | None = None
    due_date: date | None = None


@dataclass(frozen=True)
class CanonicalOpeningBills:
    """A ledger's opening bills, all of them (replacing the ones stored); `source_key` is
    the ledger's."""

    source_key: str
    bills: tuple[CanonicalOpeningBill, ...]


@dataclass(frozen=True)
class CanonicalLine:
    ledger_name: str
    amount: Decimal
    # The foreign currency amount of a line in a foreign currency (canonical sign), its
    # currency as the source names it and its rate as written (base per unit; FX-001). None
    # in the base currency.
    amount_fc: Decimal | None = None
    currency_name: str | None = None
    exchange_rate: Decimal | None = None
    foreign_unread: bool = False  # written in a foreign currency, but not readable
    is_party_line: bool = False
    bills: tuple[CanonicalBill, ...] = ()
    cost_allocations: tuple[CanonicalCostAllocation, ...] = ()
    # A bank line's instrument (several on one line joined with "; "): the cheque or
    # instrument number, its kind (Cheque, e-Fund Transfer, ...), dates and reconciliation
    # status; the source's own id for the bank entry (never a UTR); and the UTR, only a value
    # that looks like one (core/utr.py), with where it was found.
    instrument_number: str | None = None
    transaction_type: str | None = None
    instrument_date: date | None = None
    bank_cleared_date: date | None = None
    bank_recon_status: str | None = None
    tally_bank_entry_id: str | None = None
    utr: str | None = None
    utr_source: str | None = None  # bank_field, udf or narration
    has_bank_details: bool = False
    gst_rates: tuple[CanonicalGstRate, ...] = ()


@dataclass(frozen=True)
class CanonicalInventoryLine:
    item_name: str
    quantity: Decimal  # signed: in +, out -
    amount: Decimal  # canonical sign, follows quantity
    unit_name: str | None = None
    rate: Decimal | None = None
    godown_name: str | None = None
    batch_name: str | None = None
    # The other godown of a move between godowns: where an outgoing line's stock goes,
    # where an incoming line's came from (a transfer, or a job worker's godown).
    counterpart_godown_name: str | None = None
    # The sales or purchase order the line belongs to (on the order) or is against (on an
    # invoice, delivery or receipt note), and when the order is due.
    order_number: str | None = None
    order_due_date: date | None = None
    gst_rates: tuple[CanonicalGstRate, ...] = ()
    discount_pct: Decimal | None = None
    # The part of the quantity tied to another voucher that moves the stock (Tally: a
    # tracking number to a delivery or receipt note), signed like quantity. On vouchers
    # that post to the books it doesn't move stock (core.transform: stock_quantity).
    tracked_quantity: Decimal = Decimal(0)


@dataclass(frozen=True)
class CanonicalOrderRef:
    """An order a voucher (an invoice, a delivery or receipt note) is made against."""

    number: str
    order_date: date | None = None


@dataclass(frozen=True)
class CanonicalVoucher:
    source_key: str
    voucher_type_name: str
    voucher_number: str
    voucher_date: date
    lines: tuple[CanonicalLine, ...]
    inventory: tuple[CanonicalInventoryLine, ...] = ()
    orders: tuple[CanonicalOrderRef, ...] = ()
    reference_number: str | None = None
    reference_date: date | None = None
    source_altered_at: datetime | None = None
    # The source's effective date when it keeps one (Tally's EFFECTIVEDATE). Balances still
    # count by voucher_date: Tally does (checked on the test company, 2026-10-15).
    effective_date: date | None = None
    party_ledger_name: str | None = None
    narration: str | None = None
    currency_code: str = "INR"
    is_cancelled: bool = False
    is_optional: bool = False
    is_post_dated: bool = False
    # GST: the company's registration (tax unit) the voucher is under, the place of supply,
    # the e-invoice (IRN, its acknowledgement number and date) and the e-way bill.
    gst_registration: str | None = None
    place_of_supply: str | None = None
    irn: str | None = None
    irn_ack_number: str | None = None
    irn_date: date | None = None
    eway_bill_number: str | None = None
    eway_bill_date: date | None = None
    # The numbering series it is numbered in, the last day a reversing journal applies, and
    # whether it affects cash flow (Tally HASCASHFLOW).
    number_series: str | None = None
    active_to: date | None = None
    has_cash_flow: bool | None = None
    extra: Mapping[str, Any] | None = _extra()


CanonicalRecord = (
    CanonicalCompany
    | CanonicalCurrency
    | CanonicalGroup
    | CanonicalLedger
    | CanonicalVoucherType
    | CanonicalUnit
    | CanonicalItemGroup
    | CanonicalItem
    | CanonicalGodown
    | CanonicalCostCategory
    | CanonicalCostCentre
    | CanonicalOpeningBills
    | CanonicalTaxUnit
    | CanonicalStockCategory
    | CanonicalBudget
    | CanonicalVoucher
)
