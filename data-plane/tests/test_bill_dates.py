"""Bill dates, due dates and opening bills (data completion, part 2), on the seeded test
company's recordings of 2026-11-06 (tests/fixtures/tally/rules/data-completion): a sales
invoice with a 30-day credit period (BILL-1), a purchase invoice due on a date (BILL-2), and
the opening bills of a customer and a vendor."""

from datetime import date
from decimal import Decimal

import pytest

from connectors.base import SourceRecord
from connectors.tally import mapping, parser
from core.canonical import CanonicalBill, CanonicalOpeningBill, CanonicalOpeningBills
from tests.conftest import FIXTURES

RULES = FIXTURES / "tally" / "rules" / "data-completion"


@pytest.mark.parametrize(
    ("bill_date", "period", "due"),
    [
        (date(2026, 10, 1), "30 Days", date(2026, 10, 31)),
        (date(2026, 10, 1), "1 Day", date(2026, 10, 2)),
        (date(2026, 10, 1), "45", date(2026, 11, 15)),
        (date(2026, 10, 2), "31-Oct-26", date(2026, 10, 31)),  # a due date, as Tally exports it
        (date(2026, 10, 2), "31-Oct-2026", date(2026, 10, 31)),
        (None, "31-Oct-26", date(2026, 10, 31)),
        (None, "30 Days", None),  # days after an unknown date
        (date(2026, 10, 1), "", None),
        (date(2026, 10, 1), None, None),
        (date(2026, 10, 1), "next month", None),
    ],
)
def test_due_date(bill_date: date | None, period: str | None, due: date | None) -> None:
    assert mapping.due_date(bill_date, period) == due


def _bills(marker: str) -> list[CanonicalBill]:
    body = (RULES / "vouchers_2026-10.xml").read_bytes()
    for element in parser.objects(parser.parse_response(body), "VOUCHER"):
        if f"[lb-seed:{marker}]" in (element.findtext("NARRATION") or ""):
            voucher = mapping.voucher(element, parser.source_key(element))
            return [bill for line in voucher.lines for bill in line.bills]
    raise AssertionError(f"{marker} not recorded")


def test_a_credit_period_in_days_runs_from_the_bills_date() -> None:
    (bill,) = _bills("BILL-1")
    assert (bill.name, bill.bill_type) == ("INV-T1", "new_ref")
    assert (bill.bill_date, bill.due_date) == (date(2026, 10, 1), date(2026, 10, 31))


def test_a_credit_period_given_as_a_date_is_the_due_date() -> None:
    (bill,) = _bills("BILL-2")
    assert (bill.name, bill.bill_type) == ("PI-I2", "new_ref")
    assert (bill.bill_date, bill.due_date) == (date(2026, 10, 2), date(2026, 10, 31))


def _opening_bills(ledger: str) -> tuple[CanonicalOpeningBill, ...]:
    body = (RULES / "ledger_opening_bills.xml").read_bytes()
    for element in parser.objects(parser.parse_response(body), "LEDGER"):
        if parser.object_name(element) == ledger:
            record = mapping.opening_bills(element, parser.source_key(element))
            assert record.source_key == parser.source_key(element)
            return record.bills
    raise AssertionError(f"{ledger} not recorded")


def test_a_customers_opening_bills_are_debits_with_their_due_dates() -> None:
    assert _opening_bills("Customer Theta GST") == (
        CanonicalOpeningBill("OB-T1", Decimal("10000"), date(2025, 3, 1), date(2025, 3, 31)),
        CanonicalOpeningBill("OB-T2", Decimal("5000"), date(2025, 3, 31), None),
    )


def test_a_vendors_opening_bills_are_credits() -> None:
    assert _opening_bills("Vendor Iota GST") == (
        CanonicalOpeningBill("OB-I1", Decimal("-5000"), date(2025, 3, 1), date(2025, 4, 15)),
        CanonicalOpeningBill("OB-I2", Decimal("-3000"), date(2025, 3, 31), None),
    )


def test_a_ledger_without_opening_bills_has_none() -> None:
    assert _opening_bills("Electricity") == ()


def test_opening_bills_carry_no_extra_fields() -> None:
    """A field the mapping doesn't read stays with the ledger's own record, not its bills."""
    payload = (
        '<LEDGER NAME="L"><GUID>g-1</GUID><ALTERID>7</ALTERID><UDF:REGION>North</UDF:REGION>'
        "<BILLALLOCATIONS.LIST><NAME>B1</NAME><OPENINGBALANCE>-10.00</OPENINGBALANCE>"
        "</BILLALLOCATIONS.LIST></LEDGER>"
    )
    record = SourceRecord("k", "ledger_opening_bills", "g-1", 7, "xml", payload)
    (bills,) = mapping.to_canonical(record)
    assert bills == CanonicalOpeningBills("g-1", (CanonicalOpeningBill("B1", Decimal(10)),))
