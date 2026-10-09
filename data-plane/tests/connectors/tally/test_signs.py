import xml.etree.ElementTree as ET  # noqa: N817

from connectors.tally import parser
from connectors.tally.signs import check_opening_balances, check_vouchers
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
        "<VOUCHER><ALLLEDGERENTRIES.LIST><ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>"
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
