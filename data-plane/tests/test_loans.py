"""`./dev.ps1 loans` (workers/loans.py): a company's Loans (Liability) ledgers with their group
and closing balance at a date, and marking one as a short-term borrowing (F-RAT-008,
F-BS-011), audited. On the test company's netting recording, whose Term Loan (12,000 Cr) is
under Loans (Liability); a synthetic Bank OD ledger added to it."""

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import accounting as A  # noqa: N812
from core.models import system as S  # noqa: N812
from core.models.base import utcnow
from tests.test_statements import netting_books  # noqa: F401  (a fixture)
from workers.loans import list_loans, set_short_term

AS_OF = date(2026, 10, 2)


def _entity(db: Session) -> int:
    return db.scalars(select(A.Entity)).one().id


def _ledger(db: Session, name: str) -> A.Ledger:
    return db.scalars(select(A.Ledger).where(A.Ledger.name == name)).one()


def _printed(call) -> list[str]:  # noqa: ANN001
    lines: list[str] = []
    assert call(lines.append) in (0, 2)
    return lines


def test_lists_the_loans_with_group_balance_and_state(
    db: Session,
    netting_books: S.Connection,  # noqa: F811
) -> None:
    entity_id = _entity(db)
    loan = _ledger(db, "Term Loan")
    od_group = db.scalars(select(A.AccountGroup).where(A.AccountGroup.name == "Bank OD A/c")).one()
    db.add(
        A.Ledger(
            entity_id=entity_id, group_id=od_group.id, name="Synthetic OD",
            ledger_kind=loan.ledger_kind,
            opening_balance=Decimal("-250000"), source_key="synthetic-od", origin="manual",
            connection_id=loan.connection_id, created_at=utcnow(), updated_at=utcnow(),
        )
    )  # fmt: skip
    db.commit()
    lines = _printed(lambda out: list_loans(db, entity_id, AS_OF, out))
    assert "screen only; not stored" in lines[0]
    rows = [line for line in lines if " / " in line and line.split()[0].isdigit()]
    assert len(rows) == 2  # the Term Loan and the Bank OD ledger; nothing else
    od = next(r for r in rows if "Synthetic OD" in r)
    assert "yes (Bank OD A/c)" in od and "2,50,000.00 Cr" in od and "Bank OD A/c  /" in od
    term = next(r for r in rows if "Term Loan" in r)
    assert (
        f"{loan.id:>6}  no " in term and "12,000.00 Cr" in term and "Loans (Liability)  /" in term
    )


def test_marking_a_loan_is_audited_and_shown(
    db: Session,
    netting_books: S.Connection,  # noqa: F811
) -> None:
    entity_id = _entity(db)
    loan = _ledger(db, "Term Loan")
    assert _printed(lambda out: set_short_term(db, loan.id, True, out)) == [
        f"Ledger {loan.id}: marked as short-term"
    ]
    assert db.scalars(select(A.ShortTermBorrowing.ledger_id)).all() == [loan.id]
    lines = _printed(lambda out: list_loans(db, entity_id, AS_OF, out))
    assert any("yes (marked)" in line and "Term Loan" in line for line in lines)
    # Marking it again changes nothing; clearing it removes the mark. Both changes audited.
    assert "already marked" in _printed(lambda out: set_short_term(db, loan.id, True, out))[0]
    set_short_term(db, loan.id, False, lambda _: None)
    assert db.scalars(select(A.ShortTermBorrowing)).all() == []
    actions = db.scalars(select(S.AuditLog.action).order_by(S.AuditLog.id)).all()
    assert actions == ["short_term_borrowing_marked", "short_term_borrowing_cleared"]
    audit = db.scalars(select(S.AuditLog)).first()
    assert (audit.object_type, audit.object_id, audit.entity_id) == (
        "ledger",
        str(loan.id),
        entity_id,
    )


def test_only_a_loan_ledger_can_be_marked(
    db: Session,
    netting_books: S.Connection,  # noqa: F811
) -> None:
    cash = _ledger(db, "Cash")
    lines = _printed(lambda out: set_short_term(db, cash.id, True, out))
    assert lines == [f"Ledger {cash.id} isn't under Loans (Liability); nothing changed."]
    assert _printed(lambda out: set_short_term(db, 999999, True, out)) == ["No ledger 999999."]
    assert db.scalars(select(A.ShortTermBorrowing)).all() == []
    assert db.scalars(select(S.AuditLog)).all() == []
