"""`./dev.ps1 validate monthly-sales`: monthly sales proven against the source's own Sales
Accounts figure, per company (RPT-013; core/monthly_sales.py). Reads the database only:
TallyPrime needn't be running. Counts and dates only, never names or amounts.

Exit codes: 0 every window matches (warnings may be printed), 1 a window differs, 2 refused
(no stored statements, or statements older than the latest sync or transform: run
`./dev.ps1 statements` first).
"""

from collections.abc import Callable

from sqlalchemy.orm import Session

from core import monthly_sales
from core.models import accounting as A  # noqa: N812
from core.problems import title

Print = Callable[[str], None]
LISTED = 12  # differing windows listed by their dates; the rest counted


def run(
    session: Session,
    entities: list[tuple[int, str]],
    out: Print = print,
    daily: monthly_sales.Daily = monthly_sales.daily_from_view,
) -> int:
    """For each (entity id, label): refuse if its stored statements are stale, else the
    check's counts. The worst exit code of all."""
    code = 0
    for entity_id, label in entities:
        code = max(code, _entity(session, entity_id, label, out, daily))
    return code


def _entity(
    session: Session, entity_id: int, label: str, out: Print, daily: monthly_sales.Daily
) -> int:
    entity = session.get(A.Entity, entity_id)
    if entity is None or entity.books_from is None:
        out(f"{label}: no books-from date stored; sync the company first")
        return 2
    old = monthly_sales.stale(session, entity_id)
    if old is not None:
        out(
            f"{label}: refused: the stored statements (oldest refreshed "
            f"{old.refreshed:%Y-%m-%d %H:%M} UTC) are older than {old.run_type} run "
            f"{old.run_id} (finished {old.finished:%Y-%m-%d %H:%M} UTC) "
            f"[{title('statements_older_than_data')}]: run ./dev.ps1 statements first"
        )
        return 2
    finding = monthly_sales.check(session, entity_id, entity.books_from, daily)
    group = finding.group
    if not group.found:
        out(
            f"{label}: the source's Sales Accounts group wasn't found "
            f"[{title('sales_group_not_found')}]; nothing compared"
        )
        return 1
    out(
        f"{label}: Sales Accounts group found (the source's own, renamed or not): "
        f"{group.sub_groups:,} sub-groups, {len(group.ledgers):,} ledgers"
    )
    if group.outside:
        out(
            f"  WARNING {title('sales_ledgers_outside_group')}: {group.outside:,} ledgers "
            "mapped to sale of goods (4110) with entries sit outside it: not in the report"
        )
    else:
        out("  cross-check: no ledger mapped to sale of goods (4110) outside it (OK)")
    if group.with_opening:
        out(f"  WARNING {title('sales_ledger_openings')}: {group.with_opening:,} ledgers")
    if not finding.stored_dates:
        out(f"{label}: no statements stored yet; run ./dev.ps1 statements first")
        return 2
    return _windows(finding, label, out)


def _windows(finding: monthly_sales.Finding, label: str, out: Print) -> int:
    differing = len(finding.differing)
    line = (
        f"{label}: {finding.windows:,} periods compared from {finding.first} to {finding.last} "
        f"({finding.exact_months:,} of them exact calendar months; {finding.stored_dates:,} "
        f"stored dates), {differing:,} differ"
    )
    if finding.months_after:
        line += f"; {finding.months_after:,} months with sales after the last stored date"
    if not differing:
        out(f"{line} (OK)")
        return 0
    out(f"{line} [{title('monthly_sales_mismatch')}]")
    for w in finding.differing[:LISTED]:
        out(f"  differs: {w.start} to {w.end}")
    if differing > LISTED:
        out(f"  ... and {differing - LISTED:,} more periods")
    return 1
