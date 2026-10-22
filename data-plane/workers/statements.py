"""Filling the stock values and statements at every month end and year end (ADR-033,
ADR-040): `./dev.ps1 statements`.

Where it fits: validation stores and checks the statements for the dates it validates (the
as-of date and each year end); this fills every month end in between, from the books'
beginning to today, so the reporting views have every month. For each date it reads the
source's statements (read-only), then core/statements.py stores the source's figures,
builds ours and compares them. Output is counts and the statements' names only: never
labels, names or amounts.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy.orm import Session

from connectors.base import Connector, SourceEntity, SourceStatements
from core import statements
from core.dates import DateRule
from core.models import Connection
from core.validation import financial_year_ends

Progress = Callable[[str], None]


def month_ends(start: date, end: date) -> list[date]:
    """The last day of every month from `start`'s month up to `end` (inclusive)."""
    found, current = [], start.replace(day=1)
    while True:
        last = (current.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        if last > end:
            return found
        found.append(last)
        current = last + timedelta(days=1)


def statement_dates(
    books_from: date, fy_start_month: int, as_of: date, rule: DateRule, start: date | None = None
) -> list[date]:
    """Every month end and financial year end from the books' beginning (or `start`) to
    `as_of`, and `as_of` itself, each moved to the source's next reliable date for
    statements (Educational mode: a 30th becomes the 2nd, core/dates.py), never after
    `as_of`."""
    wanted = {
        *month_ends(start or books_from, as_of),
        *financial_year_ends(books_from, fy_start_month, as_of),
    }
    used = {rule.for_statements(on) for on in wanted if on >= (start or books_from)}
    return sorted({on for on in used if on <= as_of} | {as_of})


@dataclass
class FillResult:
    dates: int = 0
    differing: list[date] = field(default_factory=list)  # dates whose statements differ
    by_statement: dict[str, int] = field(default_factory=dict)  # statement -> differences
    unreadable: int = 0
    not_offered: bool = False


def fill(
    session: Session,
    connection: Connection,
    connector: Connector,
    entity: SourceEntity,
    entity_id: int,
    dates: list[date],
    progress: Progress,
) -> FillResult:
    """Reads, stores, builds and compares the statements at each date."""
    result = FillResult()
    read = getattr(connector, "source_statements", None)
    if read is None:
        result.not_offered = True
        return result
    origin = str(connection.config.get("origin", "live"))
    for on in dates:
        try:
            source: SourceStatements | None = read(entity, on)
        except Exception as exc:  # noqa: BLE001 - counted; the next date is tried
            result.unreadable += 1
            progress(f"{on}: the source's statements couldn't be read ({type(exc).__name__})")
            continue
        if source is None:
            result.not_offered = True
            return result
        compared = statements.refresh(session, entity_id, connection.id, origin, source)
        result.dates += 1
        if compared.differences:
            result.differing.append(on)
            for difference in compared.differences:
                count = result.by_statement.get(difference.statement, 0)
                result.by_statement[difference.statement] = count + 1
        progress(
            f"{on}: {compared.compared:,} lines and totals compared, "
            f"{len(compared.differences):,} differ"
        )
    return result
