"""Bill-wise payment status rules for customers and vendors."""

from datetime import date
from decimal import Decimal

from api.v1.ageing import _row
from api.v1.home import _top
from core.ageing import AgeingRow
from core.overview import TopCustomer
from core.parties import KINDS, bill_payment_status, party_payment_status


def test_bill_status_uses_remaining_amount_and_due_date() -> None:
    as_of = date(2026, 9, 30)

    assert bill_payment_status(Decimal("25.00"), date(2026, 9, 29), as_of) == "overdue"
    assert bill_payment_status(Decimal("25.00"), as_of, as_of) == "pending"
    assert bill_payment_status(Decimal("0.00"), date(2026, 9, 1), as_of) == "settled"
    assert bill_payment_status(Decimal("-25.00"), date(2026, 9, 1), as_of) == "advance"


def test_bill_status_treats_partial_settlement_and_tolerance_correctly() -> None:
    as_of = date(2026, 9, 30)

    assert bill_payment_status(Decimal("10.00"), date(2026, 9, 29), as_of) == "overdue"
    assert bill_payment_status(Decimal("0.004"), date(2026, 9, 1), as_of) == "settled"
    assert bill_payment_status(Decimal("-0.005"), date(2026, 9, 1), as_of) == "advance"


def test_party_status_does_not_call_advances_overdue() -> None:
    assert party_payment_status(Decimal("-1.00"), Decimal("10.00"), Decimal(0)) == "advance"
    assert party_payment_status(Decimal(0), Decimal("10.00"), Decimal(0)) == "settled"


def test_party_status_requires_billwise_evidence_for_pending() -> None:
    assert party_payment_status(Decimal("25.00"), Decimal("5.00"), Decimal("20.00")) == "mixed"
    assert party_payment_status(Decimal("25.00"), Decimal(0), Decimal("25.00")) == "pending"
    assert party_payment_status(Decimal("25.00"), Decimal(0), Decimal(0)) == "no_bill"


def test_customer_and_supplier_debit_credit_signs_are_normalized_before_classification() -> None:
    customer_sign = KINDS["customers"][3]
    vendor_sign = KINDS["vendors"][3]

    customer_receivable = Decimal("125.00") * customer_sign
    customer_advance = Decimal("-125.00") * customer_sign
    supplier_payable = Decimal("-125.00") * vendor_sign
    supplier_advance = Decimal("125.00") * vendor_sign

    assert party_payment_status(customer_receivable, Decimal("125.00"), Decimal(0)) == "overdue"
    assert party_payment_status(customer_advance, Decimal("125.00"), Decimal(0)) == "advance"
    assert party_payment_status(supplier_payable, Decimal("125.00"), Decimal(0)) == "overdue"
    assert party_payment_status(supplier_advance, Decimal("125.00"), Decimal(0)) == "advance"


def test_multiple_bills_and_partial_payments_are_classified_individually() -> None:
    as_of = date(2026, 9, 30)
    bills = [
        (Decimal("35.00"), date(2026, 9, 1)),  # partially paid, remainder overdue
        (Decimal("20.00"), date(2026, 10, 1)),  # a separate bill, not yet due
        (Decimal("-15.00"), date(2026, 8, 1)),  # advance, never overdue
    ]

    states = [bill_payment_status(amount, due, as_of) for amount, due in bills]
    assert states == ["overdue", "pending", "advance"]
    overdue = pending = Decimal(0)
    for (amount, _), state in zip(bills, states, strict=True):
        if state == "overdue":
            overdue += amount
        elif state == "pending":
            pending += amount
    assert (
        party_payment_status(
            sum((amount for amount, _ in bills), Decimal(0)),
            overdue,
            pending,
            Decimal("15.00"),
        )
        == "mixed"
    )


def test_party_with_bills_in_different_states_is_not_summarized_as_only_overdue() -> None:
    assert (
        party_payment_status(
            Decimal("100.00"),
            Decimal("80.00"),
            Decimal("20.00"),
        )
        == "mixed"
    )
    assert (
        party_payment_status(
            Decimal("100.00"),
            Decimal("125.00"),
            Decimal(0),
            Decimal("25.00"),
        )
        == "mixed"
    )


def test_ageing_summary_does_not_count_past_due_advances_as_overdue_or_pending() -> None:
    row = AgeingRow(1, "Synthetic party", Decimal("-45.00"))

    row.add_outstanding(Decimal("80.00"), 30)
    row.add_outstanding(Decimal("-150.00"), 60)
    row.add_outstanding(Decimal("25.00"), 0)

    assert row.overdue == Decimal("80.00")
    assert row.pending == Decimal("25.00")
    assert party_payment_status(row.balance, row.overdue, row.pending) == "advance"


def test_zero_balance_and_missing_bill_details_do_not_guess_a_payment_state() -> None:
    assert party_payment_status(Decimal(0), Decimal(90), Decimal(0)) == "settled"
    assert party_payment_status(Decimal("100.00"), Decimal(0), Decimal(0)) == "no_bill"


def test_ageing_api_legacy_status_agrees_with_normalized_classification() -> None:
    advance = AgeingRow(1, "Synthetic party", Decimal("-20.00"), overdue=Decimal("10.00"))
    settled = AgeingRow(2, "Another synthetic party", Decimal(0), overdue=Decimal("10.00"))
    mixed = AgeingRow(
        3,
        "Mixed synthetic party",
        Decimal("10.00"),
        overdue=Decimal("20.00"),
        pending=Decimal("5.00"),
    )

    assert _row(advance).payment_status == "advance"
    assert _row(advance).status == "current"
    assert _row(settled).payment_status == "settled"
    assert _row(settled).status == "current"
    assert _row(mixed).payment_status == "mixed"
    assert _row(mixed).status == "current"


def test_overview_api_summarizes_mixed_customer_bills_without_calling_them_overdue() -> None:
    customer = TopCustomer(
        3,
        "Synthetic customer",
        Decimal("100.00"),
        Decimal("100.00"),
        Decimal("80.00"),
        Decimal("20.00"),
        Decimal(0),
    )

    [result] = _top([customer], [])
    assert result.payment_status == "mixed"
    assert result.status == "current"
