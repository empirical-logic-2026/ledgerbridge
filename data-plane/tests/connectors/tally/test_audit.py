"""Counts the recorded Tally objects against the canonical rows stored for each entity."""

from argparse import Namespace
from datetime import date
from unittest.mock import Mock

import pytest
from sqlalchemy import select

from connectors.base import SourceEntity
from connectors.tally.audit import AuditCounts, VoucherExclusions, audit_counts
from connectors.tally.fixtures import DEFAULT_DIR, load_manifest
from core.models import accounting as A  # noqa: N812


def _entity(session, connection):
    link = session.scalar(
        select(A.EntitySource).where(A.EntitySource.connection_id == connection.id)
    )
    assert link is not None
    entity = session.get(A.Entity, link.entity_id)
    assert entity is not None and entity.books_from is not None
    return link, entity


def test_counts_compare_recorded_masters_and_vouchers(synced, connector, session) -> None:
    link, entity = _entity(session, synced)
    manifest = load_manifest(DEFAULT_DIR)
    recorded_collections = frozenset(manifest["files"])
    result = audit_counts(
        session,
        synced.id,
        entity.id,
        SourceEntity(link.source_entity_key, link.source_entity_name, entity.books_from),
        connector,
        date(2026, 9, 30),
        recorded_collections,
    )

    masters = {row.object_type: row for row in result.masters}
    assert masters["company"].source_count == masters["company"].stored_count == 1
    for object_type in (
        "group",
        "ledger",
        "voucher_type",
        "unit",
        "stock_group",
        "godown",
        "stock_item",
        "cost_centre",
    ):
        assert masters[object_type].difference == 0, object_type
    assert masters["currency"].source_count is None
    assert masters["cost_category"].source_count is None
    assert result.vouchers
    assert all(row.month <= date(2026, 9, 1) for row in result.vouchers)
    assert all(row.difference == 0 for row in result.vouchers)


def test_stored_counts_are_scoped_to_each_company(
    synced, connector, session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, entity = _entity(session, synced)
    second = A.Entity(
        code="AUDIT_SECOND",
        name="Synthetic second company",
        books_from=entity.books_from,
    )
    session.add(second)
    session.flush()
    session.add(
        A.EntitySource(
            entity_id=second.id,
            connection_id=synced.id,
            source_entity_key="synthetic-second-key",
            source_entity_name="LedgerBridge Test Co",
        )
    )
    session.commit()
    monkeypatch.setattr(connector, "chunk_keys", Mock(return_value=set()))
    monkeypatch.setattr(connector, "voucher_counts", Mock(return_value={}))

    result = audit_counts(
        session,
        synced.id,
        second.id,
        SourceEntity("synthetic-second-key", "LedgerBridge Test Co", entity.books_from),
        connector,
        date(2026, 9, 30),
        frozenset(load_manifest(DEFAULT_DIR)["files"]),
    )

    stored = {row.object_type: row.stored_count for row in result.masters}
    assert stored["company"] == 1
    assert all(
        row.stored_count == 0 and row.source_count in (None, 0)
        for row in result.masters
        if row.object_type != "company"
    )
    assert result.vouchers == ()


def test_audit_refuses_to_guess_a_missing_books_from_date(connector, session) -> None:
    with pytest.raises(ValueError, match="no books-from date"):
        audit_counts(
            session,
            1,
            1,
            SourceEntity("synthetic-key", "Synthetic company", None),
            connector,
            date(2026, 9, 30),
        )


def test_cli_output_does_not_include_company_names(
    synced, connector, session, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from workers import cli

    link, entity = _entity(session, synced)
    source_entity = SourceEntity(link.source_entity_key, link.source_entity_name, entity.books_from)
    monkeypatch.setattr(cli, "connector_for", Mock(return_value=connector))
    monkeypatch.setattr(connector, "list_entities", lambda: [source_entity])
    monkeypatch.setattr(
        "connectors.tally.audit.audit_counts",
        Mock(return_value=AuditCounts((), (), VoucherExclusions(0, 0, 0, 0))),
    )

    assert cli._audit_counts(session, Namespace(connection=synced.name)) == 0

    output = capsys.readouterr().out
    assert load_manifest(DEFAULT_DIR)["company"] not in output
    assert "entity" in output and "company 1" in output
