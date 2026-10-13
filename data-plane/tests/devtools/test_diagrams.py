"""The diagrams in docs/diagrams match the code (./dev.ps1 diagrams regenerates them)."""

from devtools import diagrams


def test_generated_diagram_sources_are_up_to_date() -> None:
    """Fails when the models changed but the ER or database diagrams weren't regenerated:
    run ./dev.ps1 diagrams and commit the result."""
    stale = [
        name
        for name, content in diagrams.generated().items()
        if not (diagrams.OUT / name).exists()
        or (diagrams.OUT / name).read_text(encoding="utf-8").replace("\r\n", "\n") != content
    ]
    assert not stale, f"out of date: {stale}; run ./dev.ps1 diagrams"


def test_every_source_is_rendered() -> None:
    sources = sorted(p.stem for p in diagrams.OUT.glob("*.mmd"))
    assert sources
    missing = [
        f"{stem}.{suffix}"
        for stem in sources
        for suffix in ("svg", "png")
        if not (diagrams.OUT / f"{stem}.{suffix}").exists()
    ]
    assert not missing, f"not rendered: {missing}; run ./dev.ps1 diagrams"


def test_er_diagram_has_keys_and_cardinality() -> None:
    area = next(a for a in diagrams.AREAS if a.file == "er-transactions")
    text = diagrams.er_diagram(area)
    assert "bigint id PK" in text
    assert 'bigint voucher_id FK "to vouchers"' in text
    assert 'vouchers ||--o{ voucher_lines : "voucher_id"' in text  # required: exactly one
    assert 'parties |o--o{ vouchers : "party_id"' in text  # optional: zero or one


def test_schema_diagram_limits_ai_to_reporting() -> None:
    text = diagrams.schema_diagram()
    ai_lines = [line for line in text.splitlines() if line.strip().startswith("ai_ro ")]
    assert ai_lines == ['    ai_ro ==>|"read only:<br/>reporting ONLY"| ledgerbridge_reporting']
