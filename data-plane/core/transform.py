"""Raw records → canonical tables (schema.md Section 8). Source-independent.

- Pending raw records are processed per entity, in the connector's object-type order.
- Every canonical row is upserted on (connection_id, source_key): a record delivered twice
  (e.g. in two overlapping month requests) updates the same row and never duplicates it.
- A voucher's child rows (lines, bills, cost allocations, dimensions, inventory, tax) are
  deleted and re-inserted in the same transaction as the voucher header (rule 7).
- Group "hints" (nature, standard account, ledger kind, party type) are inherited down the
  group tree, which is rebuilt from the latest raw group records on every run.
- Errors are recorded per raw record as type + field names; never amounts.
"""

import logging
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
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
from core.models import accounting as A  # noqa: N812 - short alias for many models
from core.models.base import utcnow
from core.models.source import RawRecord

logger = logging.getLogger(__name__)

BATCH = 500

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


class TransformError(ValueError):
    """A record can't be written (e.g. it refers to a master that doesn't exist)."""


@dataclass
class TransformResult:
    processed: int = 0
    failed: int = 0
    by_object_type: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    entity_ids: set[int] = field(default_factory=set)
    unmapped_ledgers: dict[int, list[str]] = field(default_factory=dict)  # entity_id -> names
    warnings: list[str] = field(default_factory=list)  # "<ledger name>: <assumption made>"


@dataclass
class _Raw:
    row: RawRecord
    records: list[CanonicalRecord]


def _slug(name: str) -> str:
    return (re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_") or "ENTITY")[:28]


class _Upserter:
    """Bulk upsert on (connection_id, source_key); returns source_key -> id."""

    def __init__(self, session: Session, connection_id: int, origin: str) -> None:
        self.session = session
        self.connection_id = connection_id
        self.origin = origin

    def __call__(self, model: type, rows: list[dict[str, Any]]) -> dict[str, int]:
        if not rows:
            return {}
        # The same key twice in one batch (overlapping deliveries): the last one wins.
        by_key = {row["source_key"]: row for row in rows}
        keys = list(by_key)
        now = utcnow()
        existing = self.ids(model, keys)
        new, changed = [], []
        for key, row in by_key.items():
            row = {
                **row,
                "connection_id": self.connection_id,
                "origin": self.origin,
                "is_deleted": False,
                "updated_at": now,
            }
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
    """The entity's group tree with hints inherited from the nearest ancestor."""

    def __init__(self, groups: Iterable[CanonicalGroup]) -> None:
        self.by_name = {g.name: _GroupInfo(g) for g in groups}
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
            info = self.by_name.get(name)
            if info is None:
                return None
            value = getattr(info.group, attribute)
            if value is not None:
                return value
            name = info.group.parent_name
        return None

    def get(self, name: str) -> _GroupInfo | None:
        return self.by_name.get(name)


class Transformer:
    def __init__(
        self, session: Session, connection_id: int, connector: Connector, origin: str = "live"
    ) -> None:
        self.session = session
        self.connection_id = connection_id
        self.connector = connector
        self.upsert = _Upserter(session, connection_id, origin)
        self.order = {t: i for i, t in enumerate(connector.object_types)}
        self.standard_ids = dict(
            session.execute(select(A.StandardAccount.code, A.StandardAccount.id)).all()
        )

    # --- driver -----------------------------------------------------------------------

    def run(self, entity_keys: Iterable[str] | None = None) -> TransformResult:
        result = TransformResult()
        query = select(RawRecord.source_entity_key).where(
            RawRecord.connection_id == self.connection_id, RawRecord.process_status == "pending"
        )
        if entity_keys is not None:
            query = query.where(RawRecord.source_entity_key.in_(list(entity_keys)))
        for entity_key in sorted(set(self.session.scalars(query.distinct()))):
            self._run_entity(entity_key, result)
        return result

    def _pending(self, entity_key: str) -> list[RawRecord]:
        rows = self.session.scalars(
            select(RawRecord).where(
                RawRecord.connection_id == self.connection_id,
                RawRecord.source_entity_key == entity_key,
                RawRecord.process_status == "pending",
            )
        ).all()
        return sorted(rows, key=lambda r: (self.order.get(r.object_type, len(self.order)), r.id))

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
        result.failed += 1

    def _done(self, items: Iterable[_Raw], result: TransformResult) -> None:
        for item in items:
            item.row.process_status = "processed"
            item.row.process_error = None
            result.processed += 1
            result.by_object_type[item.row.object_type] += 1

    def _run_entity(self, entity_key: str, result: TransformResult) -> None:
        pending = self._pending(entity_key)
        mapped = self._map(pending, result)
        entity_id = self._entity(entity_key, mapped)
        if entity_id is None:
            for item in mapped:
                self._fail(item.row, TransformError("company record not synced yet"), result)
            self.session.commit()
            return
        result.entity_ids.add(entity_id)
        self.entity_id = entity_id
        self.books_from = self.session.get_one(A.Entity, entity_id).books_from
        self.tree = _GroupTree(self._latest_groups(entity_key))

        by_kind: dict[type, list[_Raw]] = defaultdict(list)
        for item in mapped:
            kind = next((type(r) for r in item.records if not isinstance(r, CanonicalGroup)), None)
            by_kind[kind or CanonicalGroup].append(item)
        by_kind.pop(CanonicalCompany, None)

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
            items = by_kind.get(kind, [])
            for start in range(0, len(items), BATCH):
                batch = items[start : start + BATCH]
                try:
                    ok = writer(batch, result)
                    self._done(ok, result)
                    self.session.commit()
                except Exception as exc:  # noqa: BLE001 - whole batch recorded as failed
                    self.session.rollback()
                    logger.warning("Transform batch failed: %s", type(exc).__name__)
                    for item in batch:
                        row = self.session.get_one(RawRecord, item.row.id)
                        self._fail(row, exc, result)
                    self.session.commit()
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

    # --- entity -----------------------------------------------------------------------

    def _entity(self, entity_key: str, mapped: list[_Raw]) -> int | None:
        company = next(
            (r for item in mapped for r in item.records if isinstance(r, CanonicalCompany)), None
        )
        link = self.session.scalar(
            select(A.EntitySource).where(
                A.EntitySource.connection_id == self.connection_id,
                A.EntitySource.source_entity_key == entity_key,
            )
        )
        if company is None:
            return link.entity_id if link else None
        values = {
            "name": company.name,
            "legal_name": company.legal_name,
            "country_code": company.country_code,
            "state_code": company.state_code,
            "gstin": company.gstin,
            "pan": company.pan,
            "base_currency_code": company.base_currency_code,
            "fy_start_month": company.fy_start_month,
            "books_from": company.books_from,
        }
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
                    source_entity_name=company.name,
                )
            )
            entity_id = entity.id
        else:
            entity_id = link.entity_id
            link.source_entity_name = company.name
            self.session.execute(update(A.Entity).where(A.Entity.id == entity_id).values(**values))
        for item in mapped:
            if any(isinstance(r, CanonicalCompany) for r in item.records):
                item.row.process_status = "processed"
                item.row.process_error = None
        self.session.commit()
        return entity_id

    def _latest_groups(self, entity_key: str) -> list[CanonicalGroup]:
        """Every group of the entity as last received (any status), plus synthetic groups that
        ledger records carry (e.g. Tally's Primary)."""
        latest: dict[tuple[str, str], RawRecord] = {}
        for row in self.session.scalars(
            select(RawRecord)
            .where(
                RawRecord.connection_id == self.connection_id,
                RawRecord.source_entity_key == entity_key,
                RawRecord.object_type.in_(("group", "ledger")),
            )
            .order_by(RawRecord.id)
        ):
            latest[(row.object_type, row.source_key)] = row
        groups: dict[str, CanonicalGroup] = {}
        for row in latest.values():
            try:
                records = self.connector.to_canonical(_source_record(row))
            except Exception as exc:  # noqa: BLE001 - reported when the record is processed
                logger.debug(
                    "Skipping unmappable %s record: %s", row.object_type, type(exc).__name__
                )
                continue
            for record in records:
                if isinstance(record, CanonicalGroup):
                    groups[record.source_key] = record
        return list(groups.values())

    # --- masters ----------------------------------------------------------------------

    def _names(self, model: type, column: str = "name") -> dict[str, int]:
        col = getattr(model, column)
        return dict(
            self.session.execute(
                select(col, model.id).where(model.entity_id == self.entity_id)
            ).all()
        )

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

    def _groups(self, items: list[_Raw], result: TransformResult) -> list[_Raw]:
        rows, parents = [], []
        for item in items:
            for g in (r for r in item.records if isinstance(r, CanonicalGroup)):
                info = self.tree.get(g.name)
                rows.append(
                    {
                        **self._src(item, g),
                        "name": g.name,
                        "nature": info.nature if info else g.nature,
                        "is_primary": g.is_primary,
                        "affects_gross_profit": g.affects_gross_profit,
                        "standard_account_id": self._standard_id(
                            info.standard_code if info else None
                        ),
                    }
                )
                parents.append((g.source_key, g.parent_name))
        self.upsert(A.AccountGroup, rows)
        self._link_parents(A.AccountGroup, parents)
        return items

    def _link_parents(self, model: type, pairs: list[tuple[str, str | None]]) -> None:
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
        self._groups(items, result)
        groups = self._names(A.AccountGroup)
        ok, ledger_rows, party_rows = [], [], []
        for item in items:
            ledger = next(r for r in item.records if isinstance(r, CanonicalLedger))
            group_id = groups.get(ledger.group_name)
            if group_id is None:
                self._fail(item.row, TransformError("ledger refers to an unknown group"), result)
                continue
            info = self.tree.get(ledger.group_name)
            kind = (info.ledger_kind if info else None) or (
                "tax" if ledger.tax_type else (info.nature if info and info.nature else "other")
            )
            code = (info.standard_code if info else None) or ledger.default_standard_account_code
            standard = self._standard_id(None if code == NO_STANDARD_ACCOUNT else code)
            result.warnings.extend(f"{ledger.name}: {warning}" for warning in ledger.warnings)
            ledger_rows.append(
                {
                    **self._src(item, ledger),
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
                }
            )
            if kind == "party":
                p = ledger.party
                party_rows.append(
                    {
                        **self._src(item, ledger),
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
                    }
                )
            ok.append(item)
        party_ids = self.upsert(A.Party, party_rows)
        for row in ledger_rows:
            row["party_id"] = party_ids.get(row["source_key"])
        self.upsert(A.Ledger, ledger_rows)
        return ok

    def _simple(self, items: list[_Raw], kind: type, model: type, values: Any) -> list[_Raw]:
        rows = [
            {**self._src(item, r), **values(r)}
            for item in items
            for r in item.records
            if isinstance(r, kind)
        ]
        self.upsert(model, rows)
        return items

    def _voucher_types(self, items: list[_Raw], result: TransformResult) -> list[_Raw]:
        return self._simple(
            items,
            CanonicalVoucherType,
            A.VoucherType,
            lambda r: {
                "name": r.name,
                "base_type": r.base_type,
                "is_accounting": r.is_accounting,
                "is_inventory": r.is_inventory,
            },
        )

    def _units(self, items: list[_Raw], result: TransformResult) -> list[_Raw]:
        return self._simple(
            items,
            CanonicalUnit,
            A.Unit,
            lambda r: {"symbol": r.symbol, "name": r.name, "decimal_places": r.decimal_places},
        )

    def _item_groups(self, items: list[_Raw], result: TransformResult) -> list[_Raw]:
        done = self._simple(items, CanonicalItemGroup, A.ItemGroup, lambda r: {"name": r.name})
        self._link_parents(
            A.ItemGroup, [(r.source_key, r.parent_name) for i in items for r in i.records]
        )
        return done

    def _godowns(self, items: list[_Raw], result: TransformResult) -> list[_Raw]:
        done = self._simple(items, CanonicalGodown, A.Godown, lambda r: {"name": r.name})
        self._link_parents(
            A.Godown, [(r.source_key, r.parent_name) for i in items for r in i.records]
        )
        return done

    def _cost_centres(self, items: list[_Raw], result: TransformResult) -> list[_Raw]:
        done = self._simple(
            items,
            CanonicalCostCentre,
            A.CostCentre,
            lambda r: {"name": r.name, "category": r.category},
        )
        self._link_parents(
            A.CostCentre, [(r.source_key, r.parent_name) for i in items for r in i.records]
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
        )

    # --- vouchers ---------------------------------------------------------------------

    def _vouchers(self, items: list[_Raw], result: TransformResult) -> list[_Raw]:
        types = self._names(A.VoucherType)
        ledgers = {
            name: (lid, party_id, tax_type)
            for name, lid, party_id, tax_type in self.session.execute(
                select(A.Ledger.name, A.Ledger.id, A.Ledger.party_id, A.Ledger.tax_type).where(
                    A.Ledger.entity_id == self.entity_id
                )
            )
        }
        items_by_name = self._names(A.Item)
        godowns = self._names(A.Godown)
        units = self._names(A.Unit, "symbol")
        centres = self._names(A.CostCentre)

        ok: list[tuple[_Raw, CanonicalVoucher]] = []
        for item in items:
            v = next(r for r in item.records if isinstance(r, CanonicalVoucher))
            missing = (
                ("voucher type" if v.voucher_type_name not in types else None)
                or next(("ledger" for line in v.lines if line.ledger_name not in ledgers), None)
                or next(
                    ("stock item" for inv in v.inventory if inv.item_name not in items_by_name),
                    None,
                )
                or next(
                    (
                        "cost centre"
                        for line in v.lines
                        for name, _ in line.cost_allocations
                        if name not in centres
                    ),
                    None,
                )
            )
            if missing:
                self._fail(
                    item.row, TransformError(f"voucher refers to an unknown {missing}"), result
                )
            else:
                ok.append((item, v))
        if not ok:
            return []

        headers = []
        for item, v in ok:
            party = ledgers.get(v.party_ledger_name or "")
            headers.append(
                {
                    **self._src(item, v),
                    "voucher_type_id": types[v.voucher_type_name],
                    "voucher_number": v.voucher_number,
                    "voucher_date": v.voucher_date,
                    "reference_number": v.reference_number,
                    "reference_date": v.reference_date,
                    "party_id": party[1] if party else None,
                    "narration": v.narration,
                    "currency_code": "INR",
                    "is_cancelled": v.is_cancelled,
                    "is_optional": v.is_optional,
                    "is_post_dated": v.is_post_dated,
                }
            )
        voucher_ids = self.upsert(A.Voucher, headers)
        # Overlapping deliveries of one voucher: only its latest version is written below.
        latest: dict[str, tuple[_Raw, CanonicalVoucher]] = {v.source_key: (i, v) for i, v in ok}
        ids = [voucher_ids[key] for key in latest]
        self._delete_children(ids)

        now = utcnow()
        line_rows, pending_details = [], []
        inventory_rows = []
        for key, (_item, v) in latest.items():
            vid = voucher_ids[key]
            effective = not (v.is_cancelled or v.is_optional)
            for no, line in enumerate(v.lines, start=1):
                lid, _party, _tax = ledgers[line.ledger_name]
                line_rows.append(
                    {
                        "voucher_id": vid,
                        "entity_id": self.entity_id,
                        "voucher_date": v.voucher_date,
                        "line_no": no,
                        "ledger_id": lid,
                        "amount": line.amount,
                        "is_party_line": line.is_party_line,
                        "is_effective": effective,
                        "created_at": now,
                        "updated_at": now,
                    }
                )
                pending_details.append((vid, no, line))
            for no, inv in enumerate(v.inventory, start=1):
                inventory_rows.append(
                    {
                        "voucher_id": vid,
                        "entity_id": self.entity_id,
                        "voucher_date": v.voucher_date,
                        "line_no": no,
                        "item_id": items_by_name[inv.item_name],
                        "godown_id": godowns.get(inv.godown_name or ""),
                        "quantity": inv.quantity,
                        "unit_id": units.get(inv.unit_name or ""),
                        "rate": inv.rate,
                        "amount": inv.amount,
                        "discount_pct": inv.discount_pct,
                        "batch_name": inv.batch_name,
                        "created_at": now,
                        "updated_at": now,
                    }
                )
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
        bills, allocations, taxes = [], [], []
        for vid, no, line in pending_details:
            line_id = line_ids[(vid, no)]
            _lid, party_id, tax_type = ledgers[line.ledger_name]
            for bill in line.bills:
                bills.append(
                    {
                        "voucher_line_id": line_id,
                        "party_id": party_id,
                        "bill_type": bill.bill_type,
                        "bill_name": bill.name,
                        "bill_date": bill.bill_date,
                        "amount": bill.amount,
                        "created_at": now,
                        "updated_at": now,
                    }
                )
            for name, amount in line.cost_allocations:
                allocations.append(
                    {
                        "voucher_line_id": line_id,
                        "cost_centre_id": centres[name],
                        "amount": amount,
                        "created_at": now,
                        "updated_at": now,
                    }
                )
            if tax_type:
                taxes.append(
                    {
                        "voucher_id": vid,
                        "voucher_line_id": line_id,
                        "tax_type": tax_type,
                        "tax_amount": line.amount,
                        "created_at": now,
                        "updated_at": now,
                    }
                )
        for model, rows in (
            (A.BillAllocation, bills),
            (A.LineCostAllocation, allocations),
            (A.TaxLine, taxes),
        ):
            if rows:
                self.session.execute(insert(model), rows)
        return [item for item, _ in ok]

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
