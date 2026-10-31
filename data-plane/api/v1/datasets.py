"""The table explorer's endpoints (D1; ADR-049).

- `GET /api/v1/datasets`: each dataset with its dimensions, measures and filters (what the
  explorer's dropdowns offer);
- `GET /api/v1/datasets/{name}`: one page of a result (api/v1/dataset_query.py);
- `GET /api/v1/datasets/{name}/csv`: exactly that result as CSV, streamed, at most
  1,00,000 rows; when the limit is reached the last line says so and the
  `X-Row-Limit-Reached` header is `true`.

Only allow-listed keys are accepted (api/v1/dataset_specs.py); companies are limited to the
caller's access, and a company outside it is "not found".
"""

import csv
import io
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.access import CurrentAccess
from api.v1.common import ReportSession
from api.v1.dataset_query import (
    CSV_ROW_LIMIT,
    DatasetRequest,
    RequestError,
    ResultRow,
    count_rows,
    parse_request,
    rows_for_csv,
    run,
)
from api.v1.dataset_specs import DATASETS, Dataset

router = APIRouter(tags=["datasets"])


class Option(BaseModel):
    key: str
    label: str


class FilterOption(Option):
    kind: str  # date_from, date_to, ids, amount_min, amount_max


class DimensionOption(Option):
    groupable: bool


class DatasetInfo(BaseModel):
    key: str
    label: str
    dimensions: list[DimensionOption]
    measures: list[Option]
    filters: list[FilterOption]
    default_columns: list[str]
    default_measures: list[str]


class Key(BaseModel):
    id: int | str
    label: str


class Row(BaseModel):
    keys: dict[str, Key]
    values: dict[str, Decimal | int]
    level: int | None = None  # subtotals: how many outer groups they total


class DatasetResult(BaseModel):
    dataset: str
    group_by: list[str]
    columns: list[str]
    measures: list[str]
    rows: list[Row]
    subtotals: list[Row]
    total: dict[str, Decimal | int]
    page: int
    page_size: int
    total_rows: int


@router.get("/datasets")
def datasets() -> list[DatasetInfo]:
    return [
        DatasetInfo(
            key=d.key,
            label=d.label,
            dimensions=[
                DimensionOption(key=x.key, label=x.label, groupable=x.groupable)
                for x in d.dimensions.values()
            ],
            measures=[Option(key=m.key, label=m.label) for m in d.measures.values()],
            filters=[
                FilterOption(key=f.key, label=f.label, kind=f.kind) for f in d.filters.values()
            ],
            default_columns=list(d.default_columns),
            default_measures=list(d.default_measures),
        )  # fmt: skip
        for d in DATASETS.values()
    ]


@router.get("/datasets/{name}")
def query(
    name: str, request: Request, session: ReportSession, access: CurrentAccess
) -> DatasetResult:
    dataset, asked, companies = _prepare(name, request, access)
    result = run(session, dataset, asked, companies)
    return DatasetResult(
        dataset=dataset.key,
        group_by=asked.group_by,
        columns=asked.columns,
        measures=asked.measures,
        rows=[_out(r) for r in result.rows],
        subtotals=[_out(r) for r in result.subtotals],
        total=result.total,
        page=asked.page,
        page_size=asked.page_size,
        total_rows=result.total_rows,
    )


@router.get("/datasets/{name}/csv")
def export_csv(
    name: str, request: Request, session: ReportSession, access: CurrentAccess
) -> StreamingResponse:
    dataset, asked, companies = _prepare(name, request, access)
    reached = count_rows(session, dataset, asked, companies) > CSV_ROW_LIMIT
    rows = rows_for_csv(session, dataset, asked, companies, CSV_ROW_LIMIT)
    return StreamingResponse(
        _csv_lines(dataset, asked, rows, reached),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{dataset.key}.csv"',
            "X-Row-Limit-Reached": "true" if reached else "false",
        },
    )


def _prepare(name: str, request: Request, access: Any) -> tuple[Dataset, DatasetRequest, list[int]]:
    dataset = DATASETS.get(name)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Unknown dataset.")
    try:
        asked = parse_request(dataset, request.query_params.multi_items())
    except RequestError as problem:
        raise HTTPException(status_code=422, detail=str(problem)) from None
    return dataset, asked, access.entities(asked.filters.get("company"))


def _out(row: ResultRow) -> Row:
    return Row(
        keys={k: Key(id=i, label=label) for k, (i, label) in row.keys.items()},
        values=row.values,
        level=row.level,
    )


def _csv_lines(
    dataset: Dataset, asked: DatasetRequest, rows: Iterator[ResultRow], reached: bool
) -> Iterator[str]:
    """The header, every row (subtotals and the total labelled), and the limit's note."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    def line(cells: list[str]) -> str:
        buffer.seek(0)
        buffer.truncate()
        writer.writerow(cells)
        return buffer.getvalue()

    yield "\ufeff"  # Excel reads the file as UTF-8
    yield line([dataset.dimensions[k].label for k in asked.keys]
               + [dataset.measures[m].label for m in asked.measures])  # fmt: skip
    for row in rows:
        if row.level == 0:
            keys = ["Total"] + [""] * (len(asked.keys) - 1)
        elif row.level is not None:
            labels = [row.keys[k][1] for k in asked.keys[: row.level]]
            keys = labels[:-1] + [f"{labels[-1]} (subtotal)"]
            keys += [""] * (len(asked.keys) - len(keys))
        else:
            keys = [row.keys[k][1] for k in asked.keys]
        yield line([_safe(k) for k in keys] + [str(row.values[m]) for m in asked.measures])
    if reached:
        yield line([f"Stopped at {indian(CSV_ROW_LIMIT)} rows: narrow the filters to export "
                    "the rest."])  # fmt: skip


def indian(n: int) -> str:
    """A whole number in Indian grouping: 1,00,000."""
    digits = str(n)
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    pairs = [head[max(0, k - 2) : k] for k in range(len(head), 0, -2)][::-1]
    return ",".join(pairs) + "," + tail


def _safe(text: str) -> str:
    """A text cell spreadsheets won't run as a formula (CSV injection)."""
    return f"'{text}" if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text
