"""Retain observed voucher versions and compare their ledger-posting snapshots.

This records snapshots LedgerBridge actually receives; it cannot reconstruct source
versions that were never returned by Tally.
"""

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import case, select
from sqlalchemy.orm import Session, aliased

from core.models import accounting as A  # noqa: N812
from core.models.source import RawRecord


@dataclass(frozen=True)
class PostingSnapshot:
    line_no: int
    ledger_id: int
    ledger_source_key: str
    ledger_name: str
    amount: Decimal
    amount_fc: Decimal | None
    currency_name: str | None
    exchange_rate: Decimal | None
    is_party_line: bool
    details: dict[str, Any]
    identity_hash: str
    content_hash: str


@dataclass(frozen=True)
class ChangeMatch:
    change_type: str
    previous_index: int | None
    new_index: int | None
    matching_basis: str


@dataclass(frozen=True)
class LedgerHistoryRow:
    company_name: str
    voucher_number: str
    alteration_at: datetime
    ledger_name: str
    previous_debit: Decimal | None
    new_debit: Decimal | None
    previous_credit: Decimal | None
    new_credit: Decimal | None
    change_type: str
    matching_basis: str


def _normalise(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _normalise(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        normalized = [_normalise(item) for item in value]
        return sorted(normalized, key=_json)
    return value


def _json(value: Any) -> str:
    return json.dumps(_normalise(value), ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def posting_snapshot(
    *,
    line_no: int,
    ledger_id: int,
    ledger_source_key: str,
    ledger_name: str,
    amount: Decimal,
    amount_fc: Decimal | None,
    currency_name: str | None,
    exchange_rate: Decimal | None,
    is_party_line: bool,
    bills: Iterable[dict[str, Any]] = (),
    cost_allocations: Iterable[dict[str, Any]] = (),
) -> PostingSnapshot:
    details = {
        "bills": list(bills),
        "cost_allocations": list(cost_allocations),
    }
    identity = {
        "ledger_source_key": ledger_source_key,
        "is_party_line": is_party_line,
        "currency_name": currency_name,
        "bill_identities": [
            {
                "party_id": bill.get("party_id"),
                "bill_type": bill.get("bill_type"),
                "bill_name": bill.get("bill_name"),
                "bill_date": bill.get("bill_date"),
            }
            for bill in details["bills"]
        ],
        "cost_centres": [
            allocation.get("cost_centre_id") for allocation in details["cost_allocations"]
        ],
    }
    content = {
        **identity,
        "amount": amount,
        "amount_fc": amount_fc,
        "exchange_rate": exchange_rate,
        "details": details,
    }
    return PostingSnapshot(
        line_no=line_no,
        ledger_id=ledger_id,
        ledger_source_key=ledger_source_key,
        ledger_name=ledger_name,
        amount=amount,
        amount_fc=amount_fc,
        currency_name=currency_name,
        exchange_rate=exchange_rate,
        is_party_line=is_party_line,
        details=_normalise(details),
        identity_hash=_hash(identity),
        content_hash=_hash(content),
    )


def compare_postings(previous: Sequence[Any], current: Sequence[Any]) -> list[ChangeMatch]:
    """Compare posting multisets without treating line order as a source identity.

    Identical content is paired first. A unique remaining identity-context pair is a
    probable modification; competing leftovers stay unpaired and are marked ambiguous.
    """
    old_left = set(range(len(previous)))
    new_left = set(range(len(current)))
    changes: list[ChangeMatch] = []

    old_content: dict[str, list[int]] = defaultdict(list)
    new_content: dict[str, list[int]] = defaultdict(list)
    for index, line in enumerate(previous):
        old_content[line.content_hash].append(index)
    for index, line in enumerate(current):
        new_content[line.content_hash].append(index)
    for content_hash in old_content.keys() & new_content.keys():
        old_indices = sorted(old_content[content_hash], key=lambda i: _line_order(previous[i]))
        new_indices = sorted(new_content[content_hash], key=lambda i: _line_order(current[i]))
        for old_index, new_index in zip(old_indices, new_indices, strict=False):
            old_left.discard(old_index)
            new_left.discard(new_index)

    old_identity: dict[str, list[int]] = defaultdict(list)
    new_identity: dict[str, list[int]] = defaultdict(list)
    for index in old_left:
        old_identity[previous[index].identity_hash].append(index)
    for index in new_left:
        new_identity[current[index].identity_hash].append(index)
    for identity_hash in old_identity.keys() & new_identity.keys():
        old_indices = old_identity[identity_hash]
        new_indices = new_identity[identity_hash]
        if len(old_indices) == len(new_indices) == 1:
            old_index, new_index = old_indices[0], new_indices[0]
            old_left.remove(old_index)
            new_left.remove(new_index)
            changes.append(ChangeMatch("modified", old_index, new_index, "unique_posting_context"))

    if old_left and new_left:
        changes.extend(
            ChangeMatch("ambiguous", index, None, "unmatched_counterparts")
            for index in sorted(old_left, key=lambda i: _line_order(previous[i]))
        )
        changes.extend(
            ChangeMatch("ambiguous", None, index, "unmatched_counterparts")
            for index in sorted(new_left, key=lambda i: _line_order(current[i]))
        )
    elif old_left:
        changes.extend(
            ChangeMatch("deleted", index, None, "only_previous_postings")
            for index in sorted(old_left, key=lambda i: _line_order(previous[i]))
        )
    elif new_left:
        changes.extend(
            ChangeMatch("added", None, index, "only_new_postings")
            for index in sorted(new_left, key=lambda i: _line_order(current[i]))
        )
    return changes


def _line_order(line: Any) -> tuple[int, int]:
    return (line.line_no, getattr(line, "id", 0) or 0)


def _insert_version(
    session: Session,
    *,
    entity_id: int,
    voucher_id: int,
    connection_id: int,
    voucher_source_key: str,
    company_name: str,
    voucher_number: str,
    capture_key: str,
    raw_record_id: int | None,
    payload_hash: str | None,
    source_alter_id: int | None,
    source_altered_at: datetime | None,
    observed_at: datetime,
    is_deleted: bool,
    deletion_detected_at: datetime | None,
    postings: Sequence[PostingSnapshot],
) -> A.VoucherVersion | None:
    existing = session.scalar(
        select(A.VoucherVersion).where(
            A.VoucherVersion.connection_id == connection_id,
            A.VoucherVersion.capture_key == capture_key,
        )
    )
    if existing is not None:
        return None

    previous_version = session.scalar(
        select(A.VoucherVersion)
        .where(
            A.VoucherVersion.connection_id == connection_id,
            A.VoucherVersion.entity_id == entity_id,
            A.VoucherVersion.voucher_source_key == voucher_source_key,
        )
        .order_by(A.VoucherVersion.id.desc())
        .limit(1)
    )
    version = A.VoucherVersion(
        entity_id=entity_id,
        voucher_id=voucher_id,
        connection_id=connection_id,
        voucher_source_key=voucher_source_key,
        company_name=company_name,
        voucher_number=voucher_number,
        capture_key=capture_key,
        raw_record_id=raw_record_id,
        payload_hash=payload_hash,
        source_alter_id=source_alter_id,
        source_altered_at=source_altered_at,
        observed_at=observed_at,
        is_deleted=is_deleted,
        deletion_detected_at=deletion_detected_at,
        previous_version_id=previous_version.id if previous_version else None,
    )
    session.add(version)
    session.flush()

    line_rows = [
        A.VoucherVersionLine(
            voucher_version_id=version.id,
            line_no=line.line_no,
            ledger_id=line.ledger_id,
            ledger_source_key=line.ledger_source_key,
            ledger_name=line.ledger_name,
            amount=line.amount,
            amount_fc=line.amount_fc,
            currency_name=line.currency_name,
            exchange_rate=line.exchange_rate,
            is_party_line=line.is_party_line,
            details=line.details,
            identity_hash=line.identity_hash,
            content_hash=line.content_hash,
        )
        for line in postings
    ]
    session.add_all(line_rows)
    session.flush()
    if previous_version is not None:
        previous_lines = list(
            session.scalars(
                select(A.VoucherVersionLine)
                .where(A.VoucherVersionLine.voucher_version_id == previous_version.id)
                .order_by(A.VoucherVersionLine.line_no, A.VoucherVersionLine.id)
            )
        )
        for change in compare_postings(previous_lines, line_rows):
            session.add(
                A.VoucherLedgerChange(
                    previous_version_id=previous_version.id,
                    version_id=version.id,
                    previous_line_id=(
                        previous_lines[change.previous_index].id
                        if change.previous_index is not None
                        else None
                    ),
                    new_line_id=(
                        line_rows[change.new_index].id if change.new_index is not None else None
                    ),
                    change_type=change.change_type,
                    matching_basis=change.matching_basis,
                )
            )
    return version


def capture_voucher_version(
    session: Session,
    *,
    entity_id: int,
    voucher_id: int,
    connection_id: int,
    voucher_source_key: str,
    company_name: str,
    voucher_number: str,
    raw_record_id: int,
    payload_hash: str,
    source_alter_id: int | None,
    source_altered_at: datetime | None,
    observed_at: datetime,
    postings: Sequence[PostingSnapshot],
) -> A.VoucherVersion | None:
    return _insert_version(
        session,
        entity_id=entity_id,
        voucher_id=voucher_id,
        connection_id=connection_id,
        voucher_source_key=voucher_source_key,
        company_name=company_name,
        voucher_number=voucher_number,
        capture_key=f"raw:{raw_record_id}",
        raw_record_id=raw_record_id,
        payload_hash=payload_hash,
        source_alter_id=source_alter_id,
        source_altered_at=source_altered_at,
        observed_at=observed_at,
        is_deleted=False,
        deletion_detected_at=None,
        postings=postings,
    )


def _canonical_postings(session: Session, voucher_id: int) -> list[PostingSnapshot]:
    rows = session.execute(
        select(A.VoucherLine, A.Ledger.source_key, A.Ledger.name)
        .join(A.Ledger, A.Ledger.id == A.VoucherLine.ledger_id)
        .where(A.VoucherLine.voucher_id == voucher_id)
        .order_by(A.VoucherLine.line_no, A.VoucherLine.id)
    ).all()
    line_ids = [line.id for line, _, _ in rows]
    bills: dict[int, list[dict[str, Any]]] = defaultdict(list)
    allocations: dict[int, list[dict[str, Any]]] = defaultdict(list)
    if line_ids:
        for row in session.execute(
            select(A.BillAllocation).where(A.BillAllocation.voucher_line_id.in_(line_ids))
        ).scalars():
            bills[row.voucher_line_id].append(
                {
                    "party_id": row.party_id,
                    "bill_type": row.bill_type,
                    "bill_name": row.bill_name,
                    "bill_date": row.bill_date,
                    "amount": row.amount,
                }
            )
        for row in session.execute(
            select(A.LineCostAllocation).where(A.LineCostAllocation.voucher_line_id.in_(line_ids))
        ).scalars():
            allocations[row.voucher_line_id].append(
                {"cost_centre_id": row.cost_centre_id, "amount": row.amount}
            )
    return [
        posting_snapshot(
            line_no=line.line_no,
            ledger_id=line.ledger_id,
            ledger_source_key=ledger_key,
            ledger_name=ledger_name,
            amount=line.amount,
            amount_fc=line.amount_fc,
            currency_name=line.currency_name,
            exchange_rate=line.exchange_rate,
            is_party_line=line.is_party_line,
            bills=bills[line.id],
            cost_allocations=allocations[line.id],
        )
        for line, ledger_key, ledger_name in rows
    ]


def capture_missing_baselines(
    session: Session, connection_id: int, entity_id: int, voucher_source_keys: set[str]
) -> None:
    if not voucher_source_keys:
        return
    entity = session.get_one(A.Entity, entity_id)
    vouchers = session.scalars(
        select(A.Voucher).where(
            A.Voucher.connection_id == connection_id,
            A.Voucher.entity_id == entity_id,
            A.Voucher.source_key.in_(voucher_source_keys),
            A.Voucher.is_deleted.is_(False),
        )
    ).all()
    for voucher in vouchers:
        has_history = session.scalar(
            select(A.VoucherVersion.id)
            .where(
                A.VoucherVersion.connection_id == connection_id,
                A.VoucherVersion.entity_id == entity_id,
                A.VoucherVersion.voucher_source_key == voucher.source_key,
            )
            .limit(1)
        )
        if has_history is not None:
            continue
        raw = session.get(RawRecord, voucher.raw_record_id) if voucher.raw_record_id else None
        raw_id = raw.id if raw else None
        capture_key = f"raw:{raw_id}" if raw_id is not None else f"baseline:{voucher.id}"
        _insert_version(
            session,
            entity_id=entity_id,
            voucher_id=voucher.id,
            connection_id=connection_id,
            voucher_source_key=voucher.source_key,
            company_name=entity.name,
            voucher_number=voucher.voucher_number,
            capture_key=capture_key,
            raw_record_id=raw_id,
            payload_hash=raw.payload_hash if raw else None,
            source_alter_id=voucher.source_alter_id,
            source_altered_at=voucher.source_altered_at,
            observed_at=raw.received_at if raw else voucher.updated_at,
            is_deleted=False,
            deletion_detected_at=None,
            postings=_canonical_postings(session, voucher.id),
        )


def capture_voucher_deletion(session: Session, voucher: A.Voucher, detected_at: datetime) -> None:
    entity = session.get_one(A.Entity, voucher.entity_id)
    raw = session.get(RawRecord, voucher.raw_record_id) if voucher.raw_record_id else None
    raw_id = raw.id if raw else None
    if not session.scalar(
        select(A.VoucherVersion.id)
        .where(
            A.VoucherVersion.connection_id == voucher.connection_id,
            A.VoucherVersion.entity_id == voucher.entity_id,
            A.VoucherVersion.voucher_source_key == voucher.source_key,
        )
        .limit(1)
    ):
        capture_missing_baselines(
            session, voucher.connection_id, voucher.entity_id, {voucher.source_key}
        )
    capture_key = (
        f"deleted:{raw_id}:{voucher.id}" if raw_id is not None else f"deleted:{voucher.id}"
    )
    _insert_version(
        session,
        entity_id=voucher.entity_id,
        voucher_id=voucher.id,
        connection_id=voucher.connection_id,
        voucher_source_key=voucher.source_key,
        company_name=entity.name,
        voucher_number=voucher.voucher_number,
        capture_key=capture_key,
        raw_record_id=raw_id,
        payload_hash=raw.payload_hash if raw else None,
        source_alter_id=None,
        source_altered_at=None,
        observed_at=detected_at,
        is_deleted=True,
        deletion_detected_at=detected_at,
        postings=(),
    )


def _debit(amount: Decimal | None) -> Decimal | None:
    return max(amount, Decimal(0)) if amount is not None else None


def _credit(amount: Decimal | None) -> Decimal | None:
    return -min(amount, Decimal(0)) if amount is not None else None


def list_ledger_changes(
    session: Session,
    entity_ids: Sequence[int],
    date_to: date,
    date_from: date = date(2026, 4, 1),
) -> list[LedgerHistoryRow]:
    """Return entity-scoped changes in the inclusive date window.

    Source alterations use Tally's timestamp; deleted vouchers use local detection time.
    Rows with no source alteration timestamp are omitted rather than dated by receipt time.
    """
    if date_to < date_from:
        raise ValueError("date_to must be on or after date_from")
    if not entity_ids:
        return []

    old_line = aliased(A.VoucherVersionLine)
    new_line = aliased(A.VoucherVersionLine)
    version = A.VoucherVersion
    event_at = case(
        (version.is_deleted.is_(True), version.deletion_detected_at),
        else_=version.source_altered_at,
    )
    start = datetime.combine(date_from, time.min)
    end = datetime.combine(date_to + timedelta(days=1), time.min)
    query = (
        select(A.VoucherLedgerChange, version, old_line, new_line, event_at)
        .join(version, version.id == A.VoucherLedgerChange.version_id)
        .outerjoin(old_line, old_line.id == A.VoucherLedgerChange.previous_line_id)
        .outerjoin(new_line, new_line.id == A.VoucherLedgerChange.new_line_id)
        .where(
            version.entity_id.in_(entity_ids),
            event_at.is_not(None),
            event_at >= start,
            event_at < end,
        )
        .order_by(event_at, version.company_name, version.voucher_number, A.VoucherLedgerChange.id)
    )
    rows: list[LedgerHistoryRow] = []
    for change, current, previous, new, altered_at in session.execute(query):
        rows.append(
            LedgerHistoryRow(
                company_name=current.company_name,
                voucher_number=current.voucher_number,
                alteration_at=altered_at,
                ledger_name=(new.ledger_name if new is not None else previous.ledger_name),
                previous_debit=_debit(previous.amount if previous is not None else None),
                new_debit=_debit(new.amount if new is not None else None),
                previous_credit=_credit(previous.amount if previous is not None else None),
                new_credit=_credit(new.amount if new is not None else None),
                change_type=change.change_type,
                matching_basis=change.matching_basis,
            )
        )
    return rows
