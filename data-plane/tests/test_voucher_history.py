"""Observed voucher-version snapshots and ambiguity-aware ledger-posting comparisons."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from connectors.base import SourceRecord
from connectors.tally.connector import TallyConnector
from core.models import accounting as A  # noqa: N812
from core.models import system as S  # noqa: N812
from core.models.source import RawRecord
from core.raw_store import RawStore
from core.transform import Transformer, mark_deleted
from core.voucher_history import (
    PostingSnapshot,
    compare_postings,
    list_ledger_changes,
    posting_snapshot,
)
from tests.conftest import COMPANY


def _posting(
    ledger: str, amount: str, line_no: int = 1, *, bill: str | None = None
) -> PostingSnapshot:
    bills = [{"bill_type": "new_ref", "bill_name": bill}] if bill else []
    return posting_snapshot(
        line_no=line_no,
        ledger_id=1,
        ledger_source_key=ledger,
        ledger_name=ledger,
        amount=Decimal(amount),
        amount_fc=None,
        currency_name=None,
        exchange_rate=None,
        is_party_line=False,
        bills=bills,
    )


def _voucher_raw(session: Session, marker: str):
    return session.scalars(
        select(RawRecord).where(
            RawRecord.object_type == "voucher",
            RawRecord.payload.contains(f"[lb-seed:{marker}]"),
        )
    ).one()


def _redeliver(
    session: Session,
    connection: S.Connection,
    connector: TallyConnector,
    raw,
    payload: str,
    alter_id: int,
) -> None:
    RawStore(session).add(
        [
            SourceRecord(
                raw.source_entity_key,
                "voucher",
                raw.source_key,
                alter_id,
                "xml",
                payload,
            )
        ],
        connection.id,
    )
    result = Transformer(session, connection.id, connector).run()
    assert result.failed == 0


def test_added_and_deleted_postings_are_classified_from_one_sided_changes() -> None:
    old = [_posting("rent", "20")]
    new = [_posting("rent", "20"), _posting("office", "5", 2)]
    added = compare_postings(old, new)
    assert [(change.change_type, change.previous_index, change.new_index) for change in added] == [
        ("added", None, 1)
    ]

    deleted = compare_postings(new, old)
    assert [
        (change.change_type, change.previous_index, change.new_index) for change in deleted
    ] == [("deleted", 1, None)]


def test_unique_posting_context_detects_debit_and_credit_modifications() -> None:
    for previous_amount, new_amount in (("100", "125"), ("-100", "-125")):
        changes = compare_postings(
            [_posting("ledger", previous_amount)],
            [_posting("ledger", new_amount)],
        )
        assert [(change.change_type, change.matching_basis) for change in changes] == [
            ("modified", "unique_posting_context")
        ]


def test_repeated_ledger_postings_with_competing_matches_are_ambiguous() -> None:
    previous = [_posting("rent", "10", 1), _posting("rent", "20", 2)]
    current = [_posting("rent", "15", 1), _posting("rent", "25", 2)]
    changes = compare_postings(previous, current)
    assert len(changes) == 4
    assert {change.change_type for change in changes} == {"ambiguous"}
    assert all(change.matching_basis == "unmatched_counterparts" for change in changes)


def test_exact_repeated_posting_is_removed_before_comparison() -> None:
    previous = [_posting("rent", "10", 1), _posting("rent", "20", 2)]
    current = [_posting("rent", "10", 1), _posting("rent", "25", 2)]
    changes = compare_postings(previous, current)
    assert [
        (change.change_type, change.previous_index, change.new_index) for change in changes
    ] == [("modified", 1, 1)]


def test_observed_versions_persist_and_duplicate_retries_are_idempotent(
    db: Session, synced: S.Connection, connector: TallyConnector
) -> None:
    raw = _voucher_raw(db, "ALTER-1")
    voucher = db.scalars(select(A.Voucher).where(A.Voucher.source_key == raw.source_key)).one()
    original_count = db.scalar(
        select(func.count())
        .select_from(A.VoucherVersion)
        .where(A.VoucherVersion.voucher_id == voucher.id)
    )
    assert original_count == 1

    altered = (
        raw.payload.replace("-1500.00", "-1700.00")
        .replace(">1500.00<", ">1700.00<")
        .replace("</VOUCHER>", "<UPDATEDDATETIME>20261019095321123</UPDATEDDATETIME></VOUCHER>")
    )
    _redeliver(db, synced, connector, raw, altered, (raw.source_alter_id or 0) + 1)
    versions = list(
        db.scalars(
            select(A.VoucherVersion)
            .where(A.VoucherVersion.voucher_id == voucher.id)
            .order_by(A.VoucherVersion.id)
        )
    )
    assert len(versions) == 2
    assert versions[1].previous_version_id == versions[0].id
    assert versions[1].raw_record_id is not None
    assert len(versions[1].payload_hash) == 64
    assert versions[1].source_altered_at == datetime(2026, 10, 19, 9, 53, 21, 123000)
    assert versions[1].observed_at is not None

    changes = list(
        db.scalars(
            select(A.VoucherLedgerChange).where(A.VoucherLedgerChange.version_id == versions[1].id)
        )
    )
    assert len(changes) == 2
    assert {change.change_type for change in changes} == {"modified"}

    history_count = len(versions)
    _redeliver(db, synced, connector, raw, altered, (raw.source_alter_id or 0) + 1)
    db.expire_all()
    assert (
        db.scalar(
            select(func.count())
            .select_from(A.VoucherVersion)
            .where(A.VoucherVersion.voucher_id == voucher.id)
        )
        == history_count
    )

    rows = list_ledger_changes(db, [voucher.entity_id], date(2026, 10, 31))
    assert len(rows) == 2
    assert all(row.company_name == COMPANY for row in rows)
    assert all(row.alteration_at == datetime(2026, 10, 19, 9, 53, 21, 123000) for row in rows)
    assert list_ledger_changes(db, [voucher.entity_id + 1000], date(2026, 10, 31)) == []


def test_missing_source_timestamp_is_not_replaced_by_observation_time(
    db: Session, synced: S.Connection, connector: TallyConnector
) -> None:
    raw = _voucher_raw(db, "ALTER-1")
    voucher = db.scalars(select(A.Voucher).where(A.Voucher.source_key == raw.source_key)).one()
    altered = raw.payload.replace("-1500.00", "-1600.00").replace(">1500.00<", ">1600.00<")
    _redeliver(db, synced, connector, raw, altered, (raw.source_alter_id or 0) + 2)

    rows = list_ledger_changes(db, [voucher.entity_id], date(2026, 10, 31))
    assert rows == []
    latest = db.scalars(
        select(A.VoucherVersion)
        .where(A.VoucherVersion.voucher_id == voucher.id)
        .order_by(A.VoucherVersion.id.desc())
    ).first()
    assert latest is not None
    assert latest.source_altered_at is None
    assert latest.observed_at is not None


def test_history_query_scopes_multiple_companies_and_inclusive_date_window(
    db: Session, synced: S.Connection
) -> None:
    other_entity = A.Entity(code="SYNTHETIC_2", name="LedgerBridge Synthetic Co 2")
    db.add(other_entity)
    db.flush()

    group = A.AccountGroup(
        entity_id=other_entity.id,
        connection_id=synced.id,
        source_key="synthetic-group-2",
        origin="live",
        name="Expenses",
        nature="expense",
    )
    db.add(group)
    db.flush()

    ledger = A.Ledger(
        entity_id=other_entity.id,
        connection_id=synced.id,
        source_key="l2",
        origin="live",
        group_id=group.id,
        name="Rent",
        ledger_kind="expense",
    )
    voucher_type = A.VoucherType(
        entity_id=other_entity.id,
        connection_id=synced.id,
        source_key="synthetic-voucher-type-2",
        origin="live",
        name="Journal",
        base_type="journal",
    )
    db.add_all([ledger, voucher_type])
    db.flush()

    voucher = A.Voucher(
        entity_id=other_entity.id,
        connection_id=synced.id,
        source_key="v2",
        origin="live",
        voucher_type_id=voucher_type.id,
        voucher_number="SYN-2",
        voucher_date=date(2026, 4, 1),
    )
    db.add(voucher)
    db.flush()

    version = A.VoucherVersion(
        entity_id=other_entity.id,
        voucher_id=voucher.id,
        connection_id=synced.id,
        voucher_source_key=voucher.source_key,
        company_name=other_entity.name,
        voucher_number=voucher.voucher_number,
        capture_key="synthetic:company-2",
        source_altered_at=datetime(2026, 4, 1, 0, 0),
        observed_at=datetime(2026, 4, 1, 0, 0),
    )
    db.add(version)
    db.flush()
    line = A.VoucherVersionLine(
        voucher_version_id=version.id,
        line_no=1,
        ledger_id=ledger.id,
        ledger_source_key=ledger.source_key,
        ledger_name=ledger.name,
        amount=Decimal("100"),
        is_party_line=False,
        details={},
        identity_hash="1" * 64,
        content_hash="2" * 64,
    )
    db.add(line)
    db.flush()
    db.add(
        A.VoucherLedgerChange(
            version_id=version.id,
            new_line_id=line.id,
            change_type="added",
            matching_basis="synthetic",
        )
    )
    db.flush()

    rows = list_ledger_changes(db, [other_entity.id], date(2026, 4, 1), date_from=date(2026, 4, 1))
    assert len(rows) == 1
    assert rows[0].company_name == other_entity.name
    multi_company_rows = list_ledger_changes(
        db, [other_entity.id - 1, other_entity.id], date(2026, 4, 1)
    )
    assert any(row.company_name == other_entity.name for row in multi_company_rows)
    assert (
        list_ledger_changes(db, [other_entity.id], date(2026, 4, 2), date_from=date(2026, 4, 2))
        == []
    )
    assert (
        list_ledger_changes(db, [other_entity.id], date(2026, 3, 31), date_from=date(2026, 3, 1))
        == []
    )
    assert list_ledger_changes(db, [other_entity.id - 1], date(2026, 4, 1)) == []


def test_deleted_voucher_uses_detection_time_not_source_alteration_time(
    db: Session, synced: S.Connection, connector: TallyConnector
) -> None:
    raw = _voucher_raw(db, "PMT-ANCHOR")
    entity_id = db.scalar(select(A.Entity.id))
    keys = connector.list_keys(connector.list_entities()[0])
    keys["voucher"].discard(raw.source_key)
    deleted = mark_deleted(db, synced.id, entity_id, keys)
    assert deleted == {"voucher:vouchers": 1}

    version = db.scalars(
        select(A.VoucherVersion).where(
            A.VoucherVersion.voucher_source_key == raw.source_key,
            A.VoucherVersion.is_deleted.is_(True),
        )
    ).one()
    assert version.source_altered_at is None
    assert version.source_alter_id is None
    assert version.deletion_detected_at == version.observed_at
    changes = list(
        db.scalars(
            select(A.VoucherLedgerChange).where(A.VoucherLedgerChange.version_id == version.id)
        )
    )
    assert changes
    assert {change.change_type for change in changes} == {"deleted"}
    rows = list_ledger_changes(db, [entity_id], version.deletion_detected_at.date())
    assert rows
    assert all(row.alteration_at == version.deletion_detected_at for row in rows)


def test_only_captured_versions_are_compared() -> None:
    first_captured = [_posting("rent", "10")]
    next_captured = [_posting("rent", "30")]
    changes = compare_postings(first_captured, next_captured)
    assert len(changes) == 1
    assert changes[0].change_type == "modified"
    assert changes[0].matching_basis == "unique_posting_context"
