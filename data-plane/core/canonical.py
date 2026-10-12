"""Source-independent canonical records (architecture.md 4.4, DAT-003).

A connector's `to_canonical()` turns one raw record into one of these. The transform
(core/transform.py) writes them to ledgerbridge_accounting. Nothing here knows any source.

Conventions: amounts use the canonical sign (debit positive, credit negative, schema.md
Section 1). Other objects are referred to by name within the same entity, because sources
such as Tally refer to masters by name rather than by key.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

# A group's standard_account_code meaning "no standard account here": stops sub-groups and
# ledgers inheriting a mapping from further up the tree.
NO_STANDARD_ACCOUNT = "-"


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


@dataclass(frozen=True)
class CanonicalGroup:
    source_key: str
    name: str
    parent_name: str | None
    nature: str | None = None  # asset/liability/equity/income/expense
    is_primary: bool = False
    affects_gross_profit: bool = False
    # Hints inherited by sub-groups and ledgers (the transform walks the group tree):
    standard_account_code: str | None = None
    ledger_kind: str | None = None  # bank/cash/tax/party/stock
    party_type: str | None = None  # customer/vendor


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


@dataclass(frozen=True)
class CanonicalLedger:
    source_key: str
    name: str
    group_name: str
    opening_balance: Decimal = Decimal(0)
    opening_balance_date: date | None = None
    currency_code: str = "INR"
    is_bill_wise: bool = False
    is_cost_centre_applicable: bool = False
    gstin: str | None = None
    tax_type: str | None = None  # cgst/sgst/igst/cess/tds/tcs/vat/other for tax ledgers
    party: CanonicalParty | None = None  # details, used if the group makes it a party


@dataclass(frozen=True)
class CanonicalVoucherType:
    source_key: str
    name: str
    base_type: str
    is_accounting: bool = True
    is_inventory: bool = False


@dataclass(frozen=True)
class CanonicalUnit:
    source_key: str
    symbol: str
    name: str
    decimal_places: int = 0


@dataclass(frozen=True)
class CanonicalItemGroup:
    source_key: str
    name: str
    parent_name: str | None


@dataclass(frozen=True)
class CanonicalItem:
    source_key: str
    name: str
    group_name: str | None
    unit_name: str | None
    opening_qty: Decimal = Decimal(0)
    opening_value: Decimal = Decimal(0)


@dataclass(frozen=True)
class CanonicalGodown:
    source_key: str
    name: str
    parent_name: str | None


@dataclass(frozen=True)
class CanonicalCostCentre:
    source_key: str
    name: str
    parent_name: str | None
    category: str | None = None


@dataclass(frozen=True)
class CanonicalBill:
    bill_type: str  # new_ref/against_ref/advance/on_account
    name: str | None
    amount: Decimal
    bill_date: date | None = None


@dataclass(frozen=True)
class CanonicalLine:
    ledger_name: str
    amount: Decimal
    is_party_line: bool = False
    bills: tuple[CanonicalBill, ...] = ()
    cost_allocations: tuple[tuple[str, Decimal], ...] = ()  # (cost centre name, amount)


@dataclass(frozen=True)
class CanonicalInventoryLine:
    item_name: str
    quantity: Decimal  # signed: in +, out -
    amount: Decimal  # canonical sign, follows quantity
    unit_name: str | None = None
    rate: Decimal | None = None
    godown_name: str | None = None
    batch_name: str | None = None
    discount_pct: Decimal | None = None


@dataclass(frozen=True)
class CanonicalVoucher:
    source_key: str
    voucher_type_name: str
    voucher_number: str
    voucher_date: date
    lines: tuple[CanonicalLine, ...]
    inventory: tuple[CanonicalInventoryLine, ...] = ()
    reference_number: str | None = None
    reference_date: date | None = None
    party_ledger_name: str | None = None
    narration: str | None = None
    currency_code: str = "INR"
    is_cancelled: bool = False
    is_optional: bool = False
    is_post_dated: bool = False


CanonicalRecord = (
    CanonicalCompany
    | CanonicalGroup
    | CanonicalLedger
    | CanonicalVoucherType
    | CanonicalUnit
    | CanonicalItemGroup
    | CanonicalItem
    | CanonicalGodown
    | CanonicalCostCentre
    | CanonicalVoucher
)
