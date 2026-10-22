"""Stock ledgers at the source's stock value, Tally's own totals and effective dates
(ADR-033; pilot results 2026-10-15, checked on the test company the same day):

1. In two pilot companies Tally reported the Stock-in-Hand ledger at the closing stock
   value at every date. Validation compares such ledgers with that value; on the test
   company the ledger keeps its own opening and is compared ledger by ledger as before.
2. Tally's primary groups' openings are its trial balance's: their total is its difference
   in opening balances. With accounts integrated with inventory its Stock-in-Hand group
   holds the stock value it uses.
3. Tally keeps an effective date per voucher but counts balances by the voucher's date.
"""

import xml.etree.ElementTree as ET  # noqa: N817
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from connectors.base import SourceBalances
from connectors.tally import mapping, parser
from core.models import accounting as A  # noqa: N812
from core.models import system as S  # noqa: N812
from core.validation import Validator
from tests.conftest import FIXTURES
from tests.test_job_work import STOCK_LEDGER, YEAR_END, _replaying, _test_company

EFFECTIVE = FIXTURES / "tally" / "rules" / "effective_dates"
AS_OF = date(2026, 10, 2)


# --- 1. stock ledgers at the source's stock value -------------------------------------------


def _validate(db: Session, connection: S.Connection, closing_stock: Decimal):  # noqa: ANN202
    entity_id = db.scalar(select(A.Entity.id))
    validator = Validator(db, entity_id, AS_OF, Decimal(0), connection.id)
    ours = {lb.name: lb for lb in validator.ledger_balances(AS_OF)}
    stock_ledger = ours["Salary Payable"]
    ledgers = {lb.source_key: lb.balance for lb in ours.values()}
    ledgers[stock_ledger.source_key] = Decimal(999)  # the source: the stock's value
    source = SourceBalances(
        AS_OF,
        ledgers,
        opening_stock=closing_stock,
        closing_stock=closing_stock,
        stock_ledgers=frozenset({stock_ledger.source_key}),
        integrated=True,
    )
    report = Validator(db, entity_id, AS_OF, Decimal(0), connection.id).run(source)
    return report, stock_ledger


def test_a_stock_ledger_at_the_closing_stock_value_is_compared_with_it(
    db: Session, synced: S.Connection
) -> None:
    report, stock_ledger = _validate(db, synced, Decimal(999))
    codes = [f.check_code for f in report.findings]
    assert "closing_mismatch" not in codes
    note = next(f for f in report.findings if f.check_code == "stock_ledger_at_stock_value")
    assert note.severity == "info"
    assert (note.expected, note.actual) == (Decimal(999), Decimal(999))
    assert f"as of {AS_OF}" in note.message


def test_a_stock_ledger_at_another_value_still_fails(db: Session, synced: S.Connection) -> None:
    report, stock_ledger = _validate(db, synced, Decimal(500))
    failed = [f for f in report.findings if f.check_code == "closing_mismatch"]
    assert [f.object_id for f in failed] == [str(stock_ledger.id)]
    assert "stock_ledger_at_stock_value" not in [f.check_code for f in report.findings]


# --- 2. Tally's own totals ------------------------------------------------------------------


def test_tallys_own_group_totals_give_the_stock_and_the_opening_difference() -> None:
    """Recorded from the test company: the Stock-in-Hand group (renamed "Inventories")
    holds 2,010 at the books' beginning and 5,580 at the year end, the items' values; the
    primary groups' openings total zero, as Tally's trial balance shows."""
    connector = _replaying()
    balances = connector.closing_balances(_test_company(connector), YEAR_END)
    assert (balances.opening_stock, balances.closing_stock) == (Decimal(2010), Decimal(5580))
    assert balances.item_opening_value == Decimal(2010)
    assert balances.opening_difference == 0


def test_the_opening_difference_is_the_trial_balances() -> None:
    """A difference in Tally's own primary group openings is its difference in opening
    balances, whatever the ledgers' and items' openings add up to."""
    text = (STOCK_LEDGER / "group_balances.xml").read_text(encoding="utf-8")
    capital = '<OPENINGBALANCE TYPE="Amount">52010.00</OPENINGBALANCE>'  # Capital Account
    assert text.count(capital) == 1
    changed = text.replace(capital, capital.replace("52010", "52017"))
    connector = _replaying(groups=changed)
    balances = connector.closing_balances(_test_company(connector), YEAR_END)
    assert balances.opening_difference == Decimal(-7)  # 7 more credit: canonical -7


# --- 3. effective dates ---------------------------------------------------------------------


def _vouchers() -> list:  # noqa: ANN202
    root = parser.parse_response((EFFECTIVE / "vouchers.xml").read_bytes())
    return [mapping.voucher(v, parser.source_key(v)) for v in parser.objects(root, "VOUCHER")]


def _balance(name: str, on: date) -> Decimal:
    root = ET.parse(EFFECTIVE / f"ledger_balances_{on}.xml").getroot()
    ledger = next(x for x in root.iter("LEDGER") if parser.object_name(x) == name)
    return -Decimal((ledger.findtext("CLOSINGBALANCE") or "0").strip())


def test_the_effective_date_is_stored() -> None:
    effective = {(v.voucher_date, v.effective_date, v.is_optional) for v in _vouchers()}
    assert (date(2026, 8, 31), date(2026, 9, 1), False) in effective
    assert (date(2026, 9, 1), date(2026, 8, 31), False) in effective
    assert (date(2026, 8, 31), date(2026, 9, 1), True) in effective


def test_tally_counts_by_the_voucher_date_not_the_effective_date() -> None:
    """Recorded from the test company: journals dated 31 August (effective 1 September, 11)
    and 1 September (effective 31 August, 13), an optional one, and sales likewise.
    Between 31 August and 1 September Tally's Rent moved by the journal dated 1 September."""
    vouchers = [v for v in _vouchers() if not v.is_optional]

    def rent(by: str, on: date) -> Decimal:
        return sum(
            (line.amount for v in vouchers if getattr(v, by) == on
             for line in v.lines if line.ledger_name == "Rent"),
            Decimal(0),
        )  # fmt: skip

    moved = _balance("Rent", date(2026, 9, 1)) - _balance("Rent", date(2026, 8, 31))
    assert moved == rent("voucher_date", date(2026, 9, 1)) == Decimal(13)
    assert moved != rent("effective_date", date(2026, 9, 1))
    # The sale dated 31 August (effective 1 September) is in the party's balance on 31 August.
    assert _balance("Customer Beta Retail", date(2026, 8, 31)) == _balance(
        "Customer Beta Retail", date(2026, 9, 1)
    )


def test_vouchers_with_the_same_dates_are_each_counted(db: Session, synced: S.Connection) -> None:
    """`validate analyse` counts the vouchers whose effective date isn't their date: two
    vouchers with the same two dates are two vouchers (they used to count as one)."""
    from workers.analyse import Analyser

    cash = db.scalars(select(A.Ledger).where(A.Ledger.name == "Cash")).one()
    vouchers = db.scalars(
        select(A.Voucher)
        .join(A.VoucherLine, A.VoucherLine.voucher_id == A.Voucher.id)
        .where(A.VoucherLine.ledger_id == cash.id)
        .distinct()
        .limit(2)
    ).all()
    assert len(vouchers) == 2
    for voucher in vouchers:
        voucher.voucher_date, voucher.effective_date = date(2026, 5, 10), date(2026, 6, 1)
    db.commit()
    analyser = object.__new__(Analyser)
    analyser.session, analyser.entity_id = db, cash.entity_id
    analyser._effective_known = True
    analyser._checked = lambda key: []  # no dates compared
    found = analyser._effective_across(cash.source_key, cash.id)
    assert found is not None and found.startswith(
        "vouchers whose effective date isn't their date 2,"
    )
