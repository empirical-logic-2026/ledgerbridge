"""Tests for the read-only migration-history guard used by dev.ps1 up."""

from migrations.revision_guard import unknown_revisions


def test_known_database_revisions_are_accepted() -> None:
    assert unknown_revisions(["0025", "0026"], ["0025", "0026", "0027"]) == []


def test_unknown_database_revisions_are_reported() -> None:
    assert unknown_revisions(["0025", "orphaned", "0027"], ["0025", "0026", "0027"]) == ["orphaned"]


def test_multiple_unknown_database_revisions_are_sorted_and_unique() -> None:
    assert unknown_revisions(
        ["orphaned-b", "orphaned-a", "orphaned-b"],
        ["0025", "0026"],
    ) == ["orphaned-a", "orphaned-b"]
