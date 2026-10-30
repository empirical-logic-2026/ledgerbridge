"""Reading a table explorer request and answering it from MySQL (D1; ADR-049).

A request is the query string of `GET /api/v1/datasets/<name>`: `group_by`, `column`,
`measure` (repeatable), `sort` (`key` or `-key`), `page`, `page_size`, and the dataset's
filters (`company=3&company=4`, `date_from=2026-04-01`, ...). `parse_request` accepts only
keys from the dataset's allow-lists (api/v1/dataset_specs.py) and answers anything else with
a plain message: unknown parameters are refused, not ignored.

- **Grouped** (`group_by` given): one row per combination, aggregated in MySQL, a page at a
  time; the subtotals of every outer group on the page; the total. Rows are ordered by the
  outer groups, then by `sort` within the innermost one, so groups stay together.
- **List** (no `group_by`): the dataset's rows with the chosen columns and measures.
- **CSV** (`rows_for_csv`): the same result, every row in display order with the subtotals
  after their group and the total last, up to `CSV_ROW_LIMIT` rows.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import ColumnElement, Select, func, select, tuple_
from sqlalchemy.orm import Session

from api.v1.dataset_specs import Dataset

MAX_GROUPS = 4  # nested group-bys
MAX_PAGE_SIZE = 500
CSV_ROW_LIMIT = 100_000
MAX_AMOUNT = Decimal(10**16)  # DECIMAL(20,4) holds less
_CONTROL = {"group_by", "column", "measure", "sort", "page", "page_size"}


class RequestError(ValueError):
    """A request outside the dataset's allow-lists (answered with 422)."""


@dataclass
class DatasetRequest:
    group_by: list[str]
    columns: list[str]  # list mode only
    measures: list[str]
    filters: dict[str, Any] = field(default_factory=dict)
    sort: str | None = None
    descending: bool = False
    page: int = 1
    page_size: int = 100

    @property
    def keys(self) -> list[str]:
        """The dimensions shown: the groups, or the list's columns."""
        return self.group_by or self.columns


@dataclass
class ResultRow:
    keys: dict[str, tuple[Any, str]]  # dimension -> (id, label)
    values: dict[str, Decimal | int]
    level: int | None = None  # subtotals: how many outer groups they total (1 = outermost)


@dataclass
class Result:
    rows: list[ResultRow]
    subtotals: list[ResultRow]
    total: dict[str, Decimal | int]
    total_rows: int


# --- reading the request ------------------------------------------------------------------


def parse_request(dataset: Dataset, params: Sequence[tuple[str, str]]) -> DatasetRequest:
    """The request, checked against the dataset's allow-lists."""
    values: dict[str, list[str]] = {}
    for name, value in params:
        if name not in _CONTROL and name not in dataset.filters:
            raise RequestError(f"Unknown parameter '{name}'.")
        values.setdefault(name, []).append(value)

    group_by = _unique(values.get("group_by", []), "group_by")
    for key in group_by:
        dimension = dataset.dimensions.get(key)
        if dimension is None or not dimension.groupable:
            raise RequestError(f"'{key}' can't be grouped by in {dataset.key}.")
    if len(group_by) > MAX_GROUPS:
        raise RequestError(f"At most {MAX_GROUPS} group-bys.")
    columns = _unique(values.get("column", []), "column") or list(dataset.default_columns)
    for key in columns:
        if key not in dataset.dimensions:
            raise RequestError(f"Unknown column '{key}' in {dataset.key}.")
    measures = _unique(values.get("measure", []), "measure") or list(dataset.default_measures)
    for key in measures:
        if key not in dataset.measures:
            raise RequestError(f"Unknown measure '{key}' in {dataset.key}.")

    request = DatasetRequest(group_by, [] if group_by else columns, measures)
    for key, given in values.items():
        if key in dataset.filters:
            request.filters[key] = _filter_value(dataset.filters[key].kind, key, given)
    sort = _single(values, "sort")
    if sort:
        request.descending = sort.startswith("-")
        request.sort = sort.lstrip("-")
        if request.sort not in request.keys and request.sort not in measures:
            raise RequestError(f"Sort by a shown column or measure, not '{request.sort}'.")
    request.page = _number(_single(values, "page") or "1", "page", 1, 1_000_000)
    request.page_size = _number(
        _single(values, "page_size") or "100", "page_size", 1, MAX_PAGE_SIZE
    )
    return request


def _unique(keys: list[str], name: str) -> list[str]:
    if len(set(keys)) != len(keys):
        raise RequestError(f"'{name}' names a key twice.")
    return keys


def _single(values: dict[str, list[str]], name: str) -> str | None:
    given = values.get(name, [])
    if len(given) > 1:
        raise RequestError(f"'{name}' may be given once.")
    return given[0] if given else None


def _number(text: str, name: str, low: int, high: int) -> int:
    if not text.isdigit() or not low <= int(text) <= high:
        raise RequestError(f"'{name}' must be a whole number from {low} to {high:,}.")
    return int(text)


def _filter_value(kind: str, key: str, given: list[str]) -> Any:
    if kind == "ids":
        if not all(v.isdigit() for v in given):
            raise RequestError(f"'{key}' takes ids (whole numbers).")
        return sorted({int(v) for v in given})
    if len(given) != 1:
        raise RequestError(f"'{key}' may be given once.")
    if kind in ("date_from", "date_to"):
        try:
            return date.fromisoformat(given[0])
        except ValueError:
            raise RequestError(f"'{key}' must be a date (YYYY-MM-DD).") from None
    try:
        amount = Decimal(given[0])
    except InvalidOperation:
        raise RequestError(f"'{key}' must be an amount.") from None
    if not amount.is_finite() or not 0 <= amount <= MAX_AMOUNT:
        raise RequestError(f"'{key}' must be an amount of 0 or more, up to {MAX_AMOUNT:,}.")
    return amount


# --- answering it -------------------------------------------------------------------------


def run(
    session: Session, dataset: Dataset, request: DatasetRequest, companies: list[int]
) -> Result:
    """One page of the result, its subtotals and the total."""
    where = _conditions(dataset, request, companies)
    total = _total(session, dataset, request, where)
    if request.group_by:
        grouped = _grouped(dataset, request, where)
        count = session.scalar(select(func.count()).select_from(grouped.subquery())) or 0
        page = grouped.limit(request.page_size).offset((request.page - 1) * request.page_size)
        rows = [_row(dataset, request, r) for r in session.execute(page)]
        subtotals = _subtotals(session, dataset, request, where, rows)
        return Result(rows, subtotals, total, count)
    listed = _listed(dataset, request, where)
    count = session.scalar(
        select(func.count()).select_from(dataset.source).where(*where)
    ) or 0  # fmt: skip
    page = listed.limit(request.page_size).offset((request.page - 1) * request.page_size)
    rows = [_row(dataset, request, r) for r in session.execute(page)]
    return Result(rows, [], total, count)


def count_rows(
    session: Session, dataset: Dataset, request: DatasetRequest, companies: list[int]
) -> int:
    where = _conditions(dataset, request, companies)
    query = _grouped(dataset, request, where) if request.group_by else None
    if query is not None:
        return session.scalar(select(func.count()).select_from(query.subquery())) or 0
    return session.scalar(select(func.count()).select_from(dataset.source).where(*where)) or 0


def rows_for_csv(
    session: Session, dataset: Dataset, request: DatasetRequest, companies: list[int], limit: int
) -> Iterator[ResultRow]:
    """Every row in display order (subtotals after their group, the total last), at most
    `limit` data rows."""
    where = _conditions(dataset, request, companies)
    if not request.group_by:
        for r in session.execute(_listed(dataset, request, where).limit(limit)):
            yield _row(dataset, request, r)
        yield ResultRow({}, _total(session, dataset, request, where), level=0)
        return
    rows = [_row(dataset, request, r) for r in session.execute(
        _grouped(dataset, request, where).limit(limit))]  # fmt: skip
    subtotals = {
        (s.level, _ids(s, request.group_by[: s.level])): s
        for s in _subtotals(session, dataset, request, where, rows)
    }
    for i, row in enumerate(rows):
        yield row
        following = rows[i + 1] if i + 1 < len(rows) else None
        for level in range(len(request.group_by) - 1, 0, -1):  # innermost group closes first
            outer = request.group_by[:level]
            if following is None or _ids(following, outer) != _ids(row, outer):
                found = subtotals.get((level, _ids(row, outer)))
                if found is not None:
                    yield found
    yield ResultRow({}, _total(session, dataset, request, where), level=0)


def _conditions(dataset: Dataset, request: DatasetRequest, companies: list[int]) -> list[Any]:
    where: list[Any] = [*dataset.base_conditions, dataset.company_id.in_(companies)]
    for key, value in request.filters.items():
        where.append(dataset.filters[key].condition(value))
    return where


def _key_columns(dataset: Dataset, keys: list[str]) -> list[Any]:
    columns = []
    for key in keys:
        dimension = dataset.dimensions[key]
        columns += [
            dimension.id_expr.label(f"{key}__id"),
            dimension.label_expr.label(f"{key}__label"),
        ]
    return columns


def _grouped(dataset: Dataset, request: DatasetRequest, where: list[Any]) -> Select[Any]:
    dims = [dataset.dimensions[k] for k in request.group_by]
    measures = [dataset.measures[m].total_expr.label(m) for m in request.measures]
    group = [e for d in dims for e in (d.id_expr, d.label_expr)]
    order: list[Any] = [e for d in dims[:-1] for e in (d.label_expr, d.id_expr)]
    order += _sort(dataset, request, total=True)
    order += [dims[-1].label_expr, dims[-1].id_expr]
    return (
        select(*_key_columns(dataset, request.group_by), *measures)
        .select_from(dataset.source)
        .where(*where)
        .group_by(*group)
        .order_by(*order)
    )


def _listed(dataset: Dataset, request: DatasetRequest, where: list[Any]) -> Select[Any]:
    measures = [dataset.measures[m].row_expr.label(m) for m in request.measures]
    return (
        select(*_key_columns(dataset, request.columns), *measures)
        .select_from(dataset.source)
        .where(*where)
        .order_by(*_sort(dataset, request, total=False), *dataset.default_order)
    )


def _sort(dataset: Dataset, request: DatasetRequest, total: bool) -> list[ColumnElement[Any]]:
    if request.sort is None:
        return []
    if request.sort in dataset.measures:
        m = dataset.measures[request.sort]
        expr = m.total_expr if total else m.row_expr
    else:
        expr = dataset.dimensions[request.sort].label_expr
    return [expr.desc() if request.descending else expr.asc()]


def _total(
    session: Session, dataset: Dataset, request: DatasetRequest, where: list[Any]
) -> dict[str, Decimal | int]:
    row = session.execute(
        select(*[dataset.measures[m].total_expr.label(m) for m in request.measures])
        .select_from(dataset.source)
        .where(*where)
    ).one()
    return {m: _value(dataset, m, row._mapping[m]) for m in request.measures}


def _subtotals(
    session: Session,
    dataset: Dataset,
    request: DatasetRequest,
    where: list[Any],
    rows: list[ResultRow],
) -> list[ResultRow]:
    """For each outer level, the subtotals of the groups present in `rows`."""
    found = []
    for level in range(1, len(request.group_by)):
        outer = request.group_by[:level]
        present = sorted({_ids(r, outer) for r in rows})
        if not present:
            continue
        dims = [dataset.dimensions[k] for k in outer]
        query = (
            select(*_key_columns(dataset, outer),
                   *[dataset.measures[m].total_expr.label(m) for m in request.measures])
            .select_from(dataset.source)
            .where(*where, tuple_(*[d.id_expr for d in dims]).in_(present))
            .group_by(*[e for d in dims for e in (d.id_expr, d.label_expr)])
        )  # fmt: skip
        sub = DatasetRequest(outer, [], request.measures)
        for r in session.execute(query):
            row = _row(dataset, sub, r)
            row.level = level
            found.append(row)
    return found


def _row(dataset: Dataset, request: DatasetRequest, r: Any) -> ResultRow:
    m = r._mapping
    keys = {k: (_plain(m[f"{k}__id"]), str(m[f"{k}__label"])) for k in request.keys}
    return ResultRow(keys, {k: _value(dataset, k, m[k]) for k in request.measures})


def _ids(row: ResultRow, keys: list[str]) -> tuple[Any, ...]:
    return tuple(row.keys[k][0] for k in keys)


def _plain(value: Any) -> Any:
    """Ids as int or str (MySQL returns some expressions as Decimal)."""
    if isinstance(value, Decimal):
        return int(value)
    return value


def _value(dataset: Dataset, measure: str, value: Any) -> Decimal | int:
    if dataset.measures[measure].is_count:
        return int(value or 0)
    return Decimal(value or 0)
