"""The field catalogue, and promoting a catalogued field to a reporting dimension (ADR-025).

The transform keeps every field the mapping doesn't use (e.g. Tally UDFs) in each row's
`extra` JSON and counts them in `ledgerbridge_accounting.source_fields`. A field that is
useful for reporting can be promoted by an explicit command:

    python -m workers.cli promote-field --field-id 12 --code SALESMAN --name "Salesman"

This creates a dimension linked to the field, gives each distinct value a dimension value
(per entity) and attaches it to the lines of every voucher carrying the field (backfill
from `extra`). From then on the transform keeps it up to date. No schema change is needed:
the accounting user never runs DDL. A field useful for every client becomes a real column
through a migration instead.

Only voucher fields can be promoted for now: dimensions attach to voucher lines
(`line_dimensions`).
"""

from collections import Counter
from dataclasses import dataclass

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from core.models import accounting as A  # noqa: N812
from core.models.base import utcnow
from core.transform import BATCH, dimension_value_id, dimension_value_of

PROMOTABLE = ("voucher",)


class PromoteError(ValueError):
    """The field can't be promoted (unknown field, wrong object type, code in use)."""


@dataclass
class Promoted:
    dimension_id: int
    vouchers: int = 0  # vouchers carrying the field
    values: int = 0  # distinct values (dimension values)
    lines: int = 0  # voucher lines given the value


def catalogue(session: Session, entity_ids: list[int] | None = None) -> list[A.SourceField]:
    query = select(A.SourceField).order_by(
        A.SourceField.entity_id, A.SourceField.object_type, A.SourceField.field_path
    )
    if entity_ids:
        query = query.where(A.SourceField.entity_id.in_(entity_ids))
    return list(session.scalars(query))


def catalogue_counts(session: Session, entity_id: int) -> Counter[str]:
    """Catalogued fields of an entity per prefix ('none' for fields without one)."""
    return Counter(
        {
            (prefix or "none"): n
            for prefix, n in session.execute(
                select(A.SourceField.prefix, func.count())
                .where(A.SourceField.entity_id == entity_id)
                .group_by(A.SourceField.prefix)
            )
        }
    )


def promote_field(session: Session, field_id: int, code: str, name: str) -> Promoted:
    """Promotes a catalogued field to a dimension and backfills it on every entity whose
    catalogue has the same field (same object type and path)."""
    field = session.get(A.SourceField, field_id)
    if field is None:
        raise PromoteError(f"no catalogued field with id {field_id}")
    if field.object_type not in PROMOTABLE:
        raise PromoteError(
            f"only fields of {', '.join(PROMOTABLE)} records can become dimensions for now "
            f"(this one is a {field.object_type} field)"
        )
    dimension = session.scalar(select(A.Dimension).where(A.Dimension.code == code))
    if dimension is not None and (
        dimension.source_object_type,
        dimension.source_field,
    ) != (field.object_type, field.field_path):
        raise PromoteError(f"dimension code {code} is already used for something else")
    now = utcnow()
    if dimension is None:
        dimension = A.Dimension(
            code=code,
            name=name,
            applies_to="line",
            is_active=True,
            source_object_type=field.object_type,
            source_field=field.field_path,
            created_at=now,
            updated_at=now,
        )
        session.add(dimension)
        session.flush()
    promoted = Promoted(dimension.id)
    entity_ids = list(
        session.scalars(
            select(A.SourceField.entity_id).where(
                A.SourceField.object_type == field.object_type,
                A.SourceField.field_path == field.field_path,
            )
        )
    )
    # A promotion run twice starts again from the values in extra.
    values = select(A.DimensionValue.id).where(A.DimensionValue.dimension_id == dimension.id)
    session.execute(
        delete(A.LineDimension)
        .where(A.LineDimension.dimension_value_id.in_(values))
        .execution_options(synchronize_session=False)
    )
    cache: dict[tuple[int, str], int] = {}
    last_id = 0
    while True:
        vouchers = session.execute(
            select(A.Voucher.id, A.Voucher.entity_id, A.Voucher.extra)
            .where(
                A.Voucher.entity_id.in_(entity_ids),
                A.Voucher.id > last_id,
                A.Voucher.extra.is_not(None),
            )
            .order_by(A.Voucher.id)
            .limit(BATCH)
        ).all()
        if not vouchers:
            break
        last_id = vouchers[-1][0]
        value_of: dict[int, int] = {}
        for voucher_id, entity_id, extra in vouchers:
            value = dimension_value_of(extra, field.field_path)
            if value is not None:
                value_of[voucher_id] = dimension_value_id(
                    session, dimension.id, entity_id, value, cache
                )
        if not value_of:
            continue
        lines = session.execute(
            select(A.VoucherLine.id, A.VoucherLine.voucher_id).where(
                A.VoucherLine.voucher_id.in_(list(value_of))
            )
        ).all()
        rows = [
            {
                "voucher_line_id": line_id,
                "dimension_value_id": value_of[voucher_id],
                "created_at": now,
                "updated_at": now,
            }
            for line_id, voucher_id in lines
        ]
        if rows:
            session.execute(insert(A.LineDimension), rows)
        promoted.vouchers += len(value_of)
        promoted.lines += len(rows)
    promoted.values = len(cache)
    session.commit()
    return promoted
