"""The seed data set. Synthetic: no real parties or figures.

Amounts are positive here; Dr/Cr is explicit. The XML builder turns them into Tally's
signed form. Voucher dates use only the 1st, 2nd or 31st of a month (TallyPrime
Educational mode). The test company's books begin on 1 April 2025 (changed in TallyPrime by
the developer, 2026-10-24, so it has a year end): vouchers fall in FY 2025-26 or 2026-27.

Besides everyday vouchers, the set reproduces Tally's counting rules (checked against
Tally's own balances, 2026-10-14; schema.md 7.4):
- openings: ledgers and a stock item with non-zero opening balances;
- stock moved once: delivery and receipt notes and a rejection, and the sales, purchase
  and credit note lines tracked to them (before and after the note): the note moves the
  stock, the tracked invoice line doesn't;
- what counts in the books: an optional voucher, a memorandum, a reversing journal (none
  count), a voucher of a custom type under Journal and a post-dated voucher (both count);
- job work (2026-10-15): material sent to a job worker's godown ("our stock with third
  party": Tally leaves it out of every stock balance), finished goods received back, a
  partial return, consumption at the job worker (moves nothing in Tally's totals), and a
  principal's material received and partly returned ("third-party stock with us":
  counted); partly tracked invoice lines and a purchase return tracked to a rejection;
- openings that total zero in Tally: the opening stock is balanced by a capital ledger;
- a stock ledger (2026-10-15): Tally's reserved Stock-in-Hand group renamed, with one
  ledger whose opening (1,500) differs from the items' opening stock (2,010). With
  accounts integrated with inventory, Tally's trial balance, balance sheet and profit use
  the items' values and leave the ledger out; the ledger itself keeps its own opening.
  Tally refuses vouchers posting to it ("Ledger under Stock-in-Hand");
- names (2026-10-16): a ledger with an alias, and a journal naming it by the alias (Tally
  stores it naming the ledger). "Party Lima" was imported again as "Party Lima ", "PARTY
  LIMA" and "Party  Lima": Tally took each for the existing ledger (its name list keeps the
  last), and refused a ledger whose alias was another ledger's name;
- effective dates (2026-10-15): journals and sales dated on one side of a month end and
  effective on the other, regular and optional: Tally counts them by their date;
- statement layout (2026-10-23): a Direct Expenses and a Direct Incomes ledger with a
  voucher each (where Tally's Profit and Loss puts them), a vendor kept in US dollars with
  an expense entered in rupees (its unadjusted forex is a gain, the customer's a loss), and
  an opening balance on Profit & Loss A/c balanced by a fixed asset (Tally's Balance Sheet
  then shows the account's Opening Balance and Current Period, as after a year end).
"""

from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from typing import Any, Literal

Side = Literal["Dr", "Cr"]
EDUCATIONAL_DAYS = (1, 2, 31)
FY_START = date(2025, 4, 1)  # the books' beginning (FY 2025-26)
FY_END = date(2027, 3, 31)  # the end of FY 2026-27


@dataclass(frozen=True)
class Ledger:
    name: str
    parent: str
    opening: Decimal = Decimal(0)
    opening_side: Side = "Dr"
    bill_wise: bool = False
    gst_duty_head: str | None = None  # "Central Tax" / "State Tax" for GST ledgers
    predefined: bool = False  # exists in every Tally company (e.g. Cash); only altered
    aliases: tuple[str, ...] = ()  # other names (Tally's alias names)
    currency: str | None = None  # a foreign currency's symbol (else the base currency)
    # The opening is entered by hand in TallyPrime (a foreign-currency opening: Tally's XML
    # import refused foreign amounts, ADR-035): created without one and never altered.
    opening_by_hand: bool = False


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
    sales_ledger: str | None  # the ledger the amount posts to (None: no accounting)
    inward: bool = False  # received (purchase, receipt note, credit note) or sent out
    tracking: str | None = None  # tracking number: ties an invoice line to a note
    godown: str = "Main Location"
    destination: str | None = None  # the job worker's godown of a Material In/Out
    # Batches (quantity, tracking number) when the line is partly tracked; else one batch.
    batches: tuple[tuple[Decimal, str | None], ...] = ()

    def split(self) -> tuple[tuple[Decimal, str | None], ...]:
        return self.batches or ((self.quantity, self.tracking),)

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
    delete: bool = False  # deleted after creation (tests deletion detection)
    number: str | None = None  # voucher number (Tally may renumber automatic types)
    reference: str | None = None
    party: str | None = None  # the party ledger of an item voucher; else the entry with bills
    optional: bool = False
    post_dated: bool = False
    stock_journal: bool = False  # items go to the in (inward) and out lists of a journal
    effective: date | None = None  # Tally's effective date, when not the voucher's date

    @property
    def tombstone(self) -> str:
        """Empty stock group created when the voucher is deleted, so a re-run doesn't create
        the voucher again. (Unit symbols can't be used: Tally rejects digits and "-".)"""
        return f"lb-seed {self.marker} deleted"

    @property
    def tagged_narration(self) -> str:
        return f"{self.narration} [lb-seed:{self.marker}]"

    def final_entries(self) -> tuple[Entry, ...]:
        return self.alter_to if self.alter_to is not None else self.entries


@dataclass(frozen=True)
class StockItem:
    name: str
    unit: str
    opening_qty: Decimal = Decimal(0)
    opening_rate: Decimal = Decimal(0)
    group: str | None = None  # a stock group (else Primary)


@dataclass(frozen=True)
class Godown:
    name: str
    external: bool = False  # "our stock with third party" (a job worker's location)
    internal: bool = False  # "third-party stock with us" (a principal's material)


@dataclass(frozen=True)
class AccountGroup:
    """A group of ledgers, with Tally's two reporting settings (exported as ISADDABLE and
    ISSUBLEDGER, read from the test company's group records, 2026-10-24)."""

    name: str
    parent: str
    addable: bool = False  # ISADDABLE
    sub_ledger: bool = False  # ISSUBLEDGER: "group behaves like a sub-ledger"


@dataclass(frozen=True)
class Currency:
    symbol: str  # Tally's name for it, e.g. "$"
    formal_name: str
    code: str


@dataclass(frozen=True)
class SeedData:
    ledgers: tuple[Ledger, ...]
    units: tuple[str, ...]
    stock_items: tuple[StockItem, ...]
    cost_centres: tuple[str, ...]
    vouchers: tuple[Voucher, ...] = field(default=())
    voucher_types: tuple[tuple[str, str], ...] = field(default=())  # (name, parent)
    renamed_groups: tuple[tuple[str, str], ...] = field(default=())  # (reserved, new name)
    godowns: tuple[Godown, ...] = field(default=())
    stock_groups: tuple[str, ...] = field(default=())
    currencies: tuple[Currency, ...] = field(default=())
    groups: tuple[AccountGroup, ...] = field(default=())


# Voucher types whose vouchers don't post to the books (Tally leaves them out of every
# balance), and those whose inventory lines don't move stock.
NON_POSTING_TYPES = frozenset((
    "Delivery Note", "Receipt Note", "Rejections In", "Rejections Out", "Memorandum",
    "Reversing Journal", "Material In", "Material Out", "Stock Journal",
))  # fmt: skip
NON_STOCK_TYPES = frozenset(("Memorandum", "Sales Order", "Purchase Order"))


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
    # Openings on balance sheet ledgers other than cash and capital (they balance).
    Ledger("Security Deposit", "Deposits (Asset)", _d("12000"), "Dr"),
    Ledger("Term Loan", "Loans (Liability)", _d("12000"), "Cr"),
    # Balances the opening stock (Gadget 1,000, Steel Sheet 1,000, Hinge 10): with it Tally
    # shows no difference in opening balances (without it, a difference of 2,010).
    Ledger("Capital - Stock", "Capital Account", _d("2010"), "Cr"),
    # The one ledger in the renamed Stock-in-Hand group: Tally's books leave it out.
    Ledger("Stock Ledger", "Inventories", _d("1500"), "Dr"),
)
STOCK_IN_HAND = ("Stock-in-Hand", "Inventories")  # Tally's reserved group, renamed
# --- names (2026-10-16): how Tally resolves a name used in a voucher (experiments) ------
NAME_LEDGERS = (
    Ledger("Party Kilo", "Sundry Debtors", aliases=("Kilo Alias",)),
    Ledger("Party Lima", "Sundry Debtors"),
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


def _goods(
    marker: str,
    voucher_type: str,
    on: date,
    narration: str,
    party: str,
    line: ItemLine,
    number: str,
    bill: Bill | None = None,
    reference: str | None = None,
) -> Voucher:
    """A voucher of one inventory line and its party: an invoice (with a bill) or a note."""
    side: Side = "Cr" if line.inward else "Dr"
    entry = Entry(party, side, line.amount, (bill,) if bill else ())
    return Voucher(
        marker, voucher_type, on, narration, (entry,), items=(line,), number=number,
        reference=reference, party=party,
    )  # fmt: skip


def _journal(marker: str, voucher_type: str, on: date, dr: str, cr: str, amount: str,
             **flags: Any) -> Voucher:  # fmt: skip
    return Voucher(
        marker,
        voucher_type,
        on,
        f"{voucher_type} test",
        (Entry(dr, "Dr", _d(amount)), Entry(cr, "Cr", _d(amount))),
        **flags,
    )


GADGET_IN = ItemLine("Gadget", _d("30"), _d("50"), "Purchases", inward=True, tracking="RN-1")
JOB_WORKER = "Job Worker Alpha"  # our stock with a third party
PRINCIPAL = "Principal Stock"  # third-party stock with us


def _material(marker: str, voucher_type: str, on: date, party: str, line: ItemLine) -> Voucher:
    """A job work voucher (Material In / Out): stock only, nothing posted."""
    return Voucher(
        marker, voucher_type, on, f"{voucher_type} {marker}", (), items=(line,), party=party
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
    # Part payment altered to the full amount: the line amounts and the bill allocation change.
    Voucher(
        "ALTER-2",
        "Receipt",
        date(2026, 9, 2),
        "Received against SI-3",
        (
            Entry(BANK, "Dr", _d("3000")),
            Entry(CUSTOMERS[2], "Cr", _d("3000"), (_bill("SI-3", "3000", "Agst Ref"),)),
        ),
        alter_to=(
            Entry(BANK, "Dr", _d("5900")),
            Entry(CUSTOMERS[2], "Cr", _d("5900"), (_bill("SI-3", "5900", "Agst Ref"),)),
        ),
    ),
    Voucher(
        "DEL-1",
        "Payment",
        date(2026, 9, 2),
        "Duplicate salary payment, deleted",
        (Entry("Salary", "Dr", _d("700")), Entry(BANK, "Cr", _d("700"))),
        delete=True,
    ),
    # --- stock moved once: notes and the invoice lines tracked to them -----------------
    # A receipt note, then the purchase invoice tracked to it: only the note moves stock.
    _goods("RN-1", "Receipt Note", date(2026, 9, 1), "Goods received GRN-1", VENDORS[0],
           GADGET_IN, "RN-1"),
    _goods("PUR-RN-1", "Purchase", date(2026, 9, 2), "Invoice for GRN-1", VENDORS[0],
           GADGET_IN, "PUR-RN-1", _bill("PI-4", "1500"), "PI-4"),
    # A delivery note, then the sales invoice tracked to it.
    _goods("DN-1", "Delivery Note", date(2026, 9, 1), "Delivery Note DN-1", CUSTOMERS[0],
           ItemLine("Widget", _d("5"), _d("200"), "Sales - Goods", tracking="DN-1"), "DN-1"),
    _goods("SAL-DN-1", "Sales", date(2026, 9, 2), "Sales SI-5", CUSTOMERS[0],
           ItemLine("Widget", _d("5"), _d("200"), "Sales - Goods", tracking="DN-1"), "SI-5",
           _bill("SI-5", "1000")),
    # The sales invoice first (a new tracking number), the delivery note afterwards.
    _goods("SAL-TRK-2", "Sales", date(2026, 10, 1), "Sales SI-6", CUSTOMERS[0],
           ItemLine("Widget", _d("3"), _d("200"), "Sales - Goods", tracking="DN-2"), "SI-6",
           _bill("SI-6", "600")),
    _goods("DN-2", "Delivery Note", date(2026, 10, 2), "Delivery Note DN-2", CUSTOMERS[0],
           ItemLine("Widget", _d("3"), _d("200"), "Sales - Goods", tracking="DN-2"), "DN-2"),
    # A return: the credit note is tracked to the rejection, which moves the stock. (With
    # the rejection missing, Tally's P&L counted the credit note's value inconsistently.)
    _goods("CN-TRK-1", "Credit Note", date(2026, 10, 2), "Return tracked RI-1", CUSTOMERS[0],
           ItemLine("Widget", _d("2"), _d("200"), "Sales - Goods", inward=True,
                    tracking="RI-1"),
           "CN-1", _bill("SI-6", "400", "Agst Ref")),
    _goods("RI-1", "Rejections In", date(2026, 10, 2), "Goods returned RI-1", CUSTOMERS[0],
           ItemLine("Widget", _d("2"), _d("200"), "Sales - Goods", inward=True,
                    tracking="RI-1"),
           "RI-1"),
    # --- what counts in the books ------------------------------------------------------
    _journal("OPT-JNL-1", "Journal", date(2026, 10, 1), "Salary", "Salary Payable", "400",
             optional=True),
    _journal("MEMO-1", "Memorandum", date(2026, 10, 1), "Electricity", "Cash", "250"),
    _journal("REV-JNL-1", "Reversing Journal", date(2026, 10, 1), "Rent", "Salary Payable",
             "125"),
    # With reversing journals enabled in the company: still in no balance, not even on its
    # own date (checked on 1 and 2 September, 2026-10-15).
    _journal("REV-JNL-2", "Reversing Journal", date(2026, 9, 1), "Rent", "Salary Payable",
             "135"),
    _journal("ADJ-JNL-1", "Adjustment Journal", date(2026, 10, 2), "Rent", "Salary Payable",
             "300"),
    _journal("PDC-1", "Payment", date(2027, 1, 1), "Rent", "Cash", "75", post_dated=True),
    # --- job work: we send steel to a job worker, who makes brackets -------------------
    # Steel goes to the job worker's godown: out of Tally's stock balances (100 -> 20).
    _material("MAT-OUT-1", "Material Out", date(2026, 8, 2), VENDORS[2],
              ItemLine("Steel Sheet", _d("80"), _d("10"), None, destination=JOB_WORKER)),
    # Finished brackets received back.
    _material("MAT-IN-1", "Material In", date(2026, 8, 31), VENDORS[2],
              ItemLine("Bracket", _d("30"), _d("30"), None, inward=True)),
    # Steel consumed at the job worker: moves nothing in Tally's totals.
    Voucher("JW-CONSUME-1", "Stock Journal", date(2026, 8, 31), "Steel consumed at job worker",
            (), items=(ItemLine("Steel Sheet", _d("60"), _d("10"), None, godown=JOB_WORKER),),
            stock_journal=True),
    # A stock journal with both sides at our own godown: 2 Hinge consumed, 1 Bracket made.
    # Tally lists both in ALLINVENTORYENTRIES and again in its in and out lists.
    Voucher("SJ-MFG-1", "Stock Journal", date(2026, 9, 2), "Stock Journal test", (),
            items=(ItemLine("Bracket", _d("1"), _d("4"), None, inward=True),
                   ItemLine("Hinge", _d("2"), _d("2"), None)),
            stock_journal=True),
    # Unused steel returned (20 -> 30).
    _material("MAT-IN-2", "Material In", date(2026, 9, 1), VENDORS[2],
              ItemLine("Steel Sheet", _d("10"), _d("10"), None, inward=True,
                       destination=JOB_WORKER)),
    # --- job work for a principal: their fabric is counted in Tally's stock ------------
    _material("JWIN-IN-1", "Material In", date(2026, 9, 1), CUSTOMERS[1],
              ItemLine("Client Fabric", _d("50"), _d("4"), None, inward=True, godown=PRINCIPAL)),
    _material("JWIN-OUT-1", "Material Out", date(2026, 9, 2), CUSTOMERS[1],
              ItemLine("Client Fabric", _d("20"), _d("4"), None, godown=PRINCIPAL)),
    # --- partly tracked invoices and a purchase return tracked to a rejection -----------
    _goods("RN-3", "Receipt Note", date(2026, 9, 1), "Receipt Note test", VENDORS[1],
           ItemLine("Gadget", _d("30"), _d("50"), "Purchases", inward=True, tracking="RN-3"),
           "RN-3"),
    # 30 tracked to RN-3 (moved by the note), 10 untracked (moved by the invoice).
    _goods("PUR-PART-1", "Purchase", date(2026, 9, 2), "Purchase test", VENDORS[1],
           ItemLine("Gadget", _d("40"), _d("50"), "Purchases", inward=True,
                    batches=((_d("30"), "RN-3"), (_d("10"), None))),
           "PUR-PART-1", _bill("PI-5", "2000")),
    _goods("DN-3", "Delivery Note", date(2026, 9, 1), "Delivery Note test", CUSTOMERS[2],
           ItemLine("Widget", _d("4"), _d("200"), "Sales - Goods", tracking="DN-3"), "DN-3"),
    _goods("SAL-PART-1", "Sales", date(2026, 9, 2), "Sales test", CUSTOMERS[2],
           ItemLine("Widget", _d("6"), _d("200"), "Sales - Goods",
                    batches=((_d("4"), "DN-3"), (_d("2"), None))),
           "SAL-PART-1", _bill("SI-7", "1200")),
    _goods("RO-1", "Rejections Out", date(2026, 10, 1), "Rejections Out test", VENDORS[1],
           ItemLine("Gadget", _d("5"), _d("50"), "Purchases", tracking="RO-1"), "RO-1"),
    # --- effective dates (2026-10-15): vouchers dated on one side of a month end and
    # effective on the other, regular and optional, journals and sales.
    _journal("EFF-JNL-1", "Journal", date(2026, 8, 31), "Rent", "Salary Payable", "11",
             effective=date(2026, 9, 1)),
    _journal("EFF-JNL-2", "Journal", date(2026, 9, 1), "Rent", "Salary Payable", "13",
             effective=date(2026, 8, 31)),
    _journal("EFF-OPT-1", "Journal", date(2026, 8, 31), "Rent", "Salary Payable", "17",
             optional=True, effective=date(2026, 9, 1)),
    replace(_sale("EFF-SAL-1", date(2026, 8, 31), CUSTOMERS[1], "SI-EFF-1", "100", "9"),
            effective=date(2026, 9, 1)),
    replace(_sale("EFF-SAL-2", date(2026, 9, 1), CUSTOMERS[1], "SI-EFF-2", "200", "18"),
            optional=True, effective=date(2026, 8, 31)),
    _goods("DBN-TRK-1", "Debit Note", date(2026, 10, 2), "Debit Note test", VENDORS[1],
           ItemLine("Gadget", _d("5"), _d("50"), "Purchases", tracking="RO-1"), "DBN-TRK-1",
           _bill("PI-5", "250", "Agst Ref")),
)  # fmt: skip

# --- foreign currency (2026-10-16): a US dollar currency and a customer kept in it, with a
# sale entered in rupees. Tally's XML import refused foreign amounts written as its exports
# show them ("-$50.00 @ Rs84.00/$ = ..."), and rates of exchange can't be written without
# knowing their fields (none exported yet): see ADR-035.
USD = Currency("$", "US Dollar", "USD")
FX_CUSTOMER = "Customer Delta USD"
FX_LEDGERS = (Ledger(FX_CUSTOMER, "Sundry Debtors", currency="$"),)
FX_VOUCHERS = (
    Voucher(
        "FX-SAL-1", "Sales", date(2026, 8, 1), "Export sale USD 100 at 82",
        (Entry(FX_CUSTOMER, "Dr", _d("8200")), Entry("Sales - Services", "Cr", _d("8200"))),
    ),
)  # fmt: skip

# --- statement layout (2026-10-23): the lines Tally's own statements show for direct
# expenses and incomes, foreign-currency gains and losses, and an accumulated profit.
FX_VENDOR = "Vendor Echo USD"
LAYOUT_LEDGERS = (
    Ledger("Freight Inward", "Direct Expenses"),
    Ledger("Job Work Charges", "Direct Incomes"),
    Ledger(FX_VENDOR, "Sundry Creditors", currency="$"),
    Ledger("Consulting Fees", "Indirect Expenses"),
    Ledger("Profit & Loss A/c", "Primary", _d("3000"), "Cr", predefined=True),
    Ledger("Furniture", "Fixed Assets", _d("3000"), "Dr"),
)
LAYOUT_VOUCHERS = (
    _journal("STMT-DEXP-1", "Payment", date(2026, 9, 1), "Freight Inward", "Cash", "300"),
    _journal("STMT-DINC-1", "Receipt", date(2026, 9, 1), "Cash", "Job Work Charges", "120"),
    _journal("STMT-FXV-1", "Journal", date(2026, 9, 1), "Consulting Fees", FX_VENDOR, "4100"),
)

# --- Trial Balance netting (2026-10-24): how Tally splits a line into debit and credit when
# a group holds ledgers on both sides. Sundry Creditors behaves like a sub-ledger in every
# Tally company (ISSUBLEDGER Yes): a vendor with an advance is a debit inside it. Three
# custom groups, one per setting, each with a debit and a credit ledger.
NETTING_GROUPS = (
    AccountGroup("Advances Addable", "Current Assets", addable=True),
    AccountGroup("Advances Sub-ledger", "Current Assets", sub_ledger=True),
    AccountGroup("Advances Plain", "Current Assets"),
)
NETTING_LEDGERS = (
    Ledger("Addable Dr", "Advances Addable"),
    Ledger("Addable Cr", "Advances Addable"),
    Ledger("Sub-ledger Dr", "Advances Sub-ledger"),
    Ledger("Sub-ledger Cr", "Advances Sub-ledger"),
    Ledger("Plain Dr", "Advances Plain"),
    Ledger("Plain Cr", "Advances Plain"),
    Ledger("Vendor Foxtrot Advance", "Sundry Creditors"),
)
NETTING_VOUCHERS = (
    _journal("NET-ADD-DR", "Payment", date(2026, 9, 2), "Addable Dr", "Cash", "400"),
    _journal("NET-ADD-CR", "Receipt", date(2026, 9, 2), "Cash", "Addable Cr", "150"),
    _journal("NET-SUB-DR", "Payment", date(2026, 9, 2), "Sub-ledger Dr", "Cash", "200"),
    _journal("NET-SUB-CR", "Receipt", date(2026, 9, 2), "Cash", "Sub-ledger Cr", "90"),
    _journal("NET-PLN-DR", "Payment", date(2026, 9, 2), "Plain Dr", "Cash", "300"),
    _journal("NET-PLN-CR", "Receipt", date(2026, 9, 2), "Cash", "Plain Cr", "120"),
    _journal("NET-VND-DR", "Payment", date(2026, 9, 2), "Vendor Foxtrot Advance", "Cash", "700"),
)

# --- a year end (2026-10-24): the books begin on 1 April 2025, so 31 March 2026 is a year end
# before the as-of date. An item of its own bought at rising rates and sold in both years
# (its value at a date depends on the period valued), with ledgers of its own so the other
# figures stay as they were; and a customer kept in US dollars whose opening balance the
# developer entered in TallyPrime ($1,000 at Rs 80; Tally's XML import refused foreign
# amounts, ADR-035), balanced by a capital ledger.
YE_VENDOR = "Vendor Golf Year End"
YE_CUSTOMER = "Customer India Year End"
YE_PURCHASES = "Purchases - Year End"
YE_SALES = "Sales - Year End"
FX_OPENING_CUSTOMER = "Customer Hotel USD"
YEAR_END_LEDGERS = (
    Ledger(YE_VENDOR, "Sundry Creditors", bill_wise=True),
    Ledger(YE_CUSTOMER, "Sundry Debtors", bill_wise=True),
    Ledger(YE_PURCHASES, "Purchase Accounts"),
    Ledger(YE_SALES, "Sales Accounts"),
    # Entered by hand: Tally kept the ledger in the base currency with its opening in dollars
    # ("-$1000.00 @ ? 80/$ = -? 80000.00"); no rates of exchange were stored.
    Ledger(FX_OPENING_CUSTOMER, "Sundry Debtors", _d("80000"), opening_by_hand=True),
    Ledger("Capital - Hotel", "Capital Account", _d("80000"), "Cr"),
)


def _bolts(marker: str, on: date, quantity: str, rate: str, bought: bool) -> Voucher:
    """A purchase (bought) or sale of Bolts on credit, with its bill."""
    line = ItemLine(
        "Bolt", _d(quantity), _d(rate), YE_PURCHASES if bought else YE_SALES, inward=bought
    )
    party = YE_VENDOR if bought else YE_CUSTOMER
    kind = "Purchase" if bought else "Sales"
    amount = str(line.amount)
    return _goods(marker, kind, on, f"{kind} of Bolts {marker}", party, line, marker,
                  _bill(marker, amount))  # fmt: skip


YEAR_END_VOUCHERS = (
    _bolts("YE-PUR-1", date(2025, 6, 2), "100", "10", bought=True),
    _bolts("YE-PUR-2", date(2025, 9, 2), "100", "14", bought=True),
    _bolts("YE-SAL-1", date(2025, 12, 31), "120", "25", bought=False),
    _bolts("YE-PUR-3", date(2026, 3, 2), "50", "18", bought=True),
    _bolts("YE-SAL-2", date(2026, 3, 31), "30", "25", bought=False),
    _bolts("YE-PUR-4", date(2026, 6, 2), "60", "20", bought=True),
    _bolts("YE-SAL-3", date(2026, 8, 31), "80", "30", bought=False),
)

# --- edit log (2026-10-19): a journal altered after creation with TallyPrime Edit Log, so
# Tally keeps its earlier version.
EDIT_LOG_VOUCHERS = (
    Voucher(
        "EDITLOG-ALTER-1", "Journal", date(2026, 9, 2), "Journal altered under the edit log",
        (Entry("Rent", "Dr", _d("31")), Entry("Salary Payable", "Cr", _d("31"))),
        alter_to=(Entry("Rent", "Dr", _d("37")), Entry("Salary Payable", "Cr", _d("37"))),
    ),
)  # fmt: skip

# A voucher naming a ledger by its alias.
NAME_VOUCHERS = (_journal("NAME-ALIAS-1", "Journal", date(2026, 9, 1), "Kilo Alias", "Cash", "21"),)

SEED = SeedData(
    ledgers=(
        *LEDGERS,
        *NAME_LEDGERS,
        *FX_LEDGERS,
        *LAYOUT_LEDGERS,
        *NETTING_LEDGERS,
        *YEAR_END_LEDGERS,
    ),
    groups=NETTING_GROUPS,
    currencies=(USD,),
    units=("Nos",),
    stock_items=(
        StockItem("Widget", "Nos"),
        StockItem("Gadget", "Nos", _d("20"), _d("50")),  # an opening quantity and value
        StockItem("Steel Sheet", "Nos", _d("100"), _d("10")),  # sent for job work
        StockItem("Bracket", "Nos"),  # made by the job worker
        StockItem("Client Fabric", "Nos"),  # a principal's material, with us
        StockItem("Hinge", "Nos", _d("5"), _d("2"), group="Components"),  # in a stock group
        StockItem("Bolt", "Nos"),  # bought and sold across the year end
    ),
    cost_centres=("Head Office", "Branch"),
    vouchers=(
        *VOUCHERS,
        *NAME_VOUCHERS,
        *FX_VOUCHERS,
        *EDIT_LOG_VOUCHERS,
        *LAYOUT_VOUCHERS,
        *NETTING_VOUCHERS,
        *YEAR_END_VOUCHERS,
    ),
    voucher_types=(("Adjustment Journal", "Journal"),),  # a custom type under Journal
    godowns=(Godown(JOB_WORKER, external=True), Godown(PRINCIPAL, internal=True)),
    renamed_groups=(STOCK_IN_HAND,),
    stock_groups=("Components",),
)


def validate(seed: SeedData) -> list[str]:
    """Problems with the data set itself; empty when it is safe to import."""
    problems: list[str] = []
    known = {name for ledger in seed.ledgers for name in (ledger.name, *ledger.aliases)}
    items = {item.name for item in seed.stock_items}
    for v in seed.vouchers:
        for on in (v.on, v.effective or v.on):
            if on.day not in EDUCATIONAL_DAYS:
                problems.append(f"{v.marker}: day {on.day} not allowed in Educational mode")
        if not FY_START <= v.on <= FY_END:
            problems.append(f"{v.marker}: date outside FY 2026-27")
        for entries in (v.entries, *((v.alter_to,) if v.alter_to else ())):
            if not entries:
                break  # stock only (job work, stock journals): nothing to balance
            dr = sum((e.amount for e in entries if e.side == "Dr"), Decimal(0))
            cr = sum((e.amount for e in entries if e.side == "Cr"), Decimal(0))
            dr += sum((i.amount for i in v.items if i.inward), Decimal(0))
            cr += sum((i.amount for i in v.items if not i.inward), Decimal(0))
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
            if item.sales_ledger is not None and item.sales_ledger not in known:
                problems.append(f"{v.marker}: unknown ledger {item.sales_ledger}")
            if item.batches and sum(q for q, _ in item.batches) != item.quantity:
                problems.append(f"{v.marker}: batches don't add up for {item.item}")
            if item.item not in items:
                problems.append(f"{v.marker}: unknown stock item {item.item}")
    markers = [v.marker for v in seed.vouchers]
    if len(set(markers)) != len(markers):
        problems.append("duplicate voucher markers")
    return problems


def _counts(v: Voucher) -> bool:
    """Whether a voucher is in the books (Tally): not cancelled, deleted or optional, and
    of a type that posts. Post-dated vouchers count from their date."""
    return not (v.cancel or v.delete or v.optional) and v.voucher_type not in NON_POSTING_TYPES


def expected_balances(seed: SeedData) -> dict[str, tuple[Decimal, Side]]:
    """Closing balance per ledger at the financial year end after seeding: openings plus
    the vouchers in the books, using altered amounts. Returned as (amount, side) the way
    Tally's Trial Balance shows it."""
    net: dict[str, Decimal] = {}  # debit positive
    names = {alias: ledger.name for ledger in seed.ledgers for alias in ledger.aliases}
    for ledger in seed.ledgers:
        sign = 1 if ledger.opening_side == "Dr" else -1
        net[ledger.name] = sign * ledger.opening
    for v in seed.vouchers:
        if not _counts(v):
            continue
        for e in v.final_entries():
            name = names.get(e.ledger, e.ledger)
            net[name] = net.get(name, Decimal(0)) + (e.amount if e.side == "Dr" else -e.amount)
        for item in v.items:
            if item.sales_ledger is None:
                continue
            signed = item.amount if item.inward else -item.amount
            net[item.sales_ledger] = net.get(item.sales_ledger, Decimal(0)) + signed
    return {name: (abs(value), "Dr" if value >= 0 else "Cr") for name, value in net.items()}


def expected_stock_by_godown(seed: SeedData) -> dict[tuple[str, str], Decimal]:
    """Closing quantity per (stock item, godown) at the financial year end, the way Tally
    keeps it (checked against Tally, 2026-10-14 and -15): the opening, plus lines of
    vouchers that move stock, at the line's godown. A line tracked to a delivery or receipt
    note (or rejection) moves stock only on the note, never on an invoice, debit or credit
    note; a Material In/Out's destination godown moves nothing."""
    quantities = {
        (item.name, "Main Location"): item.opening_qty
        for item in seed.stock_items
        if item.opening_qty
    }
    accounting = {"Sales", "Purchase", "Credit Note", "Debit Note"}
    for v in seed.vouchers:
        if v.cancel or v.delete or v.optional or v.voucher_type in NON_STOCK_TYPES:
            continue
        for line in v.items:
            for quantity, tracking in line.split():
                if tracking and v.voucher_type in accounting:
                    continue  # the note moves it
                key = (line.item, line.godown)
                signed = quantity if line.inward else -quantity
                quantities[key] = quantities.get(key, Decimal(0)) + signed
    return quantities


def expected_stock(seed: SeedData) -> dict[str, Decimal]:
    """Closing quantity per stock item as Tally's balances show it: every godown except a
    job worker's ("our stock with third party", left out of Tally's stock balances)."""
    external = {g.name for g in seed.godowns if g.external}
    quantities = {item.name: Decimal(0) for item in seed.stock_items}
    for (item, godown), quantity in expected_stock_by_godown(seed).items():
        if godown not in external:
            quantities[item] += quantity
    return quantities
