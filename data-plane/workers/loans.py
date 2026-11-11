"""`./dev.ps1 loans`: the ledgers under Loans (Liability) of one company, and marking one as
short-term (F-RAT-008, F-BS-011; core/ratios.py).

By default Bank OD A/c ledgers and bank accounts in credit are short-term borrowings; the
other loans (Secured Loans, Unsecured Loans, term loans) aren't. A ledger marked short-term
(for example a cash-credit or working-capital loan booked under Secured Loans) counts as a
current liability in the current and quick ratios. Marks are stored by ledger id in
`short_term_borrowings`; every change is written to the audit log (AUD-001).

The list prints each ledger's id, name, group and closing balance at a date, so the
developer can decide which to mark. It is printed on the screen only: nothing is stored or
logged, and the source isn't contacted. It prints names and amounts in every environment
on purpose (the developer's request, 2026-11-11); Claude Code runs it on the test
environment only.
"""

from collections.abc import Callable
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from core.models import accounting as A  # noqa: N812
from core.models.base import utcnow
from core.models.system import AuditLog
from core.ratios import marked_ledgers
from core.statements import ledger_balances

Print = Callable[[str], None]
LOANS = "loans_liability"
BANK_OD = "bank_od_a_c"


def _groups(session: Session, entity_id: int) -> dict[str, tuple[str, str | None]]:
    """Group source key -> (name, predefined role)."""
    rows = session.execute(
        select(
            A.AccountGroup.source_key, A.AccountGroup.name, A.AccountGroup.predefined_role
        ).where(A.AccountGroup.entity_id == entity_id, A.AccountGroup.is_deleted.is_(False))
    )
    return {key: (name, role) for key, name, role in rows}


def _roles_above(session: Session, group_id: int | None) -> set[str]:
    """The predefined roles of a group and every group above it."""
    roles: set[str] = set()
    seen: set[int] = set()
    while group_id is not None and group_id not in seen:
        seen.add(group_id)
        group = session.get(A.AccountGroup, group_id)
        if group is None:
            break
        if group.predefined_role:
            roles.add(group.predefined_role)
        group_id = group.parent_id
    return roles


def _loan_ledgers(session: Session, entity_id: int, on: date) -> list[tuple]:
    """(id, name, group name, balance, under Bank OD A/c) of the ledgers under Loans
    (Liability) at any depth, by name."""
    groups = _groups(session, entity_id)
    found = []
    for ledger in ledger_balances(session, entity_id, on):
        roles = {groups[k][1] for k in ledger.groups if k in groups}
        if LOANS not in roles:
            continue
        group_name = groups[ledger.groups[0]][0] if ledger.groups else ""
        found.append((ledger.id, ledger.name, group_name, ledger.balance, BANK_OD in roles))
    return sorted(found, key=lambda row: row[1].lower())


def _amount(balance: Decimal) -> str:
    """1,23,456.00 Cr: the balance as the source shows it (debit positive)."""
    side = "Dr" if balance > 0 else "Cr"
    whole, cents = f"{abs(balance):.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    text = ",".join([*groups, tail]) if groups else tail
    return f"{text}.{cents} {side}" if balance else "0.00"


def list_loans(session: Session, entity_id: int, on: date, out: Print = print) -> int:
    """Prints the Loans (Liability) ledgers with their group, closing balance at the date and
    whether they count as short-term. Screen only."""
    marked = marked_ledgers(session, [entity_id])
    rows = _loan_ledgers(session, entity_id, on)
    out(
        f"Loans (Liability) ledgers of entity {entity_id} at {on:%d-%b-%Y} "
        "(screen only; not stored)"
    )
    if not rows:
        out("  none")
        return 0
    out(f"  {'Id':>6}  {'Short-term':<22}  {'Closing balance':>20}  Group  /  Ledger")
    for ledger_id, name, group, balance, bank_od in rows:
        state = "yes (Bank OD A/c)" if bank_od else "yes (marked)" if ledger_id in marked else "no"
        out(f"  {ledger_id:>6}  {state:<22}  {_amount(balance):>20}  {group}  /  {name}")
    out(
        "Mark a ledger: ./dev.ps1 loans mark -Ledger <id>; "
        "clear it: ./dev.ps1 loans clear -Ledger <id>"
    )
    return 0


def set_short_term(session: Session, ledger_id: int, short_term: bool, out: Print = print) -> int:
    """Marks a ledger under Loans (Liability) as short-term, or clears the mark; audited. 2 for
    a ledger that isn't one (or is under Bank OD A/c, short-term already)."""
    ledger = session.get(A.Ledger, ledger_id)
    if ledger is None or ledger.is_deleted:
        out(f"No ledger {ledger_id}.")
        return 2
    roles = _roles_above(session, ledger.group_id)
    if LOANS not in roles:
        out(f"Ledger {ledger_id} isn't under Loans (Liability); nothing changed.")
        return 2
    if BANK_OD in roles:
        out(f"Ledger {ledger_id} is under Bank OD A/c: short-term already; nothing changed.")
        return 2
    existing = session.scalar(
        select(A.ShortTermBorrowing).where(A.ShortTermBorrowing.ledger_id == ledger_id)
    )
    if (existing is not None) == short_term:
        out(
            f"Ledger {ledger_id}: already {'marked' if short_term else 'not marked'}; "
            "nothing changed"
        )
        return 0
    if short_term:
        session.add(A.ShortTermBorrowing(entity_id=ledger.entity_id, ledger_id=ledger_id))
    else:
        session.execute(
            delete(A.ShortTermBorrowing).where(A.ShortTermBorrowing.ledger_id == ledger_id)
        )
    session.add(
        AuditLog(
            occurred_at=utcnow(),
            action="short_term_borrowing_marked" if short_term else "short_term_borrowing_cleared",
            object_type="ledger",
            object_id=str(ledger_id),
            entity_id=ledger.entity_id,
            details={"via": "dev.ps1 loans"},
        )
    )
    session.commit()
    out(f"Ledger {ledger_id}: {'marked as short-term' if short_term else 'no longer short-term'}")
    return 0
