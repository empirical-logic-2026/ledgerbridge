import xml.etree.ElementTree as ET  # noqa: N817

from connectors.tally import parser
from connectors.tally.signs import (
    check_balance_sides,
    check_opening_balances,
    check_vouchers,
    postings,
)
from tests.conftest import FIXTURES

SYNTHETIC = FIXTURES / "tally_synthetic"


def _vouchers() -> list[ET.Element]:
    body = (SYNTHETIC / "vouchers_2024-04.xml").read_bytes()
    return parser.objects(parser.parse_response(body), "VOUCHER")


def test_synthetic_vouchers_confirm_debits_negative() -> None:
    report = check_vouchers(_vouchers(), anchor_voucher="1", anchor_ledger="Rent")
    assert report.vouchers == 2
    # Includes the invoice-mode accounting allocation inside the inventory entry.
    assert report.postings == 5
    assert report.debit.negative == 2 and report.debit.positive == 0
    assert report.credit.positive == 3 and report.credit.negative == 0
    assert report.balanced_vouchers == 2
    assert report.debits_negative
    assert report.anchor == "line for the given ledger is a debit and its AMOUNT is negative"
    assert report.lines()[-1].startswith("CONFIRMED")


def test_unbalanced_or_positive_debit_is_not_confirmed() -> None:
    bad = ET.fromstring(
        "<VOUCHER><ALLLEDGERENTRIES.LIST><LEDGERNAME>Rent</LEDGERNAME>"
        "<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>"
        "<AMOUNT>100.00</AMOUNT></ALLLEDGERENTRIES.LIST></VOUCHER>"
    )
    report = check_vouchers([*_vouchers(), bad])
    assert report.debit.positive == 1
    assert report.unbalanced_vouchers == 1
    assert not report.debits_negative
    assert report.lines()[-1].startswith("NOT CONFIRMED")


def test_report_contains_no_amounts_or_names() -> None:
    text = "\n".join(check_vouchers(_vouchers(), "1", "Rent").lines())
    assert "1000" not in text and "Rent" not in text and "Cash" not in text


def test_opening_balances() -> None:
    body = (SYNTHETIC / "ledgers.xml").read_bytes()
    report = check_opening_balances(parser.objects(parser.parse_response(body), "LEDGER"), "Cash")
    assert report.ledgers == 3
    assert (report.signs.negative, report.signs.positive, report.signs.zero) == (1, 1, 1)
    assert report.sums_to_zero
    assert report.anchor == "negative"


def _balances() -> list[ET.Element]:
    body = (SYNTHETIC / "ledger_balances.xml").read_bytes()
    return parser.objects(parser.parse_response(body), "LEDGER")


def test_balance_sides_agree_with_tallys_isdr() -> None:
    report = check_balance_sides(_balances(), anchors=("Rent", "Cash", "Missing"))
    assert (report.agree, report.disagree, report.zero) == (5, 0, 1)
    assert report.debits_negative
    assert report.anchors["Rent"] == "closing 1,000.00 Dr (XML amount negative)"
    assert report.anchors["Cash"] == "closing 4,000.00 Dr (XML amount negative)"
    assert report.anchors["Missing"] == "not found"
    assert report.lines()[-1].startswith("CONFIRMED")


def test_balance_side_disagreement_is_not_confirmed() -> None:
    flipped = ET.fromstring(
        "<LEDGER NAME='X'><CLOSINGBALANCE>-10.00</CLOSINGBALANCE>"
        "<LBCLOSINGISDR>No</LBCLOSINGISDR></LEDGER>"
    )
    report = check_balance_sides([*_balances(), flipped])
    assert report.disagree == 1
    assert not report.debits_negative


def test_anchor_voucher_can_be_found_by_narration_text() -> None:
    report = check_vouchers(_vouchers(), anchor_voucher="rent payment", anchor_ledger="Rent")
    assert report.anchor == "line for the given ledger is a debit and its AMOUNT is negative"


def test_complete_all_ledger_entries_are_not_double_counted() -> None:
    # TallyPrime item invoice: ALLLEDGERENTRIES already holds the sales posting.
    invoice = ET.fromstring(
        "<VOUCHER>"
        "<ALLLEDGERENTRIES.LIST><LEDGERNAME>Party</LEDGERNAME><ISDEEMEDPOSITIVE>Yes"
        "</ISDEEMEDPOSITIVE><AMOUNT>-100.00</AMOUNT></ALLLEDGERENTRIES.LIST>"
        "<ALLLEDGERENTRIES.LIST><LEDGERNAME>Sales</LEDGERNAME><ISDEEMEDPOSITIVE>No"
        "</ISDEEMEDPOSITIVE><AMOUNT>100.00</AMOUNT></ALLLEDGERENTRIES.LIST>"
        "<LEDGERENTRIES.LIST><LEDGERNAME>Party</LEDGERNAME><AMOUNT>-100.00</AMOUNT>"
        "</LEDGERENTRIES.LIST>"
        "<ALLINVENTORYENTRIES.LIST><ACCOUNTINGALLOCATIONS.LIST><LEDGERNAME>Sales</LEDGERNAME>"
        "<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE><AMOUNT>100.00</AMOUNT>"
        "</ACCOUNTINGALLOCATIONS.LIST></ALLINVENTORYENTRIES.LIST>"
        "</VOUCHER>"
    )
    assert [e.findtext("LEDGERNAME") for e in postings(invoice)] == ["Party", "Sales"]
    report = check_vouchers([invoice])
    assert (report.balanced_vouchers, report.unbalanced_vouchers) == (1, 0)


def test_cancelled_voucher_placeholder_entry_is_ignored() -> None:
    cancelled = ET.fromstring(
        "<VOUCHER><ISCANCELLED>Yes</ISCANCELLED><ALLLEDGERENTRIES.LIST/></VOUCHER>"
    )
    report = check_vouchers([*_vouchers(), cancelled])
    assert report.unparsable == 0
    assert report.debits_negative
