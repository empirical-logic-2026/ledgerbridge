"""The UTR is stored but never shown in the dashboard: no /api/v1 response model has a `utr` or
`utr_source` field, and no table explorer dataset (whose CSV export has the same columns)
offers or reads the stored columns. Needs no database."""

from typing import Any

from sqlalchemy import Column
from sqlalchemy.sql import visitors

from api.main import create_app
from api.v1.dataset_specs import DATASETS

HIDDEN = {"utr", "utr_source"}


def _properties(schema: dict[str, Any]) -> set[str]:
    """Every property name anywhere in an OpenAPI schema, nested ones included."""
    found: set[str] = set()
    if isinstance(schema, dict):
        found |= set(schema.get("properties", {}))
        for value in schema.values():
            found |= _properties(value)
    elif isinstance(schema, list):
        for value in schema:
            found |= _properties(value)
    return found


def _columns(expression: Any) -> set[str]:
    """The table columns an SQL expression reads."""
    return {
        f"{c.table.name}.{c.name}"
        for c in visitors.iterate(expression)
        if isinstance(c, Column) and c.table is not None
    }


def test_no_api_v1_response_has_a_utr_field() -> None:
    schema = create_app().openapi()
    v1 = {p: ops for p, ops in schema["paths"].items() if p.startswith("/api/v1")}
    assert v1
    assert not _properties(schema.get("components", {})) & HIDDEN
    assert not _properties(v1) & HIDDEN


def test_no_dataset_offers_or_reads_the_utr() -> None:
    stored = {f"voucher_lines.{name}" for name in HIDDEN}
    for dataset in DATASETS.values():
        keys = {*dataset.dimensions, *dataset.measures, *dataset.filters}
        assert not keys & HIDDEN, dataset.key
        labels = [d.label for d in dataset.dimensions.values()]
        assert "UTR" not in labels, dataset.key
        for d in dataset.dimensions.values():
            assert not (_columns(d.id_expr) | _columns(d.label_expr)) & stored, d.key
        for m in dataset.measures.values():
            assert not (_columns(m.row_expr) | _columns(m.total_expr)) & stored, m.key
