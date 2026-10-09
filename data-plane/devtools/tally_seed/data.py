"""The seed data set. Synthetic: no real parties or figures.

Amounts are positive here; Dr/Cr is explicit. The XML builder turns them into Tally's
signed form. Voucher dates use only the 1st, 2nd or 31st of a month (TallyPrime
Educational mode).
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal

Side = Literal["Dr", "Cr"]
EDUCATIONAL_DAYS = (1, 2, 31)
FY_START = date(2026, 4, 1)
FY_END = date(2027, 3, 31)


@dataclass(frozen=True)
class Ledger:
    name: str
    parent: str
    opening: Decimal = Decimal(0)
    opening_side: Side = "Dr"
    bill_wise: bool = False
    gst_duty_head: str | None = None  # "Central Tax" / "State Tax" for GST ledgers
    predefined: bool = False  # exists in every Tally company (e.g. Cash); only altered


@dataclass(frozen=True)
class Bill:
    name: str
    bill_type: Literal["New Ref", "Agst Ref"]
    amount: Decimal


@dataclass(frozen=True)
class Entry:
    ledger: str
    side: Side
    amount: Decimal
    bills: tuple[Bill, ...] = ()
    cost_centres: tuple[tuple[str, Decimal], ...] = ()


@dataclass(frozen=True)
class ItemLine:
    item: str
    quantity: Decimal
    rate: Decimal
    sales_ledger: str

    @property
    def amount(self) -> Decimal:
        return self.quantity * self.rate


@dataclass(frozen=True)
class Voucher:
    marker: str  # stored in the narration as [lb-seed:<marker>]; makes seeding idempotent
    voucher_type: str
    on: date
    narration: str
    entries: tuple[Entry, ...]
    items: tuple[ItemLine, ...] = ()
    cancel: bool = False
    alter_to: tuple[Entry, ...] | None = None  # entries after the post-creation alteration
    needs_cost_centres: bool = False

    @property
    def tagged_narration(self) -> str:
        return f"{self.narration} [lb-seed:{self.marker}]"

    def final_entries(self) -> tuple[Entry, ...]:
        return self.alter_to if self.alter_to is not None else self.entries


@dataclass(frozen=True)
class SeedData:
    ledgers: tuple[Ledger, ...]
    units: tuple[str, ...]
    stock_items: tuple[tuple[str, str], ...]  # (name, unit)
    cost_centres: tuple[str, ...]
    vouchers: tuple[Voucher, ...] = field(default=())


def _d(value: str) -> Decimal:
    return Decimal(value)


def _bill(name: str, amount: str, kind: Literal["New Ref", "Agst Ref"] = "New Ref") -> Bill:
    return Bill(name, kind, _d(amount))


CUSTOMERS = ("Customer Alpha Traders", "Customer Beta Retail", "Customer Gamma Stores")
VENDORS = ("Vendor Delta Supplies", "Vendor Epsilon Wholesale", "Vendor Zeta Services")
BANK = "Test Bank Current A/c"

LEDGERS: tuple[Ledger, ...] = (
    # Anchors
    Ledger("Rent", "Indirect Expenses"),
    Ledger("Capital", "Capital Account", _d("50000"), "Cr"),
    Ledger("Cash", "Cash-in-Hand", _d("50000"), "Dr", predefined=True),
    # Realistic set
    Ledger(BANK, "Bank Accounts"),
    Ledger("Sales - Goods", "Sales Accounts"),
    Ledger("Sales - Services", "Sales Accounts"),
    Ledger("Purchases", "Purchase Accounts"),
    Ledger("Electricity", "Indirect Expenses"),
    Ledger("Salary", "Indirect Expenses"),
    Ledger("Salary Payable", "Current Liabilities"),
    Ledger("Output CGST", "Duties & Taxes", gst_duty_head="Central Tax"),
    Ledger("Output SGST", "Duties & Taxes", gst_duty_head="State Tax"),
    Ledger("Input CGST", "Duties & Taxes", gst_duty_head="Central Tax"),
    Ledger("Input SGST", "Duties & Taxes", gst_duty_head="State Tax"),
    *(Ledger(name, "Sundry Debtors", bill_wise=True) for name in CUSTOMERS),
    *(Ledger(name, "Sundry Creditors", bill_wise=True) for name in VENDORS),
)


def _sale(marker: str, on: date, party: str, bill: str, net: str, tax: str) -> Voucher:
    total = _d(net) + 2 * _d(tax)
    return Voucher(
        marker,
        "Sales",
        on,
        f"GST sale {bill}",
        (
            Entry(party, "Dr", total, (Bill(bill, "New Ref", total),)),
            Entry("Sales - Services", "Cr", _d(net)),
            Entry("Output CGST", "Cr", _d(tax)),
            Entry("Output SGST", "Cr", _d(tax)),
        ),
    )


def _purchase(marker: str, on: date, party: str, bill: str, net: str, tax: str) -> Voucher:
    total = _d(net) + 2 * _d(tax)
    return Voucher(
        marker,
        "Purchase",
        on,
        f"GST purchase {bill}",
        (
            Entry("Purchases", "Dr", _d(net)),
            Entry("Input CGST", "Dr", _d(tax)),
            Entry("Input SGST", "Dr", _d(tax)),
            Entry(party, "Cr", total, (Bill(bill, "New Ref", total),)),
        ),
    )


VOUCHERS: tuple[Voucher, ...] = (
    Voucher(
        "PMT-ANCHOR",
        "Payment",
        date(2026, 4, 1),
        "Office rent April",
        (Entry("Rent", "Dr", _d("1000")), Entry("Cash", "Cr", _d("1000"))),
    ),
    Voucher(
        "SAL-ITEM",
        "Sales",
        date(2026, 4, 2),
        "Item invoice SI-1",
        (
            Entry(CUSTOMERS[0], "Dr", _d("2360"), (_bill("SI-1", "2360"),)),
            Entry("Output CGST", "Cr", _d("180")),
            Entry("Output SGST", "Cr", _d("180")),
        ),
        items=(ItemLine("Widget", _d("10"), _d("200"), "Sales - Goods"),),
    ),
    _purchase("PUR-GST-1", date(2026, 4, 2), VENDORS[0], "PI-1", "8000", "720"),
    _sale("SAL-GST-1", date(2026, 5, 1), CUSTOMERS[1], "SI-2", "10000", "900"),
    Voucher(
        "CTR-1",
        "Contra",
        date(2026, 5, 2),
        "Cash deposited in bank",
        (Entry(BANK, "Dr", _d("20000")), Entry("Cash", "Cr", _d("20000"))),
    ),
    _sale("SAL-GST-2", date(2026, 5, 31), CUSTOMERS[2], "SI-3", "5000", "450"),
    _sale("SAL-GST-3", date(2026, 6, 1), CUSTOMERS[0], "SI-4", "3000", "270"),
    _purchase("PUR-GST-2", date(2026, 6, 2), VENDORS[1], "PI-2", "4000", "360"),
    Voucher(
        "RCT-1",
        "Receipt",
        date(2026, 6, 2),
        "Received against SI-2 in full",
        (
            Entry(BANK, "Dr", _d("11800")),
            Entry(CUSTOMERS[1], "Cr", _d("11800"), (_bill("SI-2", "11800", "Agst Ref"),)),
        ),
    ),
    Voucher(
        "RCT-2",
        "Receipt",
        date(2026, 7, 1),
        "Part payment against SI-1",
        (
            Entry("Cash", "Dr", _d("2000")),
            Entry(CUSTOMERS[0], "Cr", _d("2000"), (_bill("SI-1", "2000", "Agst Ref"),)),
        ),
    ),
    Voucher(
        "PMT-2",
        "Payment",
        date(2026, 7, 2),
        "Paid PI-1 in full",
        (
            Entry(VENDORS[0], "Dr", _d("9440"), (_bill("PI-1", "9440", "Agst Ref"),)),
            Entry(BANK, "Cr", _d("9440")),
        ),
    ),
    Voucher(
        "PMT-3",
        "Payment",
        date(2026, 7, 31),
        "Part payment against PI-2",
        (
            Entry(VENDORS[1], "Dr", _d("2000"), (_bill("PI-2", "2000", "Agst Ref"),)),
            Entry("Cash", "Cr", _d("2000")),
        ),
    ),
    Voucher(
        "CC-1",
        "Payment",
        date(2026, 8, 1),
        "Electricity split by cost centre",
        (
            Entry(
                "Electricity",
                "Dr",
                _d("3000"),
                cost_centres=(("Head Office", _d("2000")), ("Branch", _d("1000"))),
            ),
            Entry(BANK, "Cr", _d("3000")),
        ),
        needs_cost_centres=True,
    ),
    Voucher(
        "CANCEL-1",
        "Payment",
        date(2026, 8, 2),
        "Duplicate rent entry, cancelled",
        (Entry("Rent", "Dr", _d("500")), Entry("Cash", "Cr", _d("500"))),
        cancel=True,
    ),
    Voucher(
        "JNL-1",
        "Journal",
        date(2026, 8, 31),
        "Salary accrual August",
        (Entry("Salary", "Dr", _d("15000")), Entry("Salary Payable", "Cr", _d("15000"))),
    ),
    _purchase("PUR-GST-3", date(2026, 8, 31), VENDORS[2], "PI-3", "1000", "90"),
    Voucher(
        "ALTER-1",
        "Payment",
        date(2026, 9, 1),
        "Electricity bill September",
        (Entry("Electricity", "Dr", _d("1200")), Entry("Cash", "Cr", _d("1200"))),
        alter_to=(Entry("Electricity", "Dr", _d("1500")), Entry("Cash", "Cr", _d("1500"))),
    ),
)

SEED = SeedData(
    ledgers=LEDGERS,
    units=("Nos",),
    stock_items=(("Widget", "Nos"),),
    cost_centres=("Head Office", "Branch"),
    vouchers=VOUCHERS,
)


def validate(seed: SeedData) -> list[str]:
    """Problems with the data set itself; empty when it is safe to import."""
    problems: list[str] = []
    known = {ledger.name for ledger in seed.ledgers}
    for v in seed.vouchers:
        if v.on.day not in EDUCATIONAL_DAYS:
            problems.append(f"{v.marker}: day {v.on.day} not allowed in Educational mode")
        if not FY_START <= v.on <= FY_END:
            problems.append(f"{v.marker}: date outside FY 2026-27")
        for entries in (v.entries, *((v.alter_to,) if v.alter_to else ())):
            dr = sum((e.amount for e in entries if e.side == "Dr"), Decimal(0))
            cr = sum((e.amount for e in entries if e.side == "Cr"), Decimal(0))
            cr += sum((i.amount for i in v.items), Decimal(0))
            if dr != cr:
                problems.append(f"{v.marker}: debits {dr} != credits {cr}")
            for e in entries:
                if e.ledger not in known:
                    problems.append(f"{v.marker}: unknown ledger {e.ledger}")
                if e.bills and sum(b.amount for b in e.bills) != e.amount:
                    problems.append(f"{v.marker}: bill allocations do not match {e.ledger}")
                if e.cost_centres and sum(a for _, a in e.cost_centres) != e.amount:
                    problems.append(f"{v.marker}: cost centres do not match {e.ledger}")
        for item in v.items:
            if item.sales_ledger not in known:
                problems.append(f"{v.marker}: unknown ledger {item.sales_ledger}")
    markers = [v.marker for v in seed.vouchers]
    if len(set(markers)) != len(markers):
        problems.append("duplicate voucher markers")
    return problems


def expected_balances(seed: SeedData) -> dict[str, tuple[Decimal, Side]]:
    """Closing balance per ledger after seeding: openings plus all non-cancelled vouchers,
    using altered amounts. Returned as (amount, side) the way Tally's Trial Balance shows it."""
    net: dict[str, Decimal] = {}  # debit positive
    for ledger in seed.ledgers:
        sign = 1 if ledger.opening_side == "Dr" else -1
        net[ledger.name] = sign * ledger.opening
    for v in seed.vouchers:
        if v.cancel:
            continue
        for e in v.final_entries():
            net[e.ledger] = net.get(e.ledger, Decimal(0)) + (
                e.amount if e.side == "Dr" else -e.amount
            )
        for item in v.items:
            net[item.sales_ledger] = net.get(item.sales_ledger, Decimal(0)) - item.amount
    return {name: (abs(value), "Dr" if value >= 0 else "Cr") for name, value in net.items()}
