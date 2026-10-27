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


SHOWN = 8  # parts 2 and 3: the best combinations printed; the rest counted


def lines(label: str, f: fx_rules.Finding) -> list[str]:
    """The finding as printed: counts and rule names only. The last line is the decision:
    the combinations of part 3 matching every date, or none (ADR-043's time-box)."""
    kinds = ", ".join(f"{k} {n:,}" for k, n in sorted(f.rate_kinds.items())) or "none"
    out = [
        f"{label}: {f.dates:,} dates"
        + (f" ({f.dates_unreadable:,} without stored statements)" if f.dates_unreadable else "")
        + f"; {f.foreign_ledgers:,} foreign-currency ledgers the source revalues, "
        f"{f.other_ledgers_with_foreign_figures:,} base-currency ledgers with foreign figures, "
        f"in {f.groups:,} group(s); rates stored: {kinds}"
    ]
    if not f.foreign_ledgers:
        out.append(f"{label}: no foreign-currency ledgers: nothing to find")
        return out
    calibration = f.calibration()
    if calibration is not None:
        out.append(
            f"{label}: as `statements` lays them out today (the source's own per-ledger "
            f"figures): {_counts(calibration, f.dates)}"
        )
    out.append("  1. Per ledger, each rule against the source's own revalued balance:")
    for p in f.per_ledger:
        missing = f"; no rate at {p.no_rate:,}" if p.no_rate else ""
        out.append(
            f'    rule "{p.rule}": {p.exact:,} of {p.compared + p.no_rate:,} ledger-dates '
            f"to the paisa, {p.rupee:,} rounded to the rupee, {p.near:,} within 1{missing}"
        )
    out.append("  2. Layout, with the source's own per-ledger figures:")
    out += _best(f.layouts, f.dates, lambda r: f"{r.rule}, {r.variant}")
    out.append("  3. Computed, rule by rule:")
    out += _best(f.results, f.dates, lambda r: f'rule "{r.rule}", {r.variant}')
    every = [p.rule for p in f.per_ledger if p.compared and p.exact == p.compared + p.no_rate]
    out.append(
        f"{label}: per ledger, rules matching every ledger-date: "
        + "; ".join(f'"{name}"' for name in every)
        if every
        else f"{label}: per ledger, no rule matches every ledger-date"
    )
    laid = [r for r in f.layouts if _all(r, f.dates)]
    out.append(
        f"{label}: with the source's own per-ledger figures, layouts matching every date: "
        + ("; ".join(f"{r.rule}, {r.variant}" for r in laid) if laid else "none")
    )
    found = [r for r in f.results if _all(r, f.dates)]
    if found:
        names = "; ".join(f'"{r.rule}" ({r.variant})' for r in found)
        out.append(f"{label}: rules matching every date exactly: {names}")
    else:
        out.append(f"{label}: no rule matches every date exactly")
    return out


def _all(r: fx_rules.Result, dates: int) -> bool:
    return bool(dates) and r.groups_exact == r.forex_exact == dates


def _counts(r: fx_rules.Result, dates: int) -> str:
    missing = f"; no rate at {r.no_rate:,} ledger-dates" if r.no_rate else ""
    return (
        f"groups {r.groups_exact:,} of {dates:,} exact, {r.groups_near:,} within 1; "
        f"forex line {r.forex_exact:,} of {dates:,} exact, {r.forex_near:,} within 1{missing}"
    )


def _best(
    results: list[fx_rules.Result], dates: int, name: Callable[[fx_rules.Result], str]
) -> list[str]:
    out = [f"    {name(r)}: {_counts(r, dates)}" for r in results[:SHOWN]]
    if len(results) > SHOWN:
        out.append(f"    ({len(results) - SHOWN:,} more combinations, none matching more dates)")
    return out
