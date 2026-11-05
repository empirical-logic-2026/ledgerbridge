"""The table explorer's datasets: what each one may be grouped by, measured and filtered by.

Every request names only keys from these allow-lists; each key maps to a fixed SQLAlchemy
expression here. No SQL text and no column names ever come from a request (ADR-049).

- **voucher_lines**: one row per effective voucher line (the books: `is_effective`, voucher
  not deleted), the same lines the statements and the monthly sales views add up.
- **vouchers**: one row per voucher with effective lines; its amount is the total of its
  debit lines.

Dimensions have an id (what filters and grouping use) and a label (what is shown). Time
dimensions follow each company's financial year (`entities.fy_start_month`). Measures have
a per-row form (lists) and a total form (groups, subtotals, the total).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import ColumnElement, and_, case, distinct, func, literal, select
from sqlalchemy.sql import FromClause

from core.models import accounting as A  # noqa: N812
from core.reporting_views import COST_ALLOCATIONS, GROUP_ANCESTORS

NONE_LABEL = "(none)"


@dataclass(frozen=True)
class Dimension:
    key: str
    label: str
    id_expr: ColumnElement[Any]
    label_expr: ColumnElement[Any]
    groupable: bool = True  # False: a list column only (e.g. the voucher number)


@dataclass(frozen=True)
class Measure:
    key: str
    label: str
    row_expr: ColumnElement[Any]  # one row's value (list mode)
    total_expr: ColumnElement[Any]  # the value of a group, a subtotal or the total
    is_count: bool = False


@dataclass(frozen=True)
class Filter:
    key: str
    label: str
    kind: str  # "date_from", "date_to", "ids", "amount_min", "amount_max"
    condition: Callable[[Any], ColumnElement[bool]]


@dataclass(frozen=True)
class Dataset:
    key: str
    label: str
    source: FromClause  # the joined tables
    base_conditions: tuple[ColumnElement[bool], ...]
    company_id: ColumnElement[Any]  # every query is limited to the caller's companies
    dimensions: dict[str, Dimension]
    measures: dict[str, Measure]
    filters: dict[str, Filter]
    default_columns: tuple[str, ...]
    default_measures: tuple[str, ...]
    default_order: tuple[ColumnElement[Any], ...] = field(default=())


def _fy(day: ColumnElement[Any]) -> ColumnElement[Any]:
    """The calendar year the company's financial year holding `day` starts in."""
    return func.year(day) - case((func.month(day) < A.Entity.fy_start_month, 1), else_=0)


def _fy_label(day: ColumnElement[Any]) -> ColumnElement[Any]:
    fy = _fy(day)
    return func.concat("FY ", fy, "-", func.lpad(func.mod(fy + 1, 100), 2, "0"))


def _quarter(day: ColumnElement[Any]) -> ColumnElement[Any]:
    """1 to 4 within the company's financial year."""
    return func.floor(func.mod(func.month(day) - A.Entity.fy_start_month + 12, 12) / 3) + 1


def _time_dimensions(day: ColumnElement[Any]) -> list[Dimension]:
    return [
        Dimension("date", "Date", func.date_format(day, "%Y-%m-%d"),
                  func.date_format(day, "%d-%b-%Y"), groupable=False),
        Dimension("month", "Month", func.date_format(day, "%Y-%m"),
                  func.date_format(day, "%b-%Y")),
        Dimension("quarter", "Quarter", func.concat(_fy(day), "-Q", _quarter(day)),
                  func.concat("Q", _quarter(day), " ", _fy_label(day))),
        Dimension("financial_year", "Financial year", _fy(day), _fy_label(day)),
    ]  # fmt: skip


def _named(key: str, label: str, id_col: Any, name_col: Any) -> Dimension:
    """A dimension over a named master; rows without one get id 0 and "(none)"."""
    return Dimension(key, label, func.coalesce(id_col, 0), func.coalesce(name_col, NONE_LABEL))


def _ids(column: Any) -> Callable[[Any], ColumnElement[bool]]:
    return lambda ids: column.in_(ids)


def _in_groups(ids: Any) -> ColumnElement[bool]:
    """Ledgers in the groups or any group below them."""
    below = select(GROUP_ANCESTORS.c.group_id).where(GROUP_ANCESTORS.c.ancestor_id.in_(ids))
    return A.Ledger.group_id.in_(below)


def _by_key(items: list[Any]) -> dict[str, Any]:
    return {item.key: item for item in items}


def _in_cost_centres(ids: Any) -> ColumnElement[bool]:
    """Lines with an allocation to any of the cost centres."""
    allocated = select(A.LineCostAllocation.voucher_line_id).where(
        A.LineCostAllocation.cost_centre_id.in_(ids)
    )
    return A.VoucherLine.id.in_(allocated)


def _text(key: str, label: str, column: Any) -> Dimension:
    """A list column of free text (a reference or instrument number): not for grouping."""
    return Dimension(
        key, label, func.coalesce(column, ""), func.coalesce(column, ""), groupable=False
    )


def _date_filters(day: Any) -> list[Filter]:
    return [
        Filter("date_from", "From", "date_from", lambda on: day >= on),
        Filter("date_to", "To", "date_to", lambda on: day <= on),
    ]


def _voucher_lines() -> Dataset:
    vl, v = A.VoucherLine, A.Voucher
    source = (
        vl.__table__.join(v.__table__, v.id == vl.voucher_id)
        .join(A.Entity.__table__, A.Entity.id == vl.entity_id)
        .join(A.VoucherType.__table__, A.VoucherType.id == v.voucher_type_id)
        .join(A.Ledger.__table__, A.Ledger.id == vl.ledger_id)
        .join(A.AccountGroup.__table__, A.AccountGroup.id == A.Ledger.group_id)
        .outerjoin(A.Party.__table__, A.Party.id == v.party_id)
    )
    debit = case((vl.amount > 0, vl.amount), else_=0)
    credit = case((vl.amount < 0, -vl.amount), else_=0)
    return Dataset(
        key="voucher_lines",
        label="Voucher lines",
        source=source,
        base_conditions=(vl.is_effective.is_(True), v.is_deleted.is_(False)),
        company_id=vl.entity_id,
        dimensions=_by_key(
            [
                _named("company", "Company", A.Entity.id, A.Entity.name),
                *_time_dimensions(vl.voucher_date),
                _named("voucher_type", "Voucher type", A.VoucherType.id, A.VoucherType.name),
                Dimension(
                    "voucher_number", "Voucher number", v.id, v.voucher_number, groupable=False
                ),
                _named("ledger", "Ledger", A.Ledger.id, A.Ledger.name),
                _named("ledger_group", "Ledger group", A.AccountGroup.id, A.AccountGroup.name),
                _named("party", "Party", A.Party.id, A.Party.name),
                _text("reference", "Reference", v.reference_number),
                _text("instrument_number", "Cheque / transfer no.", vl.instrument_number),
                _text("transaction_reference", "UTR", vl.transaction_reference),
            ]
        ),  # fmt: skip
        measures=_by_key(
            [
                Measure("debit", "Debit", debit, func.sum(debit)),
                Measure("credit", "Credit", credit, func.sum(credit)),
                Measure("net", "Net (Dr - Cr)", vl.amount, func.sum(vl.amount)),
                Measure(
                    "voucher_count",
                    "Vouchers",
                    literal(1),
                    func.count(distinct(v.id)),
                    is_count=True,
                ),
            ]
        ),  # fmt: skip
        filters=_by_key(
            [
                *_date_filters(vl.voucher_date),
                Filter("company", "Company", "ids", _ids(vl.entity_id)),
                Filter("voucher_type", "Voucher type", "ids", _ids(v.voucher_type_id)),
                Filter("ledger", "Ledger", "ids", _ids(vl.ledger_id)),
                Filter("ledger_group", "Ledger group (and below)", "ids", _in_groups),
                Filter("party", "Party", "ids", _ids(v.party_id)),
                Filter("cost_centre", "Cost centre", "ids", _in_cost_centres),
                Filter(
                    "amount_min", "Amount from", "amount_min", lambda x: func.abs(vl.amount) >= x
                ),
                Filter("amount_max", "Amount to", "amount_max", lambda x: func.abs(vl.amount) <= x),
            ]
        ),  # fmt: skip
        default_columns=("date", "voucher_number", "voucher_type", "ledger", "party"),
        default_measures=("debit", "credit"),
        default_order=(vl.voucher_date, v.voucher_number, vl.id),
    )


def _vouchers() -> Dataset:
    v, vl = A.Voucher, A.VoucherLine
    totals = (
        select(vl.voucher_id.label("voucher_id"),
               func.sum(case((vl.amount > 0, vl.amount), else_=0)).label("amount"))
        .where(vl.is_effective.is_(True))
        .group_by(vl.voucher_id)
        .subquery("voucher_totals")
    )  # fmt: skip
    source = (
        v.__table__.join(totals, totals.c.voucher_id == v.id)
        .join(A.Entity.__table__, A.Entity.id == v.entity_id)
        .join(A.VoucherType.__table__, A.VoucherType.id == v.voucher_type_id)
        .outerjoin(A.Party.__table__, A.Party.id == v.party_id)
    )
    amount = totals.c.amount
    return Dataset(
        key="vouchers",
        label="Vouchers",
        source=source,
        base_conditions=(v.is_deleted.is_(False),),
        company_id=v.entity_id,
        dimensions=_by_key(
            [
                _named("company", "Company", A.Entity.id, A.Entity.name),
                *_time_dimensions(v.voucher_date),
                _named("voucher_type", "Voucher type", A.VoucherType.id, A.VoucherType.name),
                Dimension(
                    "voucher_number", "Voucher number", v.id, v.voucher_number, groupable=False
                ),
                _named("party", "Party", A.Party.id, A.Party.name),
                _text("reference", "Reference", v.reference_number),
            ]
        ),  # fmt: skip
        measures=_by_key(
            [
                Measure("amount", "Amount", amount, func.sum(amount)),
                Measure(
                    "voucher_count",
                    "Vouchers",
                    literal(1),
                    func.count(distinct(v.id)),
                    is_count=True,
                ),
            ]
        ),  # fmt: skip
        filters=_by_key(
            [
                *_date_filters(v.voucher_date),
                Filter("company", "Company", "ids", _ids(v.entity_id)),
                Filter("voucher_type", "Voucher type", "ids", _ids(v.voucher_type_id)),
                Filter("party", "Party", "ids", _ids(v.party_id)),
                Filter("amount_min", "Amount from", "amount_min", lambda x: amount >= x),
                Filter("amount_max", "Amount to", "amount_max", lambda x: amount <= x),
            ]
        ),  # fmt: skip
        default_columns=("date", "voucher_number", "voucher_type", "party"),
        default_measures=("amount",),
        default_order=(v.voucher_date, v.voucher_number, v.id),
    )


def _cost_allocations() -> Dataset:
    """One row per cost-centre allocation (v_cost_allocations, migration 0026)."""
    ca = COST_ALLOCATIONS.c
    source = COST_ALLOCATIONS.join(A.Entity.__table__, A.Entity.id == ca.entity_id)
    return Dataset(
        key="cost_allocations",
        label="Cost centre allocations",
        source=source,
        base_conditions=(),
        company_id=ca.entity_id,
        dimensions=_by_key(
            [
                _named("company", "Company", A.Entity.id, A.Entity.name),
                *_time_dimensions(ca.voucher_date),
                _named("voucher_type", "Voucher type", ca.voucher_type, ca.voucher_type),
                Dimension(
                    "voucher_number",
                    "Voucher number",
                    ca.voucher_id,
                    ca.voucher_number,
                    groupable=False,
                ),
                _named("ledger", "Ledger", ca.ledger_id, ca.ledger),
                _named("cost_category", "Cost category", ca.cost_category_id, ca.cost_category),
                _named("cost_centre", "Cost centre", ca.cost_centre_id, ca.cost_centre),
            ]
        ),  # fmt: skip
        measures=_by_key(
            [
                Measure("amount", "Amount", ca.amount, func.sum(ca.amount)),
                Measure("allocations", "Allocations", literal(1), func.count(), is_count=True),
            ]
        ),  # fmt: skip
        filters=_by_key(
            [
                *_date_filters(ca.voucher_date),
                Filter("company", "Company", "ids", _ids(ca.entity_id)),
                Filter("ledger", "Ledger", "ids", _ids(ca.ledger_id)),
                Filter("cost_category", "Cost category", "ids", _ids(ca.cost_category_id)),
                Filter("cost_centre", "Cost centre", "ids", _ids(ca.cost_centre_id)),
            ]
        ),  # fmt: skip
        default_columns=("date", "voucher_number", "ledger", "cost_category", "cost_centre"),
        default_measures=("amount",),
        default_order=(ca.voucher_date, ca.voucher_number, ca.voucher_line_id),
    )


DATASETS: dict[str, Dataset] = {
    d.key: d for d in (_voucher_lines(), _vouchers(), _cost_allocations())
}


def all_of(*conditions: ColumnElement[bool]) -> ColumnElement[bool]:
    return and_(*conditions)
