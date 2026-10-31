"""Companies and periods for the dashboard's switchers (D1; RPT-006, RPT-008).

- `GET /api/v1/companies`: the companies the caller may see (not on hold), with their data
  health: last successful sync and latest validation (`v_data_health`), their source's name,
  and whether the source had them loaded when a sync or `entity-check` last asked
  (`entity_sources.source_loaded`; the dashboard never asks the source itself).
- `GET /api/v1/periods`: the financial years the selected companies' books cover, and the
  "as at" dates their statements are stored for (for several companies, the dates all of
  them have).
"""

from datetime import date, datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from api.access import CurrentAccess
from api.v1.common import ReportSession
from core.models import accounting as A  # noqa: N812
from core.models.reporting import StatementLine
from core.reporting_views import DATA_HEALTH

router = APIRouter(tags=["companies"])


class DataHealth(BaseModel):
    last_sync_at: datetime | None
    validation_status: str | None  # passed, failed, running; None: never validated
    validated_as_of: date | None
    validated_at: datetime | None
    source_name: str | None  # "Tally"
    source_loaded: bool | None  # None: never asked
    source_checked_at: datetime | None
    source_checked_by: str | None  # sync, entity_check


class Company(BaseModel):
    id: int
    code: str
    name: str
    books_from: date | None
    fy_start_month: int
    health: DataHealth


class FinancialYear(BaseModel):
    start_year: int  # the calendar year it starts in
    label: str  # "FY 2025-26"
    start: date
    end: date


class Periods(BaseModel):
    financial_years: list[FinancialYear]  # latest first
    as_at_dates: list[date]  # latest first


@router.get("/companies")
def companies(session: ReportSession, access: CurrentAccess) -> list[Company]:
    ids = access.entities()
    health = {
        row.entity_id: row
        for row in session.execute(select(DATA_HEALTH).where(DATA_HEALTH.c.entity_id.in_(ids)))
    }
    checked = {}
    for link in session.scalars(
        select(A.EntitySource).where(A.EntitySource.entity_id.in_(ids)).order_by(A.EntitySource.id)
    ):
        checked.setdefault(link.entity_id, link)  # the first source of each company
    entities = session.scalars(select(A.Entity).where(A.Entity.id.in_(ids)).order_by(A.Entity.id))
    return [
        Company(
            id=e.id,
            code=e.code,
            name=e.name,
            books_from=e.books_from,
            fy_start_month=e.fy_start_month,
            health=DataHealth(
                last_sync_at=getattr(health.get(e.id), "last_sync_at", None),
                validation_status=getattr(health.get(e.id), "validation_status", None),
                validated_as_of=getattr(health.get(e.id), "validated_as_of", None),
                validated_at=getattr(health.get(e.id), "validated_at", None),
                source_name=_short_name(getattr(health.get(e.id), "source_name", None)),
                source_loaded=getattr(checked.get(e.id), "source_loaded", None),
                source_checked_at=getattr(checked.get(e.id), "source_checked_at", None),
                source_checked_by=getattr(checked.get(e.id), "source_checked_by", None),
            ),
        )
        for e in entities
    ]


@router.get("/periods")
def periods(
    session: ReportSession,
    access: CurrentAccess,
    company: list[int] | None = Query(default=None),  # noqa: B008
) -> Periods:
    ids = access.entities(company)
    first_month = (
        session.scalar(select(func.min(A.Entity.fy_start_month)).where(A.Entity.id.in_(ids))) or 4
    )
    first, last = session.execute(
        select(func.min(A.Voucher.voucher_date), func.max(A.Voucher.voucher_date)).where(
            A.Voucher.entity_id.in_(ids), A.Voucher.is_deleted.is_(False)
        )
    ).one()
    books = session.scalar(select(func.min(A.Entity.books_from)).where(A.Entity.id.in_(ids)))
    first = min(d for d in (first, books) if d is not None) if (first or books) else None
    years = financial_years(first, last or first, first_month) if first else []
    dated = session.execute(
        select(StatementLine.as_of, func.count(func.distinct(StatementLine.entity_id)))
        .where(
            StatementLine.entity_id.in_(ids),
            StatementLine.figures == "ours",
            StatementLine.statement == "trial_balance",
        )
        .group_by(StatementLine.as_of)
    ).all()
    held_by_all = sorted((on for on, n in dated if n == len(ids)), reverse=True)
    return Periods(financial_years=years, as_at_dates=held_by_all)


def _short_name(name: str | None) -> str | None:
    """A source's name as people say it: "Tally (XML over HTTP)" -> "Tally"."""
    return name.split(" (", 1)[0] if name else None


def financial_years(first: date, last: date, start_month: int) -> list[FinancialYear]:
    """Every financial year from the one holding `first` to the one holding `last`, latest
    first."""
    start_year = first.year - (first.month < start_month)
    end_year = last.year - (last.month < start_month)
    years = []
    for year in range(end_year, start_year - 1, -1):
        start = date(year, start_month, 1)
        next_start = date(year + 1, start_month, 1)
        years.append(
            FinancialYear(
                start_year=year,
                label=f"FY {year}-{(year + 1) % 100:02d}",
                start=start,
                end=date.fromordinal(next_start.toordinal() - 1),
            )
        )
    return years
