"""The cash movement's split of a voucher's cash amount by what it was for (F-CF-001)."""

from decimal import Decimal

from core.cash_flow import OTHER, TRANSFERS, split


def test_one_other_ledger_takes_all_of_it() -> None:
    assert split(Decimal("-500"), [(7, Decimal("500"))], {7: "expenses"}) == [
        ("expenses", Decimal("-500"))
    ]


def test_several_are_split_by_their_entries_and_add_up_exactly() -> None:
    parts = dict(split(Decimal("1000"), [(1, Decimal("-2")), (2, Decimal("-1"))], {1: "customers"}))
    assert parts == {"customers": Decimal("666.6667"), OTHER: Decimal("333.3333")}
    assert sum(parts.values()) == Decimal("1000")


def test_a_voucher_with_only_cash_and_bank_is_a_transfer() -> None:
    assert split(Decimal("0"), [], {}) == [(TRANSFERS, Decimal("0"))]
