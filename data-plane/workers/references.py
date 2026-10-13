"""Why references by name don't resolve: `transform explain` (source-independent; ADR-027).

For each kind of reference that failed (a ledger's group, a voucher's ledgers, cost centres,
stock items, voucher type), it re-reads the failed raw records, collects the names they
refer to (in memory only), and says for each name, **without printing names or values**:

- whether it resolves now (exactly, by alias, or after normalisation, with the kinds of
  difference: spaces, case, XML entities, Unicode), or matches several targets;
- otherwise whether a close match exists (look-alike characters, punctuation, other small
  differences); whether it is one of the source's own predefined names (e.g. a Tally
  reserved group); whether the referenced object is in the stored raw records at all, and
  if so whether it failed to transform;
- with `check_source`, whether the source lists it now, and for every master type how many
  objects the source lists against how many are stored (are our requests complete?).

Output is counts and kinds only, safe to share.
"""

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from connectors.base import Connector, SourceEntity, SourceRecord
from core.canonical import (
    CanonicalCostCentre,
    CanonicalGroup,
    CanonicalItem,
    CanonicalLedger,
    CanonicalVoucher,
    CanonicalVoucherType,
)
from core.models import Connection
from core.models import accounting as A  # noqa: N812
from core.models.source import RawRecord
from core.names import NameIndex, close_match, differences, normalise
from core.transform import ALIASED, ALIASES, BATCH

Progress = Callable[[str], None]


@dataclass(frozen=True)
class Relation:
    """One kind of reference: records of `source_type` naming objects of `target_type`."""

    label: str  # "voucher -> ledger"
    source_type: str
    target_type: str  # the raw object type of the target
    target_kind: type  # the canonical kind of the target
    target_model: type
    names: Callable[[Any], Iterable[str]]  # referenced names in a canonical source record


def _group_of(r: Any) -> list[str]:
    return [r.group_name] if isinstance(r, CanonicalLedger) else []


def _type_of(r: Any) -> list[str]:
    return [r.voucher_type_name] if isinstance(r, CanonicalVoucher) else []


def _ledgers_of(r: Any) -> list[str]:
    return [line.ledger_name for line in r.lines] if isinstance(r, CanonicalVoucher) else []


def _centres_of(r: Any) -> list[str]:
    if not isinstance(r, CanonicalVoucher):
        return []
    return [name for line in r.lines for name, _ in line.cost_allocations]


def _items_of(r: Any) -> list[str]:
    return [inv.item_name for inv in r.inventory] if isinstance(r, CanonicalVoucher) else []


RELATIONS = (
    Relation("ledger -> group", "ledger", "group", CanonicalGroup, A.AccountGroup, _group_of),
    Relation(
        "voucher -> voucher type", "voucher", "voucher_type", CanonicalVoucherType,
        A.VoucherType, _type_of,
    ),
    Relation("voucher -> ledger", "voucher", "ledger", CanonicalLedger, A.Ledger, _ledgers_of),
    Relation(
        "voucher -> cost centre", "voucher", "cost_centre", CanonicalCostCentre, A.CostCentre,
        _centres_of,
    ),
    Relation("voucher -> stock item", "voucher", "stock_item", CanonicalItem, A.Item, _items_of),
)  # fmt: skip


@dataclass
class RelationReport:
    relation: Relation
    records: int = 0  # failed records with references of this kind
    exact: int = 0  # names that resolve exactly (not the cause, or fixed since)
    names: Counter[str] = field(default_factory=Counter)  # outcome -> distinct names
    records_by: Counter[str] = field(default_factory=Counter)  # outcome -> records
    kinds: Counter[str] = field(default_factory=Counter)  # kind of difference -> names
    # Of the names not found: whether the source lists them now (check_source) -> names.
    source: Counter[str] = field(default_factory=Counter)

    def add(self, outcome: str, records: int, kinds: Iterable[str] = ()) -> None:
        self.names[outcome] += 1
        self.records_by[outcome] += records
        for kind in kinds:
            self.kinds[kind] += 1


@dataclass
class EntityExplanation:
    label: str
    relations: list[RelationReport] = field(default_factory=list)
    completeness: dict[str, tuple[int, int, int]] = field(default_factory=dict)
    # object type -> (listed by the source now, stored, listed but not stored)


def _source_record(row: Any, entity_key: str) -> SourceRecord:
    return SourceRecord(
        source_entity_key=entity_key,
        object_type=row.object_type,
        source_key=row.source_key,
        source_alter_id=row.source_alter_id,
        payload_format=row.payload_format,
        payload=row.payload,
    )


def _map(connector: Connector, record: SourceRecord) -> list[Any]:
    try:
        return connector.to_canonical(record)
    except Exception:  # noqa: BLE001 - an unmappable record refers to nothing we can read
        return []


def _raw(
    session: Session, connection_id: int, entity_key: str, where: Iterable[Any]
) -> Iterable[Any]:
    """Raw records in batches by id (payloads are large)."""
    last = 0
    while True:
        rows = session.execute(
            select(
                RawRecord.id,
                RawRecord.object_type,
                RawRecord.source_key,
                RawRecord.source_alter_id,
                RawRecord.payload_format,
                RawRecord.payload,
                RawRecord.process_status,
            )
            .where(
                RawRecord.connection_id == connection_id,
                RawRecord.source_entity_key == entity_key,
                RawRecord.id > last,
                *where,
            )
            .order_by(RawRecord.id)
            .limit(BATCH)
        ).all()
        if not rows:
            return
        last = rows[-1].id
        yield from rows


def _stored_targets(
    session: Session, connector: Connector, connection_id: int, entity_key: str, relation: Relation
) -> dict[str, str]:
    """Names (and aliases) of every stored raw record of the target type, latest version
    first: name -> its process status."""
    types = ("group", "ledger") if relation.target_type == "group" else (relation.target_type,)
    latest: dict[str, Any] = {}
    for row in _raw(session, connection_id, entity_key, [RawRecord.object_type.in_(types)]):
        latest[(row.object_type, row.source_key)] = row
    statuses: dict[str, str] = {}
    for row in latest.values():
        for record in _map(connector, _source_record(row, entity_key)):
            if isinstance(record, relation.target_kind):
                status = (
                    row.process_status if row.object_type == relation.target_type else "processed"
                )
                for name in (record.name, *getattr(record, "aliases", ())):
                    statuses.setdefault(name, status)
    return statuses


def _index(session: Session, model: type, entity_id: int | None) -> NameIndex:
    """The transformed targets, as the transform resolves them."""
    index = NameIndex()
    if entity_id is None:
        return index
    for name, extra in session.execute(
        select(model.name, model.extra).where(model.entity_id == entity_id)
    ):
        index.add(name, name)
        if model in ALIASED:
            for alias in (extra or {}).get(ALIASES) or []:
                index.add_alias(alias, name)
    return index


def explain_entity(
    session: Session,
    connection: Connection,
    connector: Connector,
    entity_key: str,
    entity_id: int | None,
    label: str,
    progress: Progress,
    source_entity: SourceEntity | None = None,
) -> EntityExplanation:
    out = EntityExplanation(label)
    # Referenced names of failed records, per relation (names stay in memory only).
    referenced: dict[str, Counter[str]] = defaultdict(Counter)
    records_seen: Counter[str] = Counter()
    failed = [RawRecord.process_status == "failed", RawRecord.process_error.like("%refers to%")]
    seen = 0
    for row in _raw(session, connection.id, entity_key, failed):
        seen += 1
        if seen % 10_000 == 0:
            progress(f"{label}: read {seen:,} failed records")
        records = _map(connector, _source_record(row, entity_key))
        for relation in RELATIONS:
            if relation.source_type != row.object_type:
                continue
            names = {n for record in records for n in relation.names(record) if n}
            if names:
                records_seen[relation.label] += 1
            for name in names:
                referenced[relation.label][name] += 1
    reserved = {
        kind: {normalise(n) for n in names}
        for kind, names in (getattr(connector, "reserved_names", None) or {}).items()
    }
    source_names: dict[str, set[str]] = {}
    for relation in RELATIONS:
        names = referenced.get(relation.label)
        if not names:
            continue
        report = RelationReport(relation)
        index = _index(session, relation.target_model, entity_id)
        stored = _stored_targets(session, connector, connection.id, entity_key, relation)
        stored_index = NameIndex.build((n, n) for n in stored)
        if source_entity is not None and hasattr(connector, "master_names"):
            if relation.target_type not in source_names:
                try:
                    source_names[relation.target_type] = connector.master_names(
                        source_entity, relation.target_type
                    )
                except Exception:  # noqa: BLE001 - reported as unknown
                    source_names[relation.target_type] = set()
        for name, records in names.items():
            found = index.resolve(name)
            if found.found:
                if found.how == "exact":
                    report.exact += 1
                elif found.how == "alias":
                    report.add("resolves now by alias", records)
                else:
                    report.add(
                        "resolves now after normalisation", records, differences(name, found.value)
                    )
                continue
            if found.ambiguous:
                report.add("matches several targets after normalisation (ambiguous)", records)
                continue
            in_raw = stored_index.resolve(name)
            if in_raw.found:
                status = stored[in_raw.value]
                report.add(f"stored, but the referenced record is {status}", records)
                continue
            if normalise(name) in reserved.get(relation.target_type, set()):
                report.add(
                    "a predefined name of the source (e.g. a reserved group), not stored", records
                )
            else:
                candidate, kinds = close_match(name, [*index.names(), *stored])
                if candidate is not None:
                    report.add("not found; a close match exists", records, kinds)
                else:
                    report.add("not found; no close match", records)
            if relation.target_type in source_names:
                listed = NameIndex.build((n, n) for n in source_names[relation.target_type])
                where = (
                    "listed by the source now, but not stored (not fetched)"
                    if listed.resolve(name).found
                    else "not listed by the source under this name"
                )
                report.source[where] += 1
        report.records = records_seen[relation.label]
        if report.names:
            out.relations.append(report)
    return out


def completeness(
    session: Session, connection: Connection, connector: Connector, entity: SourceEntity
) -> dict[str, tuple[int, int, int]]:
    """Per master type: objects the source lists now, objects stored, listed but not stored
    (by key). Needs the source; read-only."""
    out = {}
    for object_type in getattr(connector, "master_types", ()):
        listed = connector.master_keys(entity, object_type)  # type: ignore[attr-defined]
        stored = set(
            session.scalars(
                select(RawRecord.source_key)
                .where(
                    RawRecord.connection_id == connection.id,
                    RawRecord.source_entity_key == entity.key,
                    RawRecord.object_type == object_type,
                )
                .distinct()
            )
        )
        out[object_type] = (len(listed), len(stored), len(listed - stored))
    return out


def failed_reference_counts(session: Session, connection_id: int) -> dict[str, int]:
    """Failed raw records per entity key whose error is an unresolved reference."""
    return dict(
        session.execute(
            select(RawRecord.source_entity_key, func.count())
            .where(
                RawRecord.connection_id == connection_id,
                RawRecord.process_status == "failed",
                RawRecord.process_error.like("%refers to%"),
            )
            .group_by(RawRecord.source_entity_key)
        ).all()
    )


def lines(explanation: EntityExplanation) -> list[str]:
    """Plain-language output: counts and kinds only."""
    out = []
    if not explanation.relations and not explanation.completeness:
        return [f"{explanation.label}: no unresolved references"]
    for report in explanation.relations:
        out.append(
            f"{explanation.label}: {report.relation.label}: {report.records:,} failed records "
            f"refer to {sum(report.names.values()):,} names that don't resolve exactly"
            + (f" (and {report.exact:,} that do)" if report.exact else "")
        )
        for outcome, count in report.names.most_common():
            records = report.records_by[outcome]
            suffix = f" ({records:,} records)" if records else ""
            out.append(f"    {outcome}: {count:,} names{suffix}")
        if report.kinds:
            listed = ", ".join(f"{kind} {n}" for kind, n in report.kinds.most_common())
            out.append(f"    kinds of difference: {listed}")
        for outcome, count in report.source.most_common():
            out.append(f"    of the names not found, {outcome}: {count:,}")
    for object_type, (listed, stored, missing) in explanation.completeness.items():
        out.append(
            f"{explanation.label}: {object_type}: the source lists {listed:,}, stored {stored:,}, "
            f"listed but not stored {missing:,}"
        )
    return out
