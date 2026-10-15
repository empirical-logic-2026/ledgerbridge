"""Raw records → canonical tables (schema.md Section 8). Source-independent.

- Pending raw records are processed per entity, object type by object type in the
  connector's order, in batches read by id, so even hundreds of thousands of records never
  sit in memory at once. `progress` receives a line every PROGRESS_EVERY records.
- Every canonical row is upserted on (connection_id, source_key): a record delivered twice
  (e.g. in two overlapping month requests) updates the same row and never duplicates it.
- A voucher's child rows (lines, bills, cost allocations, dimensions, inventory, tax) are
  deleted and re-inserted in the same transaction as the voucher header (rule 7).
- Group "hints" (nature, standard account, ledger kind, party type) are inherited down the
  group tree, which is rebuilt from the latest raw group records on every run.
- **One bad record never fails the others** (ADR-025): every row is fitted to its columns
  first (core/fit.py: values that don't fit are kept in full in `extra` and reported as a
  warning); a batch the database still rejects is written again record by record, so only
  the record at fault fails.
- Fields the mapping doesn't use (e.g. Tally UDFs) go to each row's `extra` and are counted
  in the field catalogue (`source_fields`); promoted fields become dimension values on the
  voucher's lines.
- `retry_failed` re-transforms records that failed before, with the current code; `rebuild`
  re-transforms every object of the entity (processed, failed and pending) from its latest
  raw record. Only the latest raw record of an object is ever queued again: an older
  version must never overwrite a newer one (older failed versions become `skipped`). Rows
  soft-deleted because their object was deleted in the source stay deleted.
- References by name (a ledger's group, a voucher's ledgers, ...) resolve by the rules of
  core/names.py (ADR-027): exact, then alias, then normalised, each only when exactly one
  target fits; normalised and alias matches are recorded as warnings (kinds only).
- Voucher types inherit their standard type, base type and whether they post to the books
  from their parent types; lines of vouchers whose type doesn't post to the books (e.g.
  orders, memorandum) are not effective, like cancelled and optional vouchers.
- Errors are recorded per raw record as type + field and column names; never values.
"""

import hashlib
import logging
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.orm import Session

from connectors.base import Connector, SourceRecord
from core.canonical import (
    NO_STANDARD_ACCOUNT,
    CanonicalCompany,
    CanonicalCostCentre,
    CanonicalGodown,
    CanonicalGroup,
    CanonicalItem,
    CanonicalItemGroup,
    CanonicalLedger,
    CanonicalRecord,
    CanonicalUnit,
    CanonicalVoucher,
    CanonicalVoucherType,
)
from core.errors import short_error
from core.fit import PLACEHOLDER, UNFIT, UnfitValueError, fitter, merge_extra
from core.models import accounting as A  # noqa: N812 - short alias for many models
from core.models.base import utcnow
from core.models.source import RawRecord
from core.names import ALIAS, NORMALISED, NameIndex

logger = logging.getLogger(__name__)

BATCH = 500
PROGRESS_EVERY = 10_000  # records between progress lines

# Canonical tables fed from each record kind, for deletion handling.
MODELS_BY_KIND: dict[type, tuple[type, ...]] = {
    CanonicalGroup: (A.AccountGroup,),
    CanonicalLedger: (A.Ledger, A.Party),
    CanonicalVoucherType: (A.VoucherType,),
    CanonicalUnit: (A.Unit,),
    CanonicalItemGroup: (A.ItemGroup,),
    CanonicalGodown: (A.Godown,),
    CanonicalItem: (A.Item,),
    CanonicalCostCentre: (A.CostCentre,),
    CanonicalVoucher: (A.Voucher,),
}

Progress = Callable[[str], None]
EntityLabel = Callable[[str, int | None], str]  # (source entity key, entity id) -> label


class TransformError(ValueError):
    """A record can't be written (e.g. it refers to a master that doesn't exist)."""


@dataclass
class TransformResult:
    processed: int = 0
    failed: int = 0
    retried: int = 0  # records queued again by retry_failed or rebuild
    by_object_type: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    failed_by_object_type: Counter[str] = field(default_factory=Counter)
    entity_ids: set[int] = field(default_factory=set)
    unmapped_ledgers: dict[int, list[str]] = field(default_factory=dict)  # entity_id -> names
    warnings: list[str] = field(default_factory=list)  # "<ledger name>: <assumption made>"
    # Values kept aside because they didn't fit their column: "<kind>: <table.column>; ..."
    # -> count. Kinds and column names only, never values (ADR-025).
    data_warnings: Counter[str] = field(default_factory=Counter)


@dataclass
class _Raw:
    row: RawRecord
    records: list[CanonicalRecord]
    warnings: list[str] = field(default_factory=list)


def _slug(name: str) -> str:
    return (re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_") or "ENTITY")[:28]


# --- field catalogue (ADR-025) ------------------------------------------------------------

_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")
_DATE = re.compile(r"^\d{8}$")


def infer_type(values: Iterable[Any]) -> str:
    """text / number / date / flag / mixed, from a field's values (strings)."""
    kinds = set()
    for value in values:
        text = str(value).strip()
        if text in ("Yes", "No"):
            kinds.add("flag")
        elif _DATE.match(text) and _valid_date(text):
            kinds.add("date")
        elif _NUMBER.match(text.replace(",", "")):
            kinds.add("number")
        else:
            kinds.add("text")
    if not kinds:
        return "text"
    return kinds.pop() if len(kinds) == 1 else "mixed"


def _valid_date(text: str) -> bool:
    try:
        datetime.strptime(text, "%Y%m%d")
    except ValueError:
        return False
    return True


def field_prefix(path: str) -> str | None:
    """'UDF:REFNO.LIST/UDF:REFNO' -> 'UDF' (the first prefixed name in the path)."""
    for part in path.split("/"):
        if ":" in part:
            return part.split(":", 1)[0]
    return None


def _fields(extra: dict[str, Any] | None) -> dict[str, list[Any]]:
    """Catalogued fields of a row's extra: everything but values kept aside."""
    out = {}
    for path, value in (extra or {}).items():
        if path.startswith("_"):  # values kept aside, aliases: not source fields
            continue
        out[path] = value if isinstance(value, list) else [value]
    return out


class _Catalogue:
    """Counts fields in `extra` per (entity, object type, path); written with each batch."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.reset()

    def reset(self) -> None:
        self.delta: Counter[tuple[int, str, str]] = Counter()
        self.types: dict[tuple[int, str, str], str] = {}

    def record(
        self,
        entity_id: int,
        object_type: str,
        old: dict[str, Any] | None,
        new: dict[str, Any] | None,
    ) -> None:
        before, after = _fields(old), _fields(new)
        for path in before.keys() - after.keys():
            self.delta[(entity_id, object_type, path[:255])] -= 1
        for path, values in after.items():
            key = (entity_id, object_type, path[:255])
            if path not in before:
                self.delta[key] += 1
            kind = infer_type(values)
            seen = self.types.get(key)
            self.types[key] = kind if seen in (None, kind) else "mixed"

    def flush(self) -> None:
        keys = set(self.delta) | set(self.types)
        if not keys:
            return
        now = utcnow()
        existing = {
            (row.entity_id, row.object_type, row.field_path): row
            for row in self.session.scalars(
                select(A.SourceField).where(
                    A.SourceField.entity_id.in_({k[0] for k in keys}),
                    A.SourceField.field_path.in_({k[2] for k in keys}),
                )
            )
        }
        for key in keys:
            entity_id, object_type, path = key
            kind = self.types.get(key)
            row = existing.get(key)
            if row is None:
                self.session.add(
                    A.SourceField(
                        entity_id=entity_id,
                        object_type=object_type,
                        field_path=path,
                        prefix=field_prefix(path),
                        inferred_type=kind or "text",
                        record_count=max(self.delta[key], 0),
                        first_seen_at=now,
                        last_seen_at=now,
                    )
                )
                continue
            row.record_count = max(row.record_count + self.delta[key], 0)
            if kind is not None:
                row.inferred_type = kind if row.inferred_type == kind else "mixed"
                row.last_seen_at = now
        self.reset()


class _Upserter:
    """Bulk upsert on (connection_id, source_key); returns source_key -> id. With
    `catalogue`, the rows' `extra` fields are counted (old values of updated rows first)."""

    def __init__(
        self, session: Session, connection_id: int, origin: str, catalogue: _Catalogue
    ) -> None:
        self.session = session
        self.connection_id = connection_id
        self.origin = origin
        self.catalogue = catalogue

    def __call__(
        self, model: type, rows: list[dict[str, Any]], catalogue_as: str | None = None
    ) -> dict[str, int]:
        if not rows:
            return {}
        # The same key twice in one batch (overlapping deliveries): the last one wins.
        by_key = {row["source_key"]: row for row in rows}
        keys = list(by_key)
        now = utcnow()
        existing = self.ids(model, keys)
        old_extra: dict[int, Any] = {}
        if catalogue_as and existing:
            old_extra = dict(
                self.session.execute(
                    select(model.id, model.extra).where(model.id.in_(list(existing.values())))
                ).all()
            )
        new, changed = [], []
        for key, row in by_key.items():
            row = {
                **row,
                "connection_id": self.connection_id,
                "origin": self.origin,
                "is_deleted": False,
                "updated_at": now,
            }
            if catalogue_as:
                self.catalogue.record(
                    row["entity_id"],
                    catalogue_as,
                    old_extra.get(existing.get(key, -1)),
                    row.get("extra"),
                )
            if key in existing:
                changed.append({**row, "id": existing[key]})
            else:
                new.append({**row, "created_at": now})
        if new:
            self.session.execute(insert(model), new)
        if changed:
            self.session.execute(update(model), changed)
        return self.ids(model, keys)

    def ids(self, model: type, keys: Sequence[str]) -> dict[str, int]:
        found: dict[str, int] = {}
        for start in range(0, len(keys), BATCH):
            chunk = keys[start : start + BATCH]
            found.update(
                self.session.execute(
                    select(model.source_key, model.id).where(
                        model.connection_id == self.connection_id, model.source_key.in_(chunk)
                    )
                ).all()
            )
        return found


@dataclass
class _GroupInfo:
    group: CanonicalGroup
    nature: str | None = None
    standard_code: str | None = None
    ledger_kind: str | None = None
    party_type: str | None = None


class _GroupTree:
    """The entity's group tree with hints inherited from the nearest ancestor. Parents and
    lookups resolve by the rules of core/names.py (exact, alias, normalised)."""

    def __init__(self, groups: Iterable[CanonicalGroup]) -> None:
        self.by_name = {g.name: _GroupInfo(g) for g in groups}
        self.index = NameIndex.build(
            ((name, name) for name in self.by_name),
            ((alias, g.group.name) for g in self.by_name.values() for alias in g.group.aliases),
        )
        for info in self.by_name.values():
            info.nature = self._inherit(info.group.name, "nature")
            code = self._inherit(info.group.name, "standard_account_code")
            info.standard_code = None if code == NO_STANDARD_ACCOUNT else code
            info.ledger_kind = self._inherit(info.group.name, "ledger_kind")
            info.party_type = self._inherit(info.group.name, "party_type")

    def _inherit(self, name: str | None, attribute: str) -> Any:
        seen: set[str] = set()
        while name and name not in seen:
            seen.add(name)
            info = self.get(name)
            if info is None:
                return None
            value = getattr(info.group, attribute)
            if value is not None:
                return value
            name = info.group.parent_name
        return None

    def get(self, name: str) -> _GroupInfo | None:
        found = self.index.get(name)
        return self.by_name.get(found) if found is not None else None


@dataclass
class _TypeInfo:
    base_type: str
    is_accounting: bool
    standard_type: str | None
    moves_stock: bool


class _TypeTree:
    """Voucher types with their standard type, base type and whether they post to the books,
    inherited from the nearest ancestor that has them (a type under a custom type)."""

    def __init__(self, types: Iterable[CanonicalVoucherType]) -> None:
        self.by_name = {t.name: t for t in types}
        self.index = NameIndex.build((name, name) for name in self.by_name)

    def _inherit(self, record: CanonicalVoucherType, attribute: str) -> Any:
        seen: set[str] = set()
        current: CanonicalVoucherType | None = record
        while current is not None and current.name not in seen:
            seen.add(current.name)
            value = getattr(current, attribute)
            if value is not None:
                return value
            parent = self.index.get(current.parent_name)
            current = self.by_name.get(parent) if parent is not None else None
        return None

    def info(self, record: CanonicalVoucherType) -> _TypeInfo:
        base = self._inherit(record, "base_type")
        accounting = self._inherit(record, "is_accounting")
        stock = self._inherit(record, "moves_stock")
        return _TypeInfo(
            base_type=base or "other",
            is_accounting=True if accounting is None else bool(accounting),
            standard_type=self._inherit(record, "standard_type"),
            moves_stock=True if stock is None else bool(stock),
        )


def _fit(item: _Raw, model: type, row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The row fitted to its columns, and the values kept aside (column -> full value).
    Raises UnfitValueError for a required value that can't be stored."""
    fitted = fitter(model).fit(row)
    item.warnings.extend(fitted.warnings)
    return fitted.row, fitted.unfit


def _with_extra(row: dict[str, Any], extra: Any, unfit: dict[str, Any]) -> dict[str, Any]:
    return {**row, "extra": merge_extra(dict(extra) if extra else None, unfit)}


def _dimension_code(entity_id: int, value: str) -> str:
    code = f"e{entity_id}:{value}"
    if len(code) <= 64:
        return code
    return f"e{entity_id}:h{hashlib.sha256(value.encode('utf-8')).hexdigest()[:40]}"


class Transformer:
    def __init__(
        self,
        session: Session,
        connection_id: int,
        connector: Connector,
        origin: str = "live",
        progress: Progress | None = None,
        label: EntityLabel | None = None,
    ) -> None:
        self.session = session
        self.connection_id = connection_id
        self.connector = connector
        self.catalogue = _Catalogue(session)
        self.upsert = _Upserter(session, connection_id, origin, self.catalogue)
        self.order = {t: i for i, t in enumerate(connector.object_types)}
        self.standard_ids = dict(
            session.execute(select(A.StandardAccount.code, A.StandardAccount.id)).all()
        )
        self.progress = progress
        self.label = label or (lambda key, entity_id: f"entity {entity_id}")

    # --- driver -----------------------------------------------------------------------

    def run(
        self,
        entity_keys: Iterable[str] | None = None,
        retry_failed: bool = False,
        rebuild: bool = False,
    ) -> TransformResult:
        """Transforms the pending raw records of the given entities (default: all of the
        connection's); with retry_failed also those that failed before; with rebuild every
        object again (see the module docstring)."""
        result = TransformResult()
        keys = list(entity_keys) if entity_keys is not None else None
        deleted: dict[type, list[int]] = {}
        if rebuild:
            deleted = self._deleted_rows(keys)
            result.retried = self._requeue(keys, ("processed", "failed", "skipped", "pending"))
        elif retry_failed:
            result.retried = self._requeue(keys, ("failed",))
        query = select(RawRecord.source_entity_key).where(
            RawRecord.connection_id == self.connection_id, RawRecord.process_status == "pending"
        )
        if keys is not None:
            query = query.where(RawRecord.source_entity_key.in_(keys))
        for entity_key in sorted(set(self.session.scalars(query.distinct()))):
            self._run_entity(entity_key, result)
        self._keep_deleted(deleted)
        return result

    def _scope(self, query: Any, keys: list[str] | None) -> Any:
        query = query.where(RawRecord.connection_id == self.connection_id)
        return query.where(RawRecord.source_entity_key.in_(keys)) if keys is not None else query

    def _requeue(self, keys: list[str] | None, statuses: tuple[str, ...]) -> int:
        """Marks the latest raw record of each object pending if its status is one of
        `statuses`. Older versions that failed are marked skipped: superseded, they must
        never be applied after a newer version. Returns how many were queued."""
        latest = list(
            self.session.scalars(
                self._scope(select(func.max(RawRecord.id)), keys).group_by(
                    RawRecord.object_type, RawRecord.source_key
                )
            )
        )
        queued = 0
        for start in range(0, len(latest), 5_000):
            queued += (
                self.session.execute(
                    update(RawRecord)
                    .where(
                        RawRecord.id.in_(latest[start : start + 5_000]),
                        RawRecord.process_status.in_(statuses),
                    )
                    .values(process_status="pending", process_error=None, process_warning=None)
                    .execution_options(synchronize_session=False)
                ).rowcount
                or 0
            )
            self.session.commit()
        # Every latest failed record is pending now: those still failed are older versions.
        self.session.execute(
            self._scope(update(RawRecord), keys)
            .where(RawRecord.process_status == "failed")
            .values(process_status="skipped", process_error="superseded by a newer version")
            .execution_options(synchronize_session=False)
        )
        self.session.commit()
        return queued

    def _deleted_rows(self, keys: list[str] | None) -> dict[type, list[int]]:
        """Rows soft-deleted because their object was deleted in the source (to keep them
        deleted through a rebuild: upserts mark rows as existing)."""
        from core.models.accounting import EntitySource

        entities = select(EntitySource.entity_id).where(
            EntitySource.connection_id == self.connection_id
        )
        if keys is not None:
            entities = entities.where(EntitySource.source_entity_key.in_(keys))
        models = dict.fromkeys(m for ms in MODELS_BY_KIND.values() for m in ms)
        return {
            model: list(
                self.session.scalars(
                    select(model.id).where(
                        model.connection_id == self.connection_id,
                        model.entity_id.in_(entities),
                        model.is_deleted.is_(True),
                    )
                )
            )
            for model in models
        }

    def _keep_deleted(self, deleted: dict[type, list[int]]) -> None:
        now = utcnow()
        for model, ids in deleted.items():
            for start in range(0, len(ids), 5_000):
                chunk = ids[start : start + 5_000]
                self.session.execute(
                    update(model).where(model.id.in_(chunk)).values(is_deleted=True, updated_at=now)
                )
                if model is A.Voucher:
                    self.session.execute(
                        update(A.VoucherLine)
                        .where(A.VoucherLine.voucher_id.in_(chunk))
                        .values(is_effective=False, updated_at=now)
                    )
        self.session.commit()

    def _say(self, message: str) -> None:
        if self.progress is not None:
            self.progress(message)

    def _pending_ids(self, entity_key: str) -> dict[str, list[int]]:
        """Pending raw record ids per object type, in transform order."""
        rows = self.session.execute(
            select(RawRecord.object_type, RawRecord.id)
            .where(
                RawRecord.connection_id == self.connection_id,
                RawRecord.source_entity_key == entity_key,
                RawRecord.process_status == "pending",
            )
            .order_by(RawRecord.id)
        ).all()
        by_type: dict[str, list[int]] = defaultdict(list)
        for object_type, row_id in rows:
            by_type[object_type].append(row_id)
        return dict(
            sorted(by_type.items(), key=lambda kv: (self.order.get(kv[0], len(self.order)), kv[0]))
        )

    def _load(self, ids: Sequence[int]) -> list[RawRecord]:
        rows = self.session.scalars(select(RawRecord).where(RawRecord.id.in_(list(ids)))).all()
        return sorted(rows, key=lambda r: r.id)

    def _map(self, rows: Iterable[RawRecord], result: TransformResult) -> list[_Raw]:
        mapped = []
        for row in rows:
            try:
                mapped.append(_Raw(row, self.connector.to_canonical(_source_record(row))))
            except Exception as exc:  # noqa: BLE001 - recorded per record, run continues
                self._fail(row, exc, result)
        return mapped

    def _fail(self, row: RawRecord, exc: Exception, result: TransformResult) -> None:
        row.process_status = "failed"
        row.process_error = short_error(exc)
        row.process_warning = None
        result.failed += 1
        result.failed_by_object_type[row.object_type] += 1

    def _done(self, items: Iterable[_Raw], result: TransformResult) -> None:
        for item in items:
            item.row.process_status = "processed"
            item.row.process_error = None
            warnings = list(dict.fromkeys(item.warnings))
            item.row.process_warning = "; ".join(warnings)[:2000] if warnings else None
            result.data_warnings.update(warnings)
            result.processed += 1
            result.by_object_type[item.row.object_type] += 1

    def _run_entity(self, entity_key: str, result: TransformResult) -> None:
        pending = self._pending_ids(entity_key)
        # The connector's first object type is the entity's own record (e.g. the company).
        entity_type = self.connector.object_types[0]
        company_items = self._map(self._load(pending.pop(entity_type, [])), result)
        entity_id = self._entity(entity_key, company_items, result)
        label = self.label(entity_key, entity_id)
        if entity_id is None:
            waiting = sum(len(ids) for ids in pending.values())
            self._fail_all(entity_key, TransformError("company record not synced yet"))
            result.failed += waiting
            self.session.commit()
            self._say(f"{label}: {waiting:,} records wait for the company record")
            return
        result.entity_ids.add(entity_id)
        self.entity_id = entity_id
        self.books_from = self.session.get_one(A.Entity, entity_id).books_from
        self.tree = _GroupTree(self._latest(entity_key, ("group", "ledger"), CanonicalGroup))
        self.types = _TypeTree(self._latest(entity_key, ("voucher_type",), CanonicalVoucherType))
        self.dimensions = self._promoted_dimensions()
        self.dimension_values: dict[tuple[int, str], int] = {}

        for object_type, ids in pending.items():
            self._lookups: tuple[dict[str, Any], ...] | None = None
            total, done, failed_before = len(ids), 0, result.failed
            self._say(f"{label}: transforming {object_type}: {total:,} records")
            for start in range(0, total, BATCH):
                chunk = ids[start : start + BATCH]
                self._batch(self._map(self._load(chunk), result), result)
                done += len(chunk)
                if done % PROGRESS_EVERY < BATCH and done < total:
                    self._say(
                        f"{label}: transforming {object_type}: {done:,} of {total:,} "
                        f"({result.failed - failed_before:,} failed)"
                    )
            self.session.commit()
            if total >= PROGRESS_EVERY or result.failed > failed_before:
                self._say(
                    f"{label}: {object_type}: {total:,} done, "
                    f"{result.failed - failed_before:,} failed"
                )
        result.unmapped_ledgers[entity_id] = list(
            self.session.scalars(
                select(A.Ledger.name)
                .where(
                    A.Ledger.entity_id == entity_id,
                    A.Ledger.mapping_status == "unmapped",
                    A.Ledger.is_deleted.is_(False),
                )
                .order_by(A.Ledger.name)
            )
        )

    def _fail_all(self, entity_key: str, exc: Exception) -> None:
        self.session.execute(
            update(RawRecord)
            .where(
                RawRecord.connection_id == self.connection_id,
                RawRecord.source_entity_key == entity_key,
                RawRecord.process_status == "pending",
            )
            .values(process_status="failed", process_error=short_error(exc))
            .execution_options(synchronize_session=False)
        )

    def _batch(self, mapped: list[_Raw], result: TransformResult) -> None:
        by_kind: dict[type, list[_Raw]] = defaultdict(list)
        for item in mapped:
            kind = next((type(r) for r in item.records if not isinstance(r, CanonicalGroup)), None)
            by_kind[kind or CanonicalGroup].append(item)
        for kind, writer in (
            (CanonicalGroup, self._groups),
            (CanonicalLedger, self._ledgers),
            (CanonicalVoucherType, self._voucher_types),
            (CanonicalUnit, self._units),
            (CanonicalItemGroup, self._item_groups),
            (CanonicalGodown, self._godowns),
            (CanonicalItem, self._items),
            (CanonicalCostCentre, self._cost_centres),
            (CanonicalVoucher, self._vouchers),
        ):
            items = by_kind.pop(kind, [])
            if items:
                self._write(writer, items, result)
        for items in by_kind.values():  # e.g. a second company record: nothing to write
            for item in items:
                self._fail(item.row, TransformError("no canonical table for this record"), result)
        self.session.commit()

    def _write(
        self,
        writer: Callable[[list[_Raw], TransformResult], list[_Raw]],
        items: list[_Raw],
        result: TransformResult,
    ) -> None:
        """Writes a batch; if the database rejects it, record by record, so only the record
        at fault fails (with a safe description: code, table, column, size)."""
        failed, warnings = result.failed, len(result.warnings)
        failed_types = result.failed_by_object_type.copy()
        try:
            ok = writer(items, result)
            self.catalogue.flush()
            self._done(ok, result)
            self.session.commit()
            return
        except Exception as exc:  # noqa: BLE001 - retried record by record below
            self.session.rollback()
            self.catalogue.reset()
            result.failed, result.failed_by_object_type = failed, failed_types
            del result.warnings[warnings:]
            if len(items) == 1:
                logger.warning("Transform record failed: %s", type(exc).__name__)
                self._fail(self.session.get_one(RawRecord, items[0].row.id), exc, result)
                self.session.commit()
                return
            logger.warning(
                "Transform batch failed (%s): writing its %s records one by one",
                type(exc).__name__,
                len(items),
            )
        for item in items:
            item.warnings.clear()
            self._write(writer, [item], result)

    # --- entity -----------------------------------------------------------------------

    def _entity(self, entity_key: str, mapped: list[_Raw], result: TransformResult) -> int | None:
        link = self.session.scalar(
            select(A.EntitySource).where(
                A.EntitySource.connection_id == self.connection_id,
                A.EntitySource.source_entity_key == entity_key,
            )
        )
        company, item = next(
            (
                (r, i)
                for i in mapped
                for r in i.records
                if isinstance(r, CanonicalCompany) and r.source_key == entity_key
            ),
            (None, None),
        )
        for other in mapped:
            if other is not item:  # another company's record in this entity: not ours
                self._fail(other.row, TransformError("company record of another entity"), result)
        if company is None or item is None:
            self.session.commit()
            return link.entity_id if link else None
        try:
            values, unfit = _fit(
                item,
                A.Entity,
                {
                    "name": company.name,
                    "legal_name": company.legal_name,
                    "country_code": company.country_code,
                    "state_code": company.state_code,
                    "gstin": company.gstin,
                    "pan": company.pan,
                    "base_currency_code": company.base_currency_code,
                    "fy_start_month": company.fy_start_month,
                    "books_from": company.books_from,
                },
            )
        except UnfitValueError as exc:
            self._fail(item.row, exc, result)
            self.session.commit()
            return link.entity_id if link else None
        values = _with_extra(values, company.extra, unfit)
        if link is None:
            code = _slug(company.name)
            taken = set(
                self.session.scalars(select(A.Entity.code).where(A.Entity.code.like(f"{code}%")))
            )
            suffix = 2
            unique = code
            while unique in taken:
                unique, suffix = f"{code}_{suffix}", suffix + 1
            entity = A.Entity(code=unique, **values)
            self.session.add(entity)
            self.session.flush()
            self.session.add(
                A.EntitySource(
                    entity_id=entity.id,
                    connection_id=self.connection_id,
                    source_entity_key=entity_key,
                    source_entity_name=values["name"],
                )
            )
            entity_id = entity.id
        else:
            entity_id = link.entity_id
            link.source_entity_name = values["name"]
            self.session.execute(update(A.Entity).where(A.Entity.id == entity_id).values(**values))
        self.catalogue.record(entity_id, item.row.object_type, None, values["extra"])
        self.catalogue.flush()
        self._done([item], result)
        self.session.commit()
        return entity_id

    def _latest(self, entity_key: str, object_types: tuple[str, ...], kind: type) -> list[Any]:
        """Every record of a kind as last received (any status), from the raw records of the
        given object types: groups (plus synthetic groups that ledger records carry, e.g.
        Tally's Primary), voucher types."""
        latest: dict[tuple[str, str], SourceRecord] = {}
        for row in self.session.execute(
            select(
                RawRecord.object_type,
                RawRecord.source_key,
                RawRecord.source_alter_id,
                RawRecord.payload_format,
                RawRecord.payload,
            )
            .where(
                RawRecord.connection_id == self.connection_id,
                RawRecord.source_entity_key == entity_key,
                RawRecord.object_type.in_(object_types),
            )
            .order_by(RawRecord.id)
        ):
            latest[(row.object_type, row.source_key)] = SourceRecord(
                source_entity_key=entity_key,
                object_type=row.object_type,
                source_key=row.source_key,
                source_alter_id=row.source_alter_id,
                payload_format=row.payload_format,
                payload=row.payload,
            )
        found: dict[str, Any] = {}
        for record in latest.values():
            try:
                records = self.connector.to_canonical(record)
            except Exception as exc:  # noqa: BLE001 - reported when the record is processed
                logger.debug(
                    "Skipping unmappable %s record: %s", record.object_type, type(exc).__name__
                )
                continue
            for canonical in records:
                if isinstance(canonical, kind):
                    found[canonical.source_key] = canonical
        return list(found.values())

    # --- masters ----------------------------------------------------------------------

    def _by_name(self, model: type, column: str = "name", *values: str) -> NameIndex:
        """The entity's rows by name -> id (or (id, *values)), resolving by the rules of
        core/names.py. A name too long for its column is in `extra`, and found there
        (ADR-025); aliases are in `extra._aliases` (groups and ledgers)."""
        col = getattr(model, column)
        extra_cols = [getattr(model, v) for v in values]
        with_aliases = model in ALIASED
        index = NameIndex()
        placeholders = False
        query = select(col, model.id, model.extra if with_aliases else col, *extra_cols)
        for name, row_id, extra, *rest in self.session.execute(
            query.where(model.entity_id == self.entity_id)
        ):
            value = (row_id, *rest) if values else row_id
            if name == PLACEHOLDER:
                placeholders = True
                continue
            index.add(name, value)
            if with_aliases:
                for alias in (extra or {}).get(ALIASES) or []:
                    index.add_alias(alias, value)
        if placeholders:  # rare: read extra only for these rows
            for row_id, extra, *rest in self.session.execute(
                select(model.id, model.extra, *extra_cols).where(
                    model.entity_id == self.entity_id, col == PLACEHOLDER
                )
            ):
                name = ((extra or {}).get(UNFIT) or {}).get(column, PLACEHOLDER)
                index.add(name, (row_id, *rest) if values else row_id)
        return index

    def _names(self, model: type, column: str = "name") -> NameIndex:
        return self._by_name(model, column)

    def _ref(
        self, item: _Raw, index: NameIndex, name: str | None, what: str, required: bool = True
    ) -> Any:
        """A reference by name, resolved (core/names.py). Normalised and alias matches are
        recorded as warnings, kinds only. An unresolved required reference fails the record:
        `<source> refers to an unknown <target>`, or, when several targets fit,
        `... matches several <target>s`."""
        source, target = what.split(" -> ")
        found = index.resolve(name)
        if found.how == NORMALISED:
            item.warnings.append(f"reference matched after normalisation: {what}")
        elif found.how == ALIAS:
            item.warnings.append(f"reference matched by alias: {what}")
        if found.found:
            return found.value
        if found.ambiguous:
            message = f"{source} refers to a {target} name that matches several {target}s"
        elif not required:
            return None
        else:
            message = f"{source} refers to an unknown {target}"
        if required:
            raise TransformError(message)
        item.warnings.append(f"ambiguous reference left empty: {what}")
        return None

    def _src(self, item: _Raw, record: Any) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "source_key": record.source_key,
            "source_alter_id": item.row.source_alter_id,
            "import_batch_id": item.row.import_batch_id,
            "raw_record_id": item.row.id,
        }

    def _standard_id(self, code: str | None) -> int | None:
        return self.standard_ids.get(code) if code else None

    def _fitted(
        self, item: _Raw, model: type, record: Any, values: dict[str, Any], result: TransformResult
    ) -> dict[str, Any] | None:
        """The record's row, fitted and with its extra; None (record failed) if a required
        value can't be stored."""
        try:
            row, unfit = _fit(item, model, values)
        except UnfitValueError as exc:
            self._fail(item.row, exc, result)
            return None
        return _with_extra({**self._src(item, record), **row}, record.extra, unfit)

    def _groups(self, items: list[_Raw], result: TransformResult) -> list[_Raw]:
        rows, parents, ok = [], [], []
        for item in items:
            good = True
            for g in (r for r in item.records if isinstance(r, CanonicalGroup)):
                info = self.tree.get(g.name)
                row = self._fitted(
                    item,
                    A.AccountGroup,
                    g,
                    {
                        "name": g.name,
                        "nature": info.nature if info else g.nature,
                        "is_primary": g.is_primary,
                        "affects_gross_profit": g.affects_gross_profit,
                        "standard_account_id": self._standard_id(
                            info.standard_code if info else None
                        ),
                    },
                    result,
                )
                if row is None:
                    good = False
                    break
                rows.append(_with_aliases(row, g.aliases))
                parents.append((g.source_key, g.parent_name))
            if good:
                ok.append(item)
        self.upsert(A.AccountGroup, rows, "group")
        self._link_parents(A.AccountGroup, parents)
        return ok

    def _link_parents(self, model: type, pairs: list[tuple[str, str | None]]) -> None:
        """Parent links by name (exact, alias or normalised; an unresolved or ambiguous
        parent leaves the link empty: the row itself is fine)."""
        names = self._names(model)
        ids = self.upsert.ids(model, [key for key, _ in pairs])
        updates = [
            {"id": ids[key], "parent_id": names.get(parent) if parent else None}
            for key, parent in pairs
            if key in ids
        ]
        if updates:
            self.session.execute(update(model), updates)

    def _ledgers(self, items: list[_Raw], result: TransformResult) -> list[_Raw]:
        # Groups that travel inside ledger records (e.g. Tally's synthetic Primary) first.
        items = self._groups(items, result)
        groups = self._names(A.AccountGroup)
        ok, ledger_rows, party_rows = [], [], []
        for item in items:
            ledger = next(r for r in item.records if isinstance(r, CanonicalLedger))
            try:
                group_id = self._ref(item, groups, ledger.group_name, "ledger -> group")
            except TransformError as exc:
                self._fail(item.row, exc, result)
                continue
            info = self.tree.get(ledger.group_name)
            kind = (info.ledger_kind if info else None) or (
                "tax" if ledger.tax_type else (info.nature if info and info.nature else "other")
            )
            code = (info.standard_code if info else None) or ledger.default_standard_account_code
            standard = self._standard_id(None if code == NO_STANDARD_ACCOUNT else code)
            ledger_row = self._fitted(
                item,
                A.Ledger,
                ledger,
                {
                    "group_id": group_id,
                    "name": ledger.name,
                    "ledger_kind": kind,
                    "standard_account_id": standard,
                    "mapping_status": "auto" if standard else "unmapped",
                    "opening_balance": ledger.opening_balance,
                    "opening_balance_date": ledger.opening_balance_date or self.books_from,
                    "currency_code": "INR",
                    "is_bill_wise": ledger.is_bill_wise,
                    "is_cost_centre_applicable": ledger.is_cost_centre_applicable,
                    "gstin": ledger.gstin,
                    "tax_type": ledger.tax_type,
                },
                result,
            )
            if ledger_row is None:
                continue
            ledger_row = _with_aliases(ledger_row, ledger.aliases)
            party_row = None
            if kind == "party":
                p = ledger.party
                party_row = self._fitted(
                    item,
                    A.Party,
                    ledger,
                    {
                        "name": ledger.name,
                        "party_type": (p.party_type if p and p.party_type else None)
                        or (info.party_type if info else None)
                        or "other",
                        "gstin": p.gstin if p else None,
                        "pan": p.pan if p else None,
                        "state_code": p.state_code if p else None,
                        "country_code": p.country_code if p else None,
                        "credit_days": p.credit_days if p else None,
                        "credit_limit": p.credit_limit if p else None,
                        "email": p.email if p else None,
                        "phone": p.phone if p else None,
                    },
                    result,
                )
                if party_row is None:
                    continue
                # The ledger row carries the source's extra fields; the party only what
                # didn't fit its own columns.
                party_row["extra"] = merge_extra(None, (party_row["extra"] or {}).get(UNFIT, {}))
            result.warnings.extend(f"{ledger.name}: {warning}" for warning in ledger.warnings)
            ledger_rows.append(ledger_row)
            if party_row is not None:
                party_rows.append(party_row)
            ok.append(item)
        party_ids = self.upsert(A.Party, party_rows)
        for row in ledger_rows:
            row["party_id"] = party_ids.get(row["source_key"])
        self.upsert(A.Ledger, ledger_rows, "ledger")
        return ok

    def _simple(
        self,
        items: list[_Raw],
        kind: type,
        model: type,
        values: Any,
        result: TransformResult,
        object_type: str,
    ) -> list[_Raw]:
        rows, ok = [], []
        for item in items:
            good = True
            for r in (r for r in item.records if isinstance(r, kind)):
                row = self._fitted(item, model, r, values(r), result)
                if row is None:
                    good = False
                    break
                rows.append(row)
            if good:
                ok.append(item)
        self.upsert(model, rows, object_type)
        return ok

    def _voucher_types(self, items: list[_Raw], result: TransformResult) -> list[_Raw]:
        return self._simple(
            items,
            CanonicalVoucherType,
            A.VoucherType,
            lambda r: {
                "name": r.name,
                # Inherited through the voucher type tree when the source didn't say.
                "base_type": self.types.info(r).base_type,
                "is_accounting": self.types.info(r).is_accounting,
                "standard_type": self.types.info(r).standard_type,
                "moves_stock": self.types.info(r).moves_stock,
                "is_inventory": r.is_inventory,
            },
            result,
            "voucher_type",
        )

    def _units(self, items: list[_Raw], result: TransformResult) -> list[_Raw]:
        return self._simple(
            items,
            CanonicalUnit,
            A.Unit,
            lambda r: {"symbol": r.symbol, "name": r.name, "decimal_places": r.decimal_places},
            result,
            "unit",
        )

    def _item_groups(self, items: list[_Raw], result: TransformResult) -> list[_Raw]:
        done = self._simple(
            items, CanonicalItemGroup, A.ItemGroup, lambda r: {"name": r.name}, result,
            "stock_group",
        )  # fmt: skip
        self._link_parents(
            A.ItemGroup, [(r.source_key, r.parent_name) for i in done for r in i.records]
        )
        return done

    def _godowns(self, items: list[_Raw], result: TransformResult) -> list[_Raw]:
        done = self._simple(
            items,
            CanonicalGodown,
            A.Godown,
            lambda r: {"name": r.name, "holding": r.holding},
            result,
            "godown",
        )
        self._link_parents(
            A.Godown, [(r.source_key, r.parent_name) for i in done for r in i.records]
        )
        return done

    def _cost_centres(self, items: list[_Raw], result: TransformResult) -> list[_Raw]:
        done = self._simple(
            items,
            CanonicalCostCentre,
            A.CostCentre,
            lambda r: {"name": r.name, "category": r.category},
            result,
            "cost_centre",
        )
        self._link_parents(
            A.CostCentre, [(r.source_key, r.parent_name) for i in done for r in i.records]
        )
        return done

    def _items(self, items: list[_Raw], result: TransformResult) -> list[_Raw]:
        groups = self._names(A.ItemGroup)
        units = self._names(A.Unit, "symbol")
        return self._simple(
            items,
            CanonicalItem,
            A.Item,
            lambda r: {
                "name": r.name,
                "item_group_id": groups.get(r.group_name) if r.group_name else None,
                "unit_id": units.get(r.unit_name) if r.unit_name else None,
                "opening_qty": r.opening_qty,
                "opening_value": r.opening_value,
            },
            result,
            "stock_item",
        )

    # --- vouchers ---------------------------------------------------------------------

    def _master_lookups(self) -> tuple[NameIndex, ...]:
        """Masters by name, for vouchers: read once per object type (masters are written
        before vouchers and don't change meanwhile)."""
        if self._lookups is None:
            self._lookups = (
                self._by_name(A.VoucherType, "name", "is_accounting"),
                self._by_name(A.Ledger, "name", "party_id", "tax_type"),
                self._names(A.Item),
                self._names(A.Godown),
                self._names(A.Unit, "symbol"),
                self._names(A.CostCentre),
            )
        return self._lookups

    def _vouchers(self, items: list[_Raw], result: TransformResult) -> list[_Raw]:
        types, ledgers, items_by_name, godowns, units, centres = self._master_lookups()

        prepared: list[_Prepared] = []
        for item in items:
            v = next(r for r in item.records if isinstance(r, CanonicalVoucher))
            try:
                refs = _Refs(
                    voucher_type=self._ref(
                        item, types, v.voucher_type_name, "voucher -> voucher type"
                    ),
                    ledgers={
                        line.ledger_name: self._ref(
                            item, ledgers, line.ledger_name, "voucher -> ledger"
                        )
                        for line in v.lines
                    },
                    items={
                        inv.item_name: self._ref(
                            item, items_by_name, inv.item_name, "voucher -> stock item"
                        )
                        for inv in v.inventory
                    },
                    centres={
                        name: self._ref(item, centres, name, "voucher -> cost centre")
                        for line in v.lines
                        for name, _ in line.cost_allocations
                    },
                    godowns={
                        inv.godown_name: self._ref(
                            item, godowns, inv.godown_name, "voucher -> godown", required=False
                        )
                        for inv in v.inventory
                        if inv.godown_name
                    },
                    units={
                        inv.unit_name: self._ref(
                            item, units, inv.unit_name, "voucher -> unit", required=False
                        )
                        for inv in v.inventory
                        if inv.unit_name
                    },
                    party=self._ref(
                        item,
                        ledgers,
                        v.party_ledger_name,
                        "voucher -> party ledger",
                        required=False,
                    )
                    if v.party_ledger_name
                    else None,
                )
                prepared.append(self._prepare(item, v, refs))
            except (TransformError, UnfitValueError) as exc:
                self._fail(item.row, exc, result)
        if not prepared:
            return []

        voucher_ids = self.upsert(A.Voucher, [p.header for p in prepared], "voucher")
        # Overlapping deliveries of one voucher: only its latest version is written below.
        latest = {p.header["source_key"]: p for p in prepared}
        ids = [voucher_ids[key] for key in latest]
        self._delete_children(ids)

        now = utcnow()
        stamp = {"created_at": now, "updated_at": now}
        line_rows, inventory_rows = [], []
        for key, p in latest.items():
            vid = voucher_ids[key]
            base = {"voucher_id": vid, "entity_id": self.entity_id, **stamp}
            line_rows += [{**base, **line.row} for line in p.lines]
            inventory_rows += [{**base, **row} for row in p.inventory]
        if line_rows:
            self.session.execute(insert(A.VoucherLine), line_rows)
        if inventory_rows:
            self.session.execute(insert(A.InventoryLine), inventory_rows)

        line_ids = {
            (vid, no): lid
            for lid, vid, no in self.session.execute(
                select(A.VoucherLine.id, A.VoucherLine.voucher_id, A.VoucherLine.line_no).where(
                    A.VoucherLine.voucher_id.in_(ids)
                )
            )
        }
        bills, allocations, taxes, dimensions = [], [], [], []
        for key, p in latest.items():
            vid = voucher_ids[key]
            values = self._dimension_values(p.extra)
            for line in p.lines:
                line_id = line_ids[(vid, line.row["line_no"])]
                bills += [{"voucher_line_id": line_id, **row, **stamp} for row in line.bills]
                allocations += [
                    {"voucher_line_id": line_id, **row, **stamp} for row in line.allocations
                ]
                if line.tax is not None:
                    taxes.append(
                        {"voucher_id": vid, "voucher_line_id": line_id, **line.tax, **stamp}
                    )
                dimensions += [
                    {"voucher_line_id": line_id, "dimension_value_id": value_id, **stamp}
                    for value_id in values
                ]
        for model, rows in (
            (A.BillAllocation, bills),
            (A.LineCostAllocation, allocations),
            (A.TaxLine, taxes),
            (A.LineDimension, dimensions),
        ):
            if rows:
                self.session.execute(insert(model), rows)
        return [p.item for p in prepared]

    def _prepare(
        self,
        item: _Raw,
        v: CanonicalVoucher,
        refs: "_Refs",
    ) -> "_Prepared":
        """A voucher's rows, each fitted to its columns. Child values that don't fit are kept
        in the voucher's extra as `<table>[<n>].<column>`. Raises UnfitValueError if a
        required value (an amount, a quantity, the date) can't be stored."""
        unfit: dict[str, Any] = {}

        def fit(model: type, n: int, row: dict[str, Any]) -> dict[str, Any]:
            fitted, kept = _fit(item, model, row)
            table = model.__tablename__  # type: ignore[attr-defined]
            unfit.update({f"{table}[{n}].{column}": value for column, value in kept.items()})
            return fitted

        type_id, posts = refs.voucher_type
        # Lines count in balances only when the voucher posts to the books: not cancelled,
        # not optional, and of a voucher type that posts (not e.g. an order or memorandum).
        effective = not (v.is_cancelled or v.is_optional) and posts is not False
        lines = []
        for no, line in enumerate(v.lines, start=1):
            lid, party_id, tax_type = refs.ledgers[line.ledger_name]
            lines.append(
                _PreparedLine(
                    row=fit(
                        A.VoucherLine,
                        no,
                        {
                            "voucher_date": v.voucher_date,
                            "line_no": no,
                            "ledger_id": lid,
                            "amount": line.amount,
                            "is_party_line": line.is_party_line,
                            "is_effective": effective,
                        },
                    ),
                    bills=[
                        fit(
                            A.BillAllocation,
                            no,
                            {
                                "party_id": party_id,
                                "bill_type": bill.bill_type,
                                "bill_name": bill.name,
                                "bill_date": bill.bill_date,
                                "amount": bill.amount,
                            },
                        )
                        for bill in line.bills
                    ],
                    allocations=[
                        fit(
                            A.LineCostAllocation,
                            no,
                            {"cost_centre_id": refs.centres[name], "amount": amount},
                        )
                        for name, amount in line.cost_allocations
                    ],
                    tax=fit(A.TaxLine, no, {"tax_type": tax_type, "tax_amount": line.amount})
                    if tax_type
                    else None,
                )
            )
        inventory = [
            fit(
                A.InventoryLine,
                no,
                {
                    "voucher_date": v.voucher_date,
                    "line_no": no,
                    "item_id": refs.items[inv.item_name],
                    "godown_id": refs.godowns.get(inv.godown_name or ""),
                    "quantity": inv.quantity,
                    # A line tracked to a delivery or receipt note doesn't move stock on a
                    # voucher that posts to the books: the note moves it (counted once).
                    "stock_quantity": inv.quantity - inv.tracked_quantity
                    if posts is not False
                    else inv.quantity,
                    "unit_id": refs.units.get(inv.unit_name or ""),
                    "rate": inv.rate,
                    "amount": inv.amount,
                    "discount_pct": inv.discount_pct,
                    "batch_name": inv.batch_name,
                },
            )
            for no, inv in enumerate(v.inventory, start=1)
        ]
        party = refs.party
        header, kept = _fit(
            item,
            A.Voucher,
            {
                "voucher_type_id": type_id,
                "voucher_number": v.voucher_number,
                "voucher_date": v.voucher_date,
                "reference_number": v.reference_number,
                "reference_date": v.reference_date,
                "effective_date": v.effective_date,
                "party_id": party[1] if party else None,
                "narration": v.narration,
                "currency_code": "INR",
                "is_cancelled": v.is_cancelled,
                "is_optional": v.is_optional,
                "is_post_dated": v.is_post_dated,
            },
        )
        header = _with_extra({**self._src(item, v), **header}, v.extra, {**kept, **unfit})
        return _Prepared(item, header, v.extra, lines, inventory)

    # --- promoted fields (dimensions) ---------------------------------------------------

    def _promoted_dimensions(self) -> list[tuple[int, str]]:
        return list(
            self.session.execute(
                select(A.Dimension.id, A.Dimension.source_field).where(
                    A.Dimension.source_object_type == "voucher",
                    A.Dimension.source_field.is_not(None),
                    A.Dimension.is_active.is_(True),
                )
            ).all()
        )

    def _dimension_values(self, extra: Any) -> list[int]:
        """Dimension value ids for a voucher, from its promoted fields."""
        ids = []
        for dimension_id, source_field in self.dimensions:
            value = dimension_value_of(extra, source_field)
            if value is not None:
                ids.append(
                    dimension_value_id(
                        self.session, dimension_id, self.entity_id, value, self.dimension_values
                    )
                )
        return ids

    def _delete_children(self, voucher_ids: list[int]) -> None:
        """Removes every child row of these vouchers (explicitly, not relying on cascades,
        so it works the same on every database)."""
        if not voucher_ids:
            return
        line_ids = select(A.VoucherLine.id).where(A.VoucherLine.voucher_id.in_(voucher_ids))
        for model in (A.BillAllocation, A.LineCostAllocation, A.LineDimension):
            self.session.execute(
                delete(model)
                .where(model.voucher_line_id.in_(line_ids))
                .execution_options(synchronize_session=False)
            )
        for model in (A.TaxLine, A.InventoryLine, A.VoucherLine):
            self.session.execute(
                delete(model)
                .where(model.voucher_id.in_(voucher_ids))
                .execution_options(synchronize_session=False)
            )


@dataclass
class _Refs:
    """A voucher's references, resolved: name as written -> id (ledgers: (id, party_id,
    tax_type); voucher type: (id, is_accounting))."""

    voucher_type: tuple[int, bool | None]
    ledgers: dict[str, Any]
    items: dict[str, int]
    centres: dict[str, int]
    godowns: dict[str, int | None]
    units: dict[str, int | None]
    party: Any


ALIASED: tuple[type, ...] = (A.AccountGroup, A.Ledger)  # rows that keep aliases in extra
ALIASES = "_aliases"


def _with_aliases(row: dict[str, Any], aliases: tuple[str, ...]) -> dict[str, Any]:
    """Other names a master is known by (ADR-027), kept in its extra."""
    if not aliases:
        return row
    return {**row, "extra": {**(row.get("extra") or {}), ALIASES: list(aliases)}}


@dataclass
class _PreparedLine:
    row: dict[str, Any]
    bills: list[dict[str, Any]]
    allocations: list[dict[str, Any]]
    tax: dict[str, Any] | None


@dataclass
class _Prepared:
    item: _Raw
    header: dict[str, Any]
    extra: Any
    lines: list[_PreparedLine]
    inventory: list[dict[str, Any]]


def dimension_value_of(extra: Any, source_field: str) -> str | None:
    """A promoted field's value in a record's extra (the first, if it repeats)."""
    value = (extra or {}).get(source_field)
    if isinstance(value, list):
        value = value[0] if value else None
    return str(value) if value not in (None, "") else None


def dimension_value_id(
    session: Session,
    dimension_id: int,
    entity_id: int,
    value: str,
    cache: dict[tuple[int, str], int],
) -> int:
    """The id of a dimension's value for an entity, created on first use."""
    code = _dimension_code(entity_id, value)
    key = (dimension_id, code)
    if key not in cache:
        found = session.scalar(
            select(A.DimensionValue.id).where(
                A.DimensionValue.dimension_id == dimension_id, A.DimensionValue.code == code
            )
        )
        if found is None:
            now = utcnow()
            row = A.DimensionValue(
                dimension_id=dimension_id,
                entity_id=entity_id,
                code=code,
                name=value if len(value) <= 255 else code,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.flush()
            found = row.id
        cache[key] = found
    return cache[key]


def _source_record(row: RawRecord) -> SourceRecord:
    return SourceRecord(
        source_entity_key=row.source_entity_key,
        object_type=row.object_type,
        source_key=row.source_key,
        source_alter_id=row.source_alter_id,
        payload_format=row.payload_format,  # type: ignore[arg-type]
        payload=row.payload,
    )


def mark_deleted(
    session: Session, connection_id: int, entity_id: int, existing: dict[str, set[str]]
) -> dict[str, int]:
    """Soft-deletes canonical rows whose source object no longer exists (SYN-003).

    `existing` holds the source keys that exist now, per object type. Only rows built from
    raw records of that object type are considered. Deleted vouchers' lines stop counting.
    """
    deleted: dict[str, int] = {}
    models = list(dict.fromkeys(m for ms in MODELS_BY_KIND.values() for m in ms))
    for object_type, keys in existing.items():
        for model in models:
            candidates = session.execute(
                select(model.id, model.source_key, RawRecord.source_key)
                .join(RawRecord, RawRecord.id == model.raw_record_id)
                .where(
                    model.connection_id == connection_id,
                    model.entity_id == entity_id,
                    model.is_deleted.is_(False),
                    RawRecord.object_type == object_type,
                )
            ).all()
            # Rows derived under a different key (e.g. a synthetic group carried by a
            # ledger record) aren't source objects themselves and are never deleted here.
            gone = [
                row_id for row_id, key, raw_key in candidates if key == raw_key and key not in keys
            ]
            if not gone:
                continue
            session.execute(
                update(model).where(model.id.in_(gone)).values(is_deleted=True, updated_at=utcnow())
            )
            if model is A.Voucher:
                session.execute(
                    update(A.VoucherLine)
                    .where(A.VoucherLine.voucher_id.in_(gone))
                    .values(is_effective=False, updated_at=utcnow())
                )
            deleted[f"{object_type}:{model.__tablename__}"] = len(gone)
    session.commit()
    return deleted


def trial_balance(session: Session, entity_id: int) -> list[tuple[str, Any]]:
    """Closing balance per ledger: opening balance + effective voucher lines (debit +)."""
    movements = (
        select(A.VoucherLine.ledger_id, func.sum(A.VoucherLine.amount).label("movement"))
        .where(A.VoucherLine.entity_id == entity_id, A.VoucherLine.is_effective.is_(True))
        .group_by(A.VoucherLine.ledger_id)
        .subquery()
    )
    rows = session.execute(
        select(A.Ledger.name, A.Ledger.opening_balance + func.coalesce(movements.c.movement, 0))
        .outerjoin(movements, movements.c.ledger_id == A.Ledger.id)
        .where(A.Ledger.entity_id == entity_id, A.Ledger.is_deleted.is_(False))
        .order_by(A.Ledger.name)
    ).all()
    return [(name, balance) for name, balance in rows]
