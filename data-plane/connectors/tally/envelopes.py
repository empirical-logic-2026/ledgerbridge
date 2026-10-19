"""Builds the XML requests sent to Tally: what to export, for which company and dates.

Where it fits: `connector.py` picks a collection below (a CollectionSpec: which Tally
objects, which fields) and turns it into a request with `collection_request`, or asks for
one of Tally's own reports with `report_request`; `client.py` sends it and `parser.py`
reads the answer. Only Export requests are ever built: the connector is read-only (CON-008).

Each collection fetches an explicit list of fields: only what the mapping
(connectors/tally/mapping.py) reads, so exports stay small on years of data. Fetching
everything (`NATIVEMETHOD *`) made vouchers about 7x and ledgers about 15x larger.
Tally ignores field names it doesn't know, so fields that differ between TallyPrime and
Tally.ERP 9 releases (e.g. GSTIN, state) are listed in both forms.
"""

from dataclasses import dataclass, replace
from datetime import date, timedelta
from xml.sax.saxutils import escape


@dataclass(frozen=True)
class CollectionSpec:
    collection_id: str  # also the request ID, used to recognise fixture files
    tally_type: str  # Tally object type, e.g. Ledger
    object_tag: str  # element tag of each object in the response
    object_type: str  # our object_type in ledgerbridge_source.raw_records
    fetch: tuple[str, ...]
    # TDL formulas computed by Tally itself, as "NAME : formula"
    compute: tuple[str, ...] = ()


_KEYS = ("GUID", "ALTERID", "MASTERID", "NAME")

COMPANIES = CollectionSpec(
    "LBCompanies",
    "Company",
    "COMPANY",
    "company",
    (
        "NAME", "GUID", "ALTERID", "BOOKSFROM", "STARTINGFROM", "ENDINGAT", "ISCOSTCENTRESON",
        "ISINTEGRATED",
        "BASICCOMPANYFORMALNAME", "STATENAME", "COUNTRYNAME", "GSTREGISTRATIONNUMBER",
        "INCOMETAXNUMBER", "CURRENCYNAME",
    ),
)  # fmt: skip
GROUPS = CollectionSpec(
    "LBGroups",
    "Group",
    "GROUP",
    "group",
    (*_KEYS, "PARENT", "ISREVENUE", "ISDEEMEDPOSITIVE", "AFFECTSGROSSPROFIT"),
)
LEDGERS = CollectionSpec(
    "LBLedgers",
    "Ledger",
    "LEDGER",
    "ledger",
    (
        *_KEYS, "PARENT", "OPENINGBALANCE", "ISBILLWISEON", "ISCOSTCENTRESON", "CURRENCYNAME",
        "TAXTYPE", "GSTDUTYHEAD", "PARTYGSTIN", "LEDGSTREGDETAILS.GSTIN", "INCOMETAXNUMBER",
        "LEDSTATENAME", "LEDMAILINGDETAILS.STATE", "COUNTRYNAME", "EMAIL", "LEDGERPHONE",
        "LEDGERMOBILE", "BILLCREDITPERIOD", "CREDITLIMIT",
    ),
)  # fmt: skip
VOUCHER_TYPES = CollectionSpec(
    "LBVoucherTypes",
    "VoucherType",
    "VOUCHERTYPE",
    "voucher_type",
    (*_KEYS, "PARENT", "AFFECTSSTOCK"),
)
UNITS = CollectionSpec(
    "LBUnits", "Unit", "UNIT", "unit", (*_KEYS, "ORIGINALNAME", "DECIMALPLACES", "ISSIMPLEUNIT")
)
STOCK_GROUPS = CollectionSpec(
    "LBStockGroups", "StockGroup", "STOCKGROUP", "stock_group", (*_KEYS, "PARENT")
)
STOCK_ITEMS = CollectionSpec(
    "LBStockItems",
    "StockItem",
    "STOCKITEM",
    "stock_item",
    (*_KEYS, "PARENT", "BASEUNITS", "OPENINGBALANCE", "OPENINGVALUE", "OPENINGRATE"),
)
# ISEXTERNAL: "our stock with a third party" (a job worker's location; Tally leaves its stock
# out of every stock balance); ISINTERNAL: "third-party stock with us" (counted by Tally).
GODOWNS = CollectionSpec(
    "LBGodowns", "Godown", "GODOWN", "godown", (*_KEYS, "PARENT", "ISEXTERNAL", "ISINTERNAL")
)
COST_CENTRES = CollectionSpec(
    "LBCostCentres", "CostCentre", "COSTCENTRE", "cost_centre", (*_KEYS, "PARENT", "CATEGORY")
)
VOUCHERS = CollectionSpec(
    "LBVouchers",
    "Voucher",
    "VOUCHER",
    "voucher",
    (
        "GUID", "ALTERID", "MASTERID", "DATE", "EFFECTIVEDATE", "VOUCHERTYPENAME",
        "VOUCHERNUMBER", "REFERENCE", "REFERENCEDATE", "PARTYLEDGERNAME", "NARRATION",
        "ISCANCELLED", "ISOPTIONAL", "ISPOSTDATED", "ISDELETED", "ISINVOICE",
        "AllLedgerEntries.LedgerName", "AllLedgerEntries.Amount",
        "AllLedgerEntries.IsDeemedPositive", "AllLedgerEntries.IsPartyLedger",
        "AllLedgerEntries.BillAllocations.Name", "AllLedgerEntries.BillAllocations.BillType",
        "AllLedgerEntries.BillAllocations.Amount",
        "AllLedgerEntries.CategoryAllocations.Category",
        "AllLedgerEntries.CategoryAllocations.CostCentreAllocations.Name",
        "AllLedgerEntries.CategoryAllocations.CostCentreAllocations.Amount",
        "AllInventoryEntries.StockItemName", "AllInventoryEntries.ActualQty",
        "AllInventoryEntries.BilledQty", "AllInventoryEntries.Rate",
        "AllInventoryEntries.Amount", "AllInventoryEntries.IsDeemedPositive",
        "AllInventoryEntries.Discount",
        "AllInventoryEntries.BatchAllocations.GodownName",
        "AllInventoryEntries.BatchAllocations.BatchName",
        # A tracking number ties an invoice line to a delivery or receipt note: the note
        # moves the stock, the invoice line doesn't (mapping._tracked).
        "AllInventoryEntries.BatchAllocations.TrackingNumber",
        "AllInventoryEntries.BatchAllocations.ActualQty",
        "AllInventoryEntries.AccountingAllocations.LedgerName",
        "AllInventoryEntries.AccountingAllocations.Amount",
        "AllInventoryEntries.AccountingAllocations.IsDeemedPositive",
        # Stock journals and manufacturing journals: consumed (out) and produced (in) items.
        *(f"InventoryEntries{side}.{field}" for side in ("In", "Out") for field in (
            "StockItemName", "ActualQty", "BilledQty", "Rate", "Amount", "IsDeemedPositive",
            "BatchAllocations.GodownName", "BatchAllocations.BatchName",
        )),
    ),
)  # fmt: skip

# Whether TallyPrime runs in Educational mode (its license, asked through the company list):
# then balances are reliable on the 1st, 2nd and 31st only (core/dates.py).
LICENSE = CollectionSpec(
    "LBLicense", "Company", "COMPANY", "license", ("NAME",),
    compute=("LBEDUCATIONAL : $$LicenseInfo:IsEducationalMode",),
)  # fmt: skip

# Ledger balances with Tally's own Dr/Cr judgement ($$IsDr), independent of how amounts are
# signed in XML. Used to confirm the sign convention (schema.md Section 7) and, with a
# balances period, for closing-balance validation (M4).
LEDGER_BALANCES = CollectionSpec(
    "LBLedgerBalances",
    "Ledger",
    "LEDGER",
    "ledger_balance",
    ("GUID", "NAME", "PARENT", "OPENINGBALANCE", "CLOSINGBALANCE", "CURRENCYNAME"),
    compute=(
        "LBOPENINGISDR : $$IsDr:$OpeningBalance",
        "LBCLOSINGISDR : $$IsDr:$ClosingBalance",
    ),
)

# Stock values Tally uses for the period's profit (opening and closing stock), and each
# item's closing quantity (validation, VAL-006).
STOCK_VALUES = CollectionSpec(
    "LBStockValues",
    "StockItem",
    "STOCKITEM",
    "stock_value",
    ("GUID", "NAME", "OPENINGVALUE", "CLOSINGVALUE", "CLOSINGBALANCE"),
)

# Groups with Tally's own totals for a period: its primary groups' openings are the trial
# balance's (their sum is Tally's difference in opening balances), and with accounts
# integrated with inventory its Stock-in-Hand group holds the stock value Tally uses
# (checked on the test company, 2026-10-15).
GROUP_BALANCES = CollectionSpec(
    "LBGroupBalances", "Group", "GROUP", "group_balance",
    ("NAME", "PARENT", "OPENINGBALANCE", "CLOSINGBALANCE"),
)  # fmt: skip

# One stock item's stock by godown (and batch), with Tally's own opening and closing
# quantities for the period: `validate analyse` compares stock godown by godown. Requested
# per item (CHILDOF): Tally's Stock Summary leaves out godowns of items in stock groups.
BATCHES = CollectionSpec(
    "LBBatches", "Batch", "BATCH", "batch",
    ("NAME", "GODOWNNAME", "BATCHNAME", "OPENINGBALANCE", "CLOSINGBALANCE"),
)  # fmt: skip

# Vouchers of a month with their type only, to count them (validation, VAL-005). Small,
# like a keys-only listing.
VOUCHER_COUNTS = CollectionSpec(
    "LBVoucherCounts", "Voucher", "VOUCHER", "voucher_count", ("GUID", "DATE", "VOUCHERTYPENAME")
)

# Outstanding bills (bill-wise details) as Tally reports them now: Tally's Bills collection
# ignores the period (checked on the test company, 2026-10-13). PARENT is the party ledger.
BILLS = CollectionSpec(
    "LBBills", "Bills", "BILL", "bill", ("NAME", "PARENT", "BILLDATE", "CLOSINGBALANCE")
)

# Each ledger's opening bills (bill-wise opening balance), from the ledger master.
LEDGER_OPENING_BILLS = CollectionSpec(
    "LBLedgerOpeningBills",
    "Ledger",
    "LEDGER",
    "ledger_opening_bills",
    ("GUID", "NAME", "BILLALLOCATIONS.NAME", "BILLALLOCATIONS.OPENINGBALANCE"),
)

# One ledger's vouchers as Tally lists them (its standard collection type of a ledger's
# vouchers; Child Of the ledger): the vouchers in the books (optional ones left out), with
# the same fields as VOUCHERS. Used by `validate compare-ledger`.
LEDGER_VOUCHERS = replace(
    VOUCHERS, collection_id="LBLedgerVouchers", tally_type="Vouchers : Ledger"
)


# Masters whose OPENINGBALANCE (and OPENINGVALUE) Tally computes for the requested period:
# it is the balance at the period's start, not the master's opening. Without a period Tally
# uses its current period, so a company whose current period starts after the books begin
# reports the balance at that later date (checked on the test company, 2026-10-14). These
# are always fetched for a period starting on the books-beginning date
# (connector._period_for).
OPENING_SPECS = frozenset(("LBLedgers", "LBStockItems", "LBLedgerOpeningBills"))

# Masters in the order they must be transformed (each may refer to the ones before it).
MASTER_SPECS = (
    GROUPS,
    LEDGERS,
    VOUCHER_TYPES,
    UNITS,
    STOCK_GROUPS,
    GODOWNS,
    STOCK_ITEMS,
    COST_CENTRES,
)
ALL_SPECS = (COMPANIES, *MASTER_SPECS, VOUCHERS)
SPEC_BY_OBJECT_TYPE = {spec.object_type: spec for spec in ALL_SPECS}

_PERIOD_FILTER = "LBInPeriod"
_CHANGED_FILTER = "LBChanged"


def tally_date(value: date) -> str:
    return value.strftime("%Y%m%d")


def _dates(start: date, end: date) -> str:
    """Tally's From and To date variables."""
    return (
        f'<SVFROMDATE TYPE="Date">{tally_date(start)}</SVFROMDATE>'
        f'<SVTODATE TYPE="Date">{tally_date(end)}</SVTODATE>'
    )


LEDGER_VOUCHERS_REPORT = "Ledger Vouchers"  # one ledger's vouchers, as Tally shows them
TRIAL_BALANCE = "Trial Balance"  # Tally's own report (an Export of data, read-only)


def report_request(
    report: str, company: str, period: tuple[date, date], ledger: str | None = None
) -> str:
    """An export of one of Tally's own reports for a period (e.g. its Trial Balance), as
    Tally shows it: lines of DSPACCNAME / DSPACCINFO. `ledger` selects the ledger of a
    ledger report. Read-only."""
    ledger_name = f"<LEDGERNAME>{escape(ledger)}</LEDGERNAME>" if ledger is not None else ""
    return (
        "<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST>"
        f"<TYPE>Data</TYPE><ID>{escape(report)}</ID></HEADER><BODY><DESC><STATICVARIABLES>"
        "<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>"
        f"<SVCURRENTCOMPANY>{escape(company)}</SVCURRENTCOMPANY>"
        f"{_dates(*period)}{ledger_name}"
        "</STATICVARIABLES></DESC></BODY></ENVELOPE>"
    )


def ledger_report_request(company: str, ledger: str, period: tuple[date, date]) -> str:
    """Tally's Ledger Vouchers report of one ledger (read-only). Its export lists the
    vouchers of the To date's month only (checked on the test company, 2026-10-16), and a
    calculated "Unadjusted Forex Gain/Loss" line dated on the To date for a foreign-currency
    ledger; only that line is read from it."""
    return report_request(LEDGER_VOUCHERS_REPORT, company, period, ledger=ledger)


def keys_only(spec: CollectionSpec) -> CollectionSpec:
    """The same collection fetching only GUID and AlterID (for spotting deletions), plus the
    date, so a listing for part of a month can be held to its dates (parser.parse_records)."""
    return replace(
        spec, collection_id=f"{spec.collection_id}Keys", fetch=("GUID", "ALTERID", "DATE")
    )


def names_only(spec: CollectionSpec) -> CollectionSpec:
    """The same collection fetching only GUID and name (with alias names): which names
    Tally lists now (diagnostics)."""
    return replace(spec, collection_id=f"{spec.collection_id}Names", fetch=("GUID", "NAME"))


def collection_request(
    spec: CollectionSpec,
    company: str | None = None,
    period: tuple[date, date] | None = None,
    since_alter_id: int | None = None,
    balances_period: tuple[date, date] | None = None,
    child_of: str | None = None,
) -> str:
    """Builds a collection export.

    - `period` (inclusive) limits objects by $Date. Tally is given an *exclusive* end date
      (the day after the period) and the filter uses `<`. For calendar months that end date
      is always the 1st of a month. This matters because TallyPrime in Educational mode
      silently returns nothing for report dates other than the 1st, 2nd or 31st.
    - `since_alter_id` returns only objects created or altered after that AlterID
      (incremental sync, SYN-002). AlterID is a company-wide change counter.
    - `balances_period` (inclusive) sets the period that balances such as $ClosingBalance
      are computed for, without filtering objects. TallyPrime accepts any end date here,
      also in Educational mode.
    """
    static = ["<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>"]
    if company is not None:
        static.append(f"<SVCURRENTCOMPANY>{escape(company)}</SVCURRENTCOMPANY>")
    extra = "".join(f"<COMPUTE>{formula}</COMPUTE>" for formula in spec.compute)
    if child_of is not None:  # e.g. one stock item's batches
        extra = f"<CHILDOF>{escape(child_of)}</CHILDOF>{extra}"
    formulae = []
    if period is not None:
        static.append(_dates(period[0], period[1] + timedelta(days=1)))  # exclusive end
        extra += f"<FILTER>{_PERIOD_FILTER}</FILTER>"
        formulae.append(
            f'<SYSTEM TYPE="Formulae" NAME="{_PERIOD_FILTER}">'
            "$Date &gt;= ##SVFromDate AND $Date &lt; ##SVToDate</SYSTEM>"
        )
    if balances_period is not None:
        static.append(_dates(*balances_period))
    if since_alter_id is not None:
        extra += f"<FILTER>{_CHANGED_FILTER}</FILTER>"
        formulae.append(
            f'<SYSTEM TYPE="Formulae" NAME="{_CHANGED_FILTER}">'
            f"$AlterID &gt; {int(since_alter_id)}</SYSTEM>"
        )
    return (
        "<ENVELOPE>"
        "<HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST>"
        f"<TYPE>Collection</TYPE><ID>{spec.collection_id}</ID></HEADER>"
        "<BODY><DESC>"
        f"<STATICVARIABLES>{''.join(static)}</STATICVARIABLES>"
        "<TDL><TDLMESSAGE>"
        f'<COLLECTION NAME="{spec.collection_id}" ISMODIFY="No">'
        f"<TYPE>{spec.tally_type}</TYPE>"
        f"<FETCH>{', '.join(spec.fetch)}</FETCH>"
        f"{extra}"
        "</COLLECTION>"
        f"{''.join(formulae)}"
        "</TDLMESSAGE></TDL>"
        "</DESC></BODY>"
        "</ENVELOPE>"
    )
