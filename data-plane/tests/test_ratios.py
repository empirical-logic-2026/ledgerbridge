"""The current ratio, quick ratio and debt to equity in the form of Schedule III (F-RAT-008 to
F-RAT-010; parts F-BS-007 to F-BS-009), against figures worked out by hand from Tally's own
Balance Sheet and ledger balances of LedgerBridge Test Co at 02-Oct-2026 (the netting
recording: tests/fixtures/tally/rules/statement_netting/integrated). Bank OD and the marked
loans, which the recording doesn't have, on synthetic ledgers added to it.

Tally's Balance Sheet at 02-Oct-2026 (balance_sheet_2026-10-02.xml):
    Capital Account 52,010 Cr; Loans (Liability) 12,000 Cr; Current Liabilities 23,089 Cr;
    Profit & Loss A/c 4,121 Dr; Fixed Assets 3,000 Dr; Current Assets 75,878 Dr.

Tally's ledger balances (ledger_balance_2026-10-02.xml), by side, worked out by hand:

Current assets (debit balances):
    Cash 26,059; Test Bank Current A/c 25,260; Security Deposit 12,000;
    debtors in debit: Alpha 5,100 + Beta 118 + Gamma 1,200 + Kilo 21 = 6,439;
    creditor in debit: Vendor Foxtrot Advance 700;
    other: Addable Dr 400 + Plain Dr 300 + Sub-ledger Dr 200 (advance groups under Current
    Assets) + Input CGST 1,170 + Input SGST 1,170 (Duties & Taxes in debit) = 3,240;
    closing stock (stock_value_2026-10-02.xml): 904 + 120 + 4,250 + 6 + 300 = 5,580.
    Total 26,059 + 25,260 + 12,000 + 6,439 + 700 + 3,240 + 5,580 = 79,278.

Current liabilities (credit balances):
    creditors in credit: Delta 1,500 + Epsilon 4,470 + Zeta 1,180 = 7,150;
    duties and taxes: Output CGST 1,809 + Output SGST 1,809 = 3,618;
    other: Salary Payable 15,361 + Addable Cr 150 + Plain Cr 120 + Sub-ledger Cr 90 = 15,721.
    Total 7,150 + 3,618 + 15,721 = 26,489. The Term Loan (Loans (Liability)) isn't current.

Ratios: current 79,278 / 26,489 = 2.99; quick (79,278 - 5,580) / 26,489 = 2.78;
debt to equity 12,000 / (52,010 - 4,121) = 0.25. Netting the groups as Tally's lines do
gave 75,878 / 23,089 = 3.29: by sign, the same 3,400 (700 + 2,340 + 360) moves to both
sides, so current assets less current liabilities stays Tally's 52,789.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import statements
from core.balance_sheet import position_ratios
from core.models import accounting as A  # noqa: N812
from core.models import system as S  # noqa: N812
from core.models.base import utcnow
from core.ratios import classify, position
from tests.stock_replay import NETTING
from tests.test_statements import _source, netting_books  # noqa: F401  (a fixture)

AS_OF = date(2026, 10, 2)
D = Decimal


@pytest.fixture
def stored(db: Session, netting_books: S.Connection) -> int:  # noqa: F811
    """The test company with Tally's statements stored at 02-Oct-2026; its entity id."""
    entity_id = db.scalars(select(A.Entity)).one().id
    statements.refresh(
        db, entity_id, netting_books.id, "live", _source("integrated", AS_OF, NETTING)
    )
    return entity_id


EQUITY = D("47889")  # Tally's Capital Account 52,010 Cr less the Profit & Loss A/c 4,121 Dr


def _ratios(db: Session, companies: list[int]) -> dict[str, Decimal | None]:
    """The three ratios from the parts at 02-Oct-2026; the Balance Sheet endpoint's
    (with the equity from the stored lines): tests/test_ratios_integration.py."""
    return position_ratios(position(db, companies, AS_OF), EQUITY)


def _ledger(db: Session, entity_id: int, name: str) -> A.Ledger:
    return db.scalars(
        select(A.Ledger).where(A.Ledger.entity_id == entity_id, A.Ledger.name == name)
    ).one()


def test_current_assets_and_liabilities_by_sign_match_the_hand_worked_figures(
    db: Session, stored: int
) -> None:
    found = position(db, [stored], AS_OF)
    assert dict(found.assets) == {
        "cash": D("26059"), "bank": D("25260"), "deposits": D("12000"),
        "receivables": D("6439"), "supplier_advances": D("700"),
        "other_assets": D("3240"), "stock": D("5580"),
    }  # fmt: skip
    assert dict(found.liabilities) == {
        "payables": D("7150"), "duties_taxes": D("3618"), "other_liabilities": D("15721"),
    }  # fmt: skip
    assert found.current_assets == D("79278")
    assert found.current_liabilities == D("26489")
    assert dict(found.borrowings) == {"long_term_borrowings": D("12000")}
    # Tally's lines net each group; by sign the same amount moves to both sides.
    assert found.current_assets - found.current_liabilities == D("75878") - D("23089")


def test_the_ratios_follow_schedule_iii(db: Session, stored: int) -> None:
    ratios = _ratios(db, [stored])
    assert ratios["current_ratio"] == D("2.99")  # netted lines gave 3.29
    assert ratios["quick_ratio"] == D("2.78")
    assert ratios["debt_to_equity"] == D("0.25")


def test_a_loan_marked_short_term_is_a_current_liability(db: Session, stored: int) -> None:
    loan = _ledger(db, stored, "Term Loan")
    db.add(A.ShortTermBorrowing(entity_id=stored, ledger_id=loan.id))
    db.commit()
    found = position(db, [stored], AS_OF)
    assert found.marked == 1
    assert found.liabilities["short_term_borrowings"] == D("12000")
    assert dict(found.borrowings) == {"short_term_borrowings": D("12000")}  # still debt
    ratios = _ratios(db, [stored])
    assert ratios["current_ratio"] == D("2.06")  # 79,278 / (26,489 + 12,000)
    assert ratios["debt_to_equity"] == D("0.25")


def _synthetic_ledger(db: Session, entity_id: int, group: str, name: str, opening: str) -> None:
    """A synthetic ledger (not in the recording) under one of the company's groups, with
    an opening balance (debit positive) and no entries."""
    group_row = db.scalars(
        select(A.AccountGroup).where(
            A.AccountGroup.entity_id == entity_id, A.AccountGroup.name == group
        )
    ).one()
    model = _ledger(db, entity_id, "Term Loan")
    db.add(
        A.Ledger(
            entity_id=entity_id, group_id=group_row.id, name=name, ledger_kind=model.ledger_kind,
            opening_balance=D(opening), source_key=f"synthetic-{name}", origin="manual",
            connection_id=model.connection_id, created_at=utcnow(), updated_at=utcnow(),
        )
    )  # fmt: skip
    db.commit()


def test_bank_od_and_a_bank_in_credit_are_short_term_borrowings(db: Session, stored: int) -> None:
    _synthetic_ledger(db, stored, "Bank OD A/c", "Synthetic OD", "-8000")
    _synthetic_ledger(db, stored, "Bank Accounts", "Synthetic Overdrawn", "-2000")
    found = position(db, [stored], AS_OF)
    assert found.liabilities["short_term_borrowings"] == D("10000")
    assert found.borrowings["short_term_borrowings"] == D("10000")
    assert found.assets["bank"] == D("25260")  # the bank in credit isn't netted against it
    ratios = _ratios(db, [stored])
    assert ratios["current_ratio"] == D("2.17")  # 79,278 / (26,489 + 10,000) = 2.1727
    assert ratios["debt_to_equity"] == D("0.46")  # (12,000 + 10,000) / 47,889


@pytest.mark.parametrize(
    ("roles", "balance", "marked", "placed"),
    [
        ({"current_assets", "sundry_debtors"}, "-50", False, ("liability", "customer_advances")),
        ({"current_liabilities", "sundry_creditors"}, "70", False, ("asset", "supplier_advances")),
        (
            {"loans_liability", "secured_loans"},
            "-900",
            False,
            ("borrowing", "long_term_borrowings"),
        ),
        (
            {"loans_liability", "secured_loans"},
            "-900",
            True,
            ("liability", "short_term_borrowings"),
        ),
        ({"loans_liability", "bank_od_a_c"}, "-900", False, ("liability", "short_term_borrowings")),
        ({"loans_liability", "bank_od_a_c"}, "40", False, ("asset", "bank")),
        ({"current_assets", "stock_in_hand"}, "500", False, None),
        ({"current_liabilities", "provisions"}, "-30", False, ("liability", "provisions")),
        ({"fixed_assets"}, "100", False, None),
        ({"current_assets", "cash_in_hand"}, "0", False, None),
    ],
)
def test_each_balance_goes_to_its_side(
    roles: set[str], balance: str, marked: bool, placed: tuple[str, str] | None
) -> None:
    assert classify(roles, D(balance), marked) == placed
