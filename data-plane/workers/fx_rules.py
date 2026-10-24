"""`./dev.ps1 validate fx-rules`: which revaluation rule the source's statements follow, per
company (ADR-043; core/fx_rules.py). Counts only, never names or amounts.

Where it fits: run after `./dev.ps1 statements` stored the source's statements at every month
end. For each company it checks that the company is loaded (LB-SYNC-011), reads the source's
group netting setting once (read-only), then lets core/fx_rules.py lay our statements out
again under each candidate rule and count the dates where the groups holding foreign-currency
ledgers and the forex line equal the source's.
"""

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from connectors.base import Connector, SourceEntity
from core import fx_rules
from core.models.reporting import StatementLine as LineRow
from workers.entities import ensure_loaded

Print = Callable[[str], None]


def run(
    session: Session,
    connector: Connector,
    entities: list[tuple[SourceEntity, int, str]],
    out: Print = print,
) -> int:
    """For each (entity, entity id, label): the finder's counts. 0 unless no company has
    stored statements to test against (2)."""
    tested = 0
    for entity, entity_id, label in entities:
        ensure_loaded(connector, entity)
        netted = _netted(connector, entity, label, out)
        dates = sorted(
            session.scalars(
                select(LineRow.as_of)
                .where(LineRow.entity_id == entity_id, LineRow.figures == "source")
                .distinct()
            )
        )
        if not dates:
            out(f"{label}: no statements stored yet; run ./dev.ps1 statements first")
            continue
        tested += 1
        for line in lines(label, fx_rules.find(session, entity_id, dates, netted)):
            out(line)
    return 0 if tested else 2


def _netted(connector: Connector, entity: SourceEntity, label: str, out: Print) -> frozenset[str]:
    """The groups the source nets for reporting (read-only); none when it can't say, which
    is said, since it changes how a group line splits into debit and credit."""
    read = getattr(connector, "netted_groups", None)
    if read is None:
        return frozenset()
    try:
        return frozenset(read(entity))
    except Exception as exc:  # noqa: BLE001 - reported; the finder still runs
        out(
            f"{label}: the source's group netting setting couldn't be read "
            f"({type(exc).__name__}); every group is split ledger by ledger"
        )
        return frozenset()


def lines(label: str, f: fx_rules.Finding) -> list[str]:
    """The finding as printed: counts and rule names only."""
    kinds = ", ".join(f"{k} {n:,}" for k, n in sorted(f.rate_kinds.items())) or "none"
    out = [
        f"{label}: {f.dates:,} dates"
        + (f" ({f.dates_unreadable:,} without stored statements)" if f.dates_unreadable else "")
        + f"; {f.foreign_ledgers:,} foreign-currency ledgers the source revalues, "
        f"{f.other_ledgers_with_foreign_figures:,} base-currency ledgers with foreign figures, "
        f"in {f.groups:,} group(s); rates stored: {kinds}"
    ]
    for r in f.results:
        missing = f"; no rate at {r.no_rate:,} ledger-dates" if r.no_rate else ""
        out.append(
            f'  rule "{r.rule}" ({r.variant}): groups {r.groups_exact:,} of {f.dates:,} exact, '
            f"{r.groups_near:,} within 1; forex line {r.forex_exact:,} of {f.dates:,} exact, "
            f"{r.forex_near:,} within 1{missing}"
        )
    full = [r for r in f.results if r.groups_exact == r.forex_exact == f.dates and f.dates]
    calibrated = any(r.rule == fx_rules.CALIBRATION for r in full)
    out.append(
        f"{label}: calibration "
        + (
            "reproduces the source at every date"
            if calibrated
            else "doesn't reproduce the source at every date: the counts below it can't be trusted"
        )
    )
    full = [r for r in full if r.rule != fx_rules.CALIBRATION]
    if full:
        names = "; ".join(f'"{r.rule}" ({r.variant})' for r in full)
        out.append(f"{label}: rules matching every date exactly: {names}")
    else:
        out.append(f"{label}: no rule matches every date exactly")
    return out
