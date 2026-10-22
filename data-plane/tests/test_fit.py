"""Fitting values to their columns (core/fit.py, ADR-025): cases the sync tests don't reach."""

from core.fit import PLACEHOLDER, fitter
from core.models import accounting as A  # noqa: N812

SURROGATE = "\ud800"  # a character MySQL can't store


def test_a_too_long_value_with_invalid_characters_is_kept_in_extra() -> None:
    """Cleaning the invalid characters doesn't make a long value fit: it must still go to
    extra (it used to reach the database too long and fail its record)."""
    name = "x" * 300 + SURROGATE
    fitted = fitter(A.Ledger).fit({"name": name})
    assert fitted.row["name"] == PLACEHOLDER
    assert "name" in fitted.unfit
    assert fitted.warnings == [
        "invalid characters and too long (length 301, column allows 255): ledgers.name"
    ]


def test_a_short_value_with_invalid_characters_is_cleaned() -> None:
    fitted = fitter(A.Ledger).fit({"name": "ab" + SURROGATE})
    assert fitted.row["name"] == "ab" + chr(0xFFFD)
    assert fitted.warnings == ["invalid characters (length 3): ledgers.name"]
