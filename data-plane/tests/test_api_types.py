"""frontend/src/api/types.ts is generated from the API (devtools/api_types.py) and current."""

from devtools.api_types import TARGET, render, ts_type


def test_the_frontend_types_are_up_to_date() -> None:
    assert TARGET.read_text(encoding="utf-8") == render(), (
        "frontend/src/api/types.ts is stale: run python -m devtools.api_types "
        "(or ./dev.ps1 diagrams)"
    )


def test_schemas_translate_to_typescript() -> None:
    assert ts_type({"anyOf": [{"type": "string"}, {"type": "null"}]}) == "string | null"
    assert ts_type({"type": "array", "items": {"$ref": "#/components/schemas/Row"}}) == "Row[]"
    assert ts_type({"type": "object", "additionalProperties": {"type": "integer"}}) == (
        "Record<string, number>"
    )
    assert ts_type({"const": "ok"}) == '"ok"'
