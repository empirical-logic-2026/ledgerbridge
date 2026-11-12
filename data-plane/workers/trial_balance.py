"""`./dev.ps1 trial-balance`: one company's Trial Balance at a date, laid out as Tally's
(Particulars, Debit, Credit, the totals), so the developer can hold it beside Tally's own
on the same date (ADR-055; core/trial_balance.py builds it, the same as the page).

The date is the last stored statement date on or before the one asked for (the statements
command stores them); the Trial Balance is for the financial year that date falls in, as
Tally opens it. `--detailed` adds each group's sub-groups and ledgers, as Tally's Alt+F1.

Printed on the screen only: nothing is stored or logged, and the source isn't contacted. It
prints names and amounts in every environment on purpose (the developer's request,
2026-11-12, for the pilot comparison; like `loans`); Claude Code runs it on the test
environment only.
"""

from collections.abc import Callable
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from core.report_periods import stored_dates
from core.trial_balance import TrialBalance, trial_balance

Print = Callable[[str], None]
WIDTH = 44  # the Particulars column
INDENT = 2  # per level of the tree


def print_trial_balance(
    session: Session, entity_id: int, name: str, on: date, detailed: bool, out: Print = print
) -> int:
    """Prints the Trial Balance; 0 when it balances, 1 when it doesn't, 2 without one."""
    dates = sorted(d for d in stored_dates(session, [entity_id]) if d <= on)
    if not dates:
        out(f"No statement is stored on or before {on:%d-%b-%Y}: run ./dev.ps1 statements.")
        return 2
    found = trial_balance(session, [entity_id], dates[-1])
    if found.reason:
        out(f"No Trial Balance: {found.reason}.")
        return 2
    _header(found, name, out)
    for row in found.rows:
        if row.kind == "difference" or (not detailed and row.depth > 0):
            continue
        if not (row.debit or row.credit):
            continue
        label = " " * (INDENT * row.depth) + row.label
        out(_line(label, row.debit, row.credit))
    out("-" * (WIDTH + 36))
    out(_line("Total", found.debit, found.credit))
    difference = found.difference
    if difference is not None:
        out(_line(difference.label, difference.debit, difference.credit))
        out(_line("Grand Total", found.debit + difference.debit, found.credit + difference.credit))
        out("  (Tally's exported Trial Balance has no such line: compare the totals above.)")
    if found.settings_missing:
        out("Note: run ./dev.ps1 statements once: the groups netted for reporting and the profit")
        out("of earlier years are read with the statements (until then they may differ).")
    return 0 if difference is None else 1


def _header(found: TrialBalance, name: str, out: Print) -> None:
    start = found.year_start
    period = f"{start:%d-%b-%Y}" if start else "the books' beginning"
    out(f"Trial Balance of {name}")
    out(f"From {period} to {found.as_of:%d-%b-%Y} (screen only; not stored)")
    out(f"{'Particulars':<{WIDTH}}{'Debit':>18}{'Credit':>18}")
    out("-" * (WIDTH + 36))


def _line(label: str, debit: Decimal, credit: Decimal) -> str:
    shown = label if len(label) <= WIDTH - 1 else label[: WIDTH - 2] + "…"
    return f"{shown:<{WIDTH}}{_amount(debit):>18}{_amount(credit):>18}"


def _amount(value: Decimal) -> str:
    return f"{value:,.2f}" if value else ""
