"""Counts fetched Tally objects against the canonical records stored for each company."""

from collections import Counter
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from connectors.base import Chunk, SourceEntity
from connectors.tally import envelopes
from connectors.tally.connector import TallyConnector
from core.models import accounting as A  # noqa: N812
from core.models.base import SourceTrackingMixin
from core.names import NameIndex


@dataclass(frozen=True)
class MasterCount:
    object_type: str
    source_count: int | None
    stored_count: int

    @property
    def difference(self) -> int | None:
        return None if self.source_count is None else self.source_count - self.stored_count


@dataclass(frozen=True)
class VoucherCount:
    month: date
    voucher_type: str
    source_count: int
    stored_count: int

    @property
    def difference(self) -> int:
        return self.source_count - self.stored_count


@dataclass(frozen=True)
class VoucherExclusions:
    cancelled: int
    optional: int
    non_accounting_type: int
    deleted: int


@dataclass(frozen=True)
class AuditCounts:
    masters: tuple[MasterCount, ...]
    vouchers: tuple[VoucherCount, ...]
    exclusions: VoucherExclusions


_MASTER_TABLES: dict[str, type[SourceTrackingMixin]] = {
    "currency": A.CurrencySource,
    "group": A.AccountGroup,
    "ledger": A.Ledger,
    "voucher_type": A.VoucherType,
    "unit": A.Unit,
    "stock_group": A.ItemGroup,
    "godown": A.Godown,
    "stock_item": A.Item,
    "cost_category": A.CostCategory,
    "cost_centre": A.CostCentre,
}


def audit_counts(
    session: Session,
    connection_id: int,
    entity_id: int,
    entity: SourceEntity,
    connector: TallyConnector,
    as_of: date,
    recorded_collection_ids: frozenset[str] | None = None,
) -> AuditCounts:
    """Compare the source's read-only counts with active canonical records.

    `recorded_collection_ids` is supplied only by fixture tests. It prevents an
    unrecorded collection (which the fixture transport answers as empty) from being
    mistaken for a confirmed source count of zero.
    """
    if entity.books_from is None:
        raise ValueError("The company has no books-from date; voucher counts are unavailable")
    if as_of < entity.books_from:
        raise ValueError("The audit end date precedes the company's books-from date")

    # Master types with a table of their own (a ledger's opening bills share its key).
    specs = [spec for spec in envelopes.MASTER_SPECS if spec.object_type in _MASTER_TABLES]
    source_masters = {
        spec.object_type: len(connector.chunk_keys(entity, Chunk(spec.object_type)))
        for spec in specs
    }
    masters = [
        MasterCount(
            "company",
            _recorded_count(
                1,
                envelopes.COMPANIES.collection_id,
                recorded_collection_ids,
            ),
            session.scalar(
                select(func.count())
                .select_from(A.EntitySource)
                .where(
                    A.EntitySource.connection_id == connection_id,
                    A.EntitySource.source_entity_key == entity.key,
                )
            )
            or 0,
        )
    ]
    for spec in specs:
        model = _MASTER_TABLES[spec.object_type]
        conditions = [model.entity_id == entity_id, model.is_deleted.is_(False)]
        if spec.object_type == "group":
            conditions.append(~model.source_key.like("primary:%"))
        stored_count = (
            session.scalar(select(func.count()).select_from(model).where(*conditions)) or 0
        )
        masters.append(
            MasterCount(
                spec.object_type,
                _recorded_count(
                    source_masters[spec.object_type],
                    spec.collection_id,
                    recorded_collection_ids,
                ),
                stored_count,
            )
        )

    source_vouchers = connector.voucher_counts(entity, entity.books_from, as_of)
    type_rows = session.execute(
        select(A.VoucherType.id, A.VoucherType.name, A.VoucherType.is_deleted).where(
            A.VoucherType.entity_id == entity_id
        )
    ).all()
    type_ids: dict[str, int] = {}
    type_index_values: list[tuple[str, str]] = []
    for type_id, name, is_deleted in type_rows:
        if name not in type_ids or not is_deleted:
            type_ids[name] = type_id
    type_index_values.extend((name, name) for name in type_ids)
    type_index = NameIndex.build(type_index_values)

    unmatched_names = sorted(
        {name for _, name in source_vouchers if not type_index.resolve(name).found}
    )
    unmatched_numbers = {name: number for number, name in enumerate(unmatched_names, start=1)}

    def source_type_label(name: str) -> str:
        found = type_index.resolve(name)
        if found.found:
            return f"voucher type {type_ids[found.value]}"
        return f"unmatched source type {unmatched_numbers[name]}"

    source_counts: Counter[tuple[date, str]] = Counter()
    for (month, name), count in source_vouchers.items():
        source_counts[(month, source_type_label(name))] += count

    stored_counts: Counter[tuple[date, str]] = Counter()
    rows = session.execute(
        select(
            A.Voucher.voucher_date,
            A.Voucher.voucher_type_id,
            func.count(),
        )
        .where(
            A.Voucher.entity_id == entity_id,
            A.Voucher.is_deleted.is_(False),
            A.Voucher.voucher_date >= entity.books_from,
            A.Voucher.voucher_date <= as_of,
        )
        .group_by(A.Voucher.voucher_date, A.Voucher.voucher_type_id)
    )
    type_name_by_id = {type_id: name for type_id, name, _ in type_rows}
    for voucher_date, type_id, count in rows:
        month = voucher_date.replace(day=1)
        name = type_name_by_id.get(type_id)
        label = source_type_label(name) if name is not None else f"unmatched stored type {type_id}"
        stored_counts[(month, label)] += count

    vouchers = tuple(
        VoucherCount(month, label, source_counts[(month, label)], stored_counts[(month, label)])
        for month, label in sorted(set(source_counts) | set(stored_counts))
    )
    exclusions = _voucher_exclusions(session, entity_id, entity.books_from, as_of)
    return AuditCounts(tuple(masters), vouchers, exclusions)


def _recorded_count(
    count: int, collection_id: str, recorded_collection_ids: frozenset[str] | None
) -> int | None:
    if recorded_collection_ids is not None and collection_id not in recorded_collection_ids:
        return None
    return count


def _voucher_exclusions(
    session: Session, entity_id: int, start: date, end: date
) -> VoucherExclusions:
    rows = session.execute(
        select(
            A.Voucher.is_cancelled,
            A.Voucher.is_optional,
            A.VoucherType.is_accounting,
            func.count(),
        )
        .join(A.VoucherType, A.VoucherType.id == A.Voucher.voucher_type_id)
        .where(
            A.Voucher.entity_id == entity_id,
            A.Voucher.is_deleted.is_(False),
            A.Voucher.voucher_date >= start,
            A.Voucher.voucher_date <= end,
        )
        .group_by(A.Voucher.is_cancelled, A.Voucher.is_optional, A.VoucherType.is_accounting)
    )
    cancelled = optional = non_accounting = 0
    for is_cancelled, is_optional, is_accounting, count in rows:
        if is_cancelled:
            cancelled += count
        if is_optional:
            optional += count
        if is_accounting is False:
            non_accounting += count
    deleted = (
        session.scalar(
            select(func.count())
            .select_from(A.Voucher)
            .where(
                A.Voucher.entity_id == entity_id,
                A.Voucher.is_deleted.is_(True),
                A.Voucher.voucher_date >= start,
                A.Voucher.voucher_date <= end,
            )
        )
        or 0
    )
    return VoucherExclusions(cancelled, optional, non_accounting, deleted)
