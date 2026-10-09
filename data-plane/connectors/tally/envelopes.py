"""Builds Tally XML export requests (TDL collections).

Only Export requests are ever built: the connector is read-only (CON-008).
Inline TDL collections with explicit fetch lists work in both TallyPrime and Tally.ERP 9.
"""

from dataclasses import dataclass
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


_KEYS = ("GUID", "ALTERID", "MASTERID")

COMPANIES = CollectionSpec(
    "LBCompanies",
    "Company",
    "COMPANY",
    "company",
    ("NAME", "GUID", "BOOKSFROM", "STARTINGFROM", "ENDINGAT"),
)
GROUPS = CollectionSpec("LBGroups", "Group", "GROUP", "group", _KEYS)
LEDGERS = CollectionSpec("LBLedgers", "Ledger", "LEDGER", "ledger", _KEYS)
VOUCHER_TYPES = CollectionSpec(
    "LBVoucherTypes", "VoucherType", "VOUCHERTYPE", "voucher_type", _KEYS
)
VOUCHERS = CollectionSpec(
    "LBVouchers",
    "Voucher",
    "VOUCHER",
    "voucher",
    (
        *_KEYS,
        "ALLLEDGERENTRIES",
        "LEDGERENTRIES",
        "ALLINVENTORYENTRIES",
        "INVENTORYENTRIES",
    ),
)

# Ledger balances with Tally's own Dr/Cr judgement ($$IsDr), independent of how amounts are
# signed in XML. Used to confirm the sign convention (schema.md Section 7).
LEDGER_BALANCES = CollectionSpec(
    "LBLedgerBalances",
    "Ledger",
    "LEDGER",
    "ledger_balance",
    ("NAME", "OPENINGBALANCE", "CLOSINGBALANCE"),
    compute=(
        "LBOPENINGISDR : $$IsDr:$OpeningBalance",
        "LBCLOSINGISDR : $$IsDr:$ClosingBalance",
    ),
)

MASTER_SPECS = (GROUPS, LEDGERS, VOUCHER_TYPES)
ALL_SPECS = (COMPANIES, *MASTER_SPECS, VOUCHERS)

_PERIOD_FILTER = "LBInPeriod"


def tally_date(value: date) -> str:
    return value.strftime("%Y%m%d")


def collection_request(
    spec: CollectionSpec,
    company: str | None = None,
    period: tuple[date, date] | None = None,
) -> str:
    """Builds a collection export. `period` (inclusive) limits objects by $Date.

    Tally is given an *exclusive* end date (the day after the period) and the filter uses
    `<`. For calendar months that end date is always the 1st of a month. This matters
    because TallyPrime in Educational mode silently returns nothing for report dates
    other than the 1st, 2nd or 31st, so a month ending on the 30th would come back empty.
    """
    static = ["<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>"]
    if company is not None:
        static.append(f"<SVCURRENTCOMPANY>{escape(company)}</SVCURRENTCOMPANY>")
    collection_extra = "".join(f"<COMPUTE>{formula}</COMPUTE>" for formula in spec.compute)
    formulae = ""
    if period is not None:
        end_exclusive = period[1] + timedelta(days=1)
        static.append(f'<SVFROMDATE TYPE="Date">{tally_date(period[0])}</SVFROMDATE>')
        static.append(f'<SVTODATE TYPE="Date">{tally_date(end_exclusive)}</SVTODATE>')
        collection_extra += f"<FILTER>{_PERIOD_FILTER}</FILTER>"
        formulae = (
            f'<SYSTEM TYPE="Formulae" NAME="{_PERIOD_FILTER}">'
            "$Date &gt;= ##SVFromDate AND $Date &lt; ##SVToDate</SYSTEM>"
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
        "<NATIVEMETHOD>*</NATIVEMETHOD>"
        f"<FETCH>{', '.join(spec.fetch)}</FETCH>"
        f"{collection_extra}"
        "</COLLECTION>"
        f"{formulae}"
        "</TDLMESSAGE></TDL>"
        "</DESC></BODY>"
        "</ENVELOPE>"
    )
