"""The UTR rule (core/utr.py): only values that look like a bank's transaction reference."""

import pytest

from core.utr import as_utr, in_text


@pytest.mark.parametrize(
    ("value", "utr"),
    [
        ("HDFCN52026100112345", "HDFCN52026100112345"),  # NEFT: 4 letters, N, 14 more
        ("sbinr52026100100001", "SBINR52026100100001"),  # RTGS, any case
        ("629012345678", "629012345678"),  # IMPS / UPI: 12 digits
        ("UTR: 1234ABCD5678", "1234ABCD5678"),  # labelled
        ("UTR No. AXIS99887766", "AXIS99887766"),
        ("a12f490e-4b6c-49c0-bf85-bec1eaf56181", None),  # Tally's own key
        ("7GJ2K9QX4M1Z8P3T", None),  # a random 16-character code (Tally's generated id)
        ("000451", None),  # a cheque number
        ("NEFT", None),
        ("12345678901", None),  # 11 digits
        ("1234567890123", None),  # 13 digits
        ("HDFCN123", None),  # too short after N
        (None, None),
    ],
)
def test_a_value_is_a_utr_only_when_it_looks_like_one(value: str | None, utr: str | None) -> None:
    assert as_utr(value) == utr


def test_a_utr_in_a_narration() -> None:
    assert in_text("Courier paid by NEFT, UTR HDFCN52026100112345") == "HDFCN52026100112345"
    assert in_text("Paid via IMPS ref 629012345678 to vendor") == "629012345678"
    assert in_text("Being rent for September") is None
    assert in_text("Phone 98450 12345, invoice 123456789012345") is None  # 15 digits: no
    assert in_text(None) is None
