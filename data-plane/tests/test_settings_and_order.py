"""Settings and order (data completion, part 6), on the seeded test company's recordings of
2026-11-06 (tests/fixtures/tally/rules/data-completion): the groups' and ledgers' sort
positions, ledgers affecting stock, the company's settings, numbering series (SER-1 in a
"Branch" series of Seed Sales), reversing journals' last day (REV-JNL-1, REV-JNL-2) and
cash flow."""

import xml.etree.ElementTree as ET  # noqa: N817
from datetime import date

from connectors.tally import mapping, parser
from core.canonical import CanonicalLedger, CanonicalNumberSeries, CanonicalVoucher
from core.statements import _Group, _group_order
from tests.conftest import FIXTURES

RULES = FIXTURES / "tally" / "rules" / "data-completion"
# Tally's Trial Balance order of its predefined primary groups (their SORTPOSITION).
TALLY_ORDER = (
    "Capital Account", "Loans (Liability)", "Current Liabilities", "Fixed Assets", "Investments",
    "Current Assets", "Branch / Divisions", "Misc. Expenses (ASSET)", "Suspense A/c",
    "Sales Accounts", "Purchase Accounts", "Direct Incomes", "Direct Expenses",
    "Indirect Incomes", "Indirect Expenses",
)  # fmt: skip


def _objects(file: str, tag: str) -> list[ET.Element]:
    return parser.objects(parser.parse_response((RULES / file).read_bytes()), tag)


def group_positions() -> dict[str, int]:
    """Every recorded group's name and sort position (used by the statement tests too)."""
    groups = (mapping.group(e, parser.source_key(e)) for e in _objects("groups.xml", "GROUP"))
    return {g.name: g.sort_position for g in groups if g.sort_position is not None}


def test_primary_groups_sorted_by_position_follow_tallys_trial_balance() -> None:
    positions = group_positions()
    primary = [g for g in TALLY_ORDER if g in positions]
    assert primary == list(TALLY_ORDER)
    assert sorted(primary, key=positions.__getitem__) == list(TALLY_ORDER)


def test_the_order_falls_back_to_nature_without_positions() -> None:
    groups = [
        _Group(1, "Expenses", "expense", False, None),
        _Group(2, "Capital", "equity", False, None),
        _Group(3, "Assets", "asset", False, None, sort_position=60),
        _Group(4, "Loans", "liability", False, None, sort_position=20),
    ]
    assert [g.name for g in sorted(groups, key=_group_order)] == [
        "Loans", "Assets", "Capital", "Expenses"
    ]  # fmt: skip


def test_ledgers_keep_their_position_and_whether_they_affect_stock() -> None:
    ledgers = [
        r
        for e in _objects("ledgers.xml", "LEDGER")
        for r in mapping.ledger(e, parser.source_key(e), "e")
        if isinstance(r, CanonicalLedger)
    ]
    assert {x.sort_position for x in ledgers} == {1000}  # Tally's default: listed by name
    assert sum(1 for x in ledgers if x.affects_stock) == 5
    assert all(x.affects_stock is not None for x in ledgers)


def test_the_companys_settings() -> None:
    (element,) = _objects("companies.xml", "COMPANY")
    company = mapping.company(element, parser.source_key(element))
    assert (company.is_integrated, company.is_fifo, company.audited_upto) == (
        True, True, date(2027, 1, 1)
    )  # fmt: skip


def test_a_settings_field_not_sent_is_unknown() -> None:
    element = ET.fromstring("<COMPANY NAME='X'><GUID>g</GUID></COMPANY>")  # noqa: S314
    company = mapping.company(element, "g")
    assert (company.is_integrated, company.is_fifo, company.audited_upto) == (None, None, None)


def test_a_voucher_types_numbering_series() -> None:
    elements = _objects("voucher_types.xml", "VOUCHERTYPE")
    types = {t.name: t for t in (mapping.voucher_type(e, parser.source_key(e)) for e in elements)}
    assert [s.name for s in types["Seed Sales"].number_series] == ["Default", "Branch"]
    assert types["Seed Sales"].number_series[1] == CanonicalNumberSeries(
        "Branch", "Automatic", "Auto Renumber", 1, 0, False, False
    )
    assert [s.numbering_sub_method for s in types["Sales"].number_series] == ["Auto Retain"]


def _vouchers() -> list[CanonicalVoucher]:
    return [
        mapping.voucher(e, parser.source_key(e))
        for f in sorted(RULES.glob("vouchers_*.xml"))
        for e in _objects(f.name, "VOUCHER")
    ]


def test_vouchers_keep_their_series_last_day_and_cash_flow() -> None:
    vouchers = _vouchers()
    marked = {(v.narration or "").rsplit("[lb-seed:", 1)[-1].rstrip("]"): v for v in vouchers}
    assert marked["SER-1"].number_series == "Branch"
    assert {v.number_series for v in vouchers} == {"Default", "Branch"}
    assert (marked["REV-JNL-1"].active_to, marked["REV-JNL-2"].active_to) == (
        date(2026, 10, 1), date(2026, 9, 1)
    )  # fmt: skip
    assert {v.voucher_type_name for v in vouchers if v.active_to} == {"Reversing Journal"}
    cash = {v.voucher_type_name for v in vouchers if v.has_cash_flow}
    assert {"Receipt", "Contra"} <= cash and "Sales" not in cash
