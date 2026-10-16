"""Foreign-currency ledgers (VAL-013, ADR-035; pilot 2026-10-16): Tally reports such a
ledger's closing balance, and its group totals, at current rates; its trial balance shows
the difference to the rupee amounts entered as "Unadjusted Forex Gain/Loss", and its Ledger
Vouchers show the amounts entered. Validation compares the foreign-currency ledgers with
that book value; each line keeps its foreign amount."""

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from connectors.base import SourceBalances
from connectors.tally.connector import TallyConnector, _foreign, report_lines
from connectors.tally.signs import tally_amount, tally_foreign_amount
from core.models import accounting as A  # noqa: N812
from core.models import system as S  # noqa: N812
from core.validation import Validator
from tests.conftest import FIXTURES

AS_OF = date(2026, 10, 2)
FOREX_FIXTURES = FIXTURES / "tally" / "rules" / "forex"
FOREX = "-$100.00 @ ₹ 82.00/$ = -₹ 8,200.00"


def test_a_foreign_amount_keeps_both_parts() -> None:
    assert tally_amount(FOREX) == Decimal("-8200.00")
    assert tally_foreign_amount(FOREX) == Decimal("-100.00")
    assert tally_foreign_amount("-8200.00") is None


def test_foreign_ledgers_are_those_not_in_the_base_currency() -> None:
    """Tally exports the rupee sign as "?"; the base currency is that of the ledgers
    directly under Primary (Profit & Loss A/c)."""
    currencies = {"pl": "?", "cash": "?", "usd": "$", "eur": "EUR", "old": ""}
    assert _foreign(currencies, ["pl"]) == {"usd", "eur"}
    assert _foreign({"a": "?", "b": "?", "usd": "$"}, []) == {"usd"}  # most ledgers' currency


def _replaying() -> TallyConnector:
    """Answered by the responses recorded from the test company (2026-10-16): a US dollar
    customer with a sale of Rs 8,200 entered without a dollar amount."""
    import httpx

    files = {
        "LBCompanies": "companies.xml",
        "LBGroupBalances": "group_balances.xml",
        "LBLedgerBalances": "ledger_balances.xml",
        "LBStockValues": "stock_values.xml",
        "Trial Balance": "trial_balance.xml",
    }

    def answer(request: httpx.Request) -> httpx.Response:
        name = request.content.decode().split("<ID>")[1].split("</ID>")[0]
        return httpx.Response(200, content=(FOREX_FIXTURES / files[name]).read_bytes())

    return TallyConnector.from_config(
        {"url": "http://tally.test:9000"}, transport=httpx.MockTransport(answer)
    )


def test_the_book_value_is_the_revalued_balance_plus_the_unadjusted_forex() -> None:
    """Tally values the dollar customer at its dollar amount ($0, so Rs 0) in its closing
    balance and in its group totals, and shows the Rs 8,200 entered as "Unadjusted Forex
    Gain/Loss" in its trial balance: the book value is their sum."""
    connector = _replaying()
    (entity,) = connector.list_entities()
    balances = connector.closing_balances(entity, AS_OF)
    (key,) = balances.foreign_ledgers
    assert balances.ledgers[key] == 0
    assert balances.book_values == {frozenset({key}): Decimal("8200.00")}
    lines = dict(report_lines((FOREX_FIXTURES / "trial_balance.xml").read_bytes()))
    assert lines["Unadjusted Forex Gain/Loss"] == Decimal("8200.00")  # a debit


def _validate(db: Session, connection: S.Connection, book: Decimal):  # noqa: ANN202
    entity_id = db.scalar(select(A.Entity.id))
    ours = {
        lb.name: lb
        for lb in Validator(db, entity_id, AS_OF, Decimal(0), connection.id).ledger_balances(AS_OF)
    }
    customer = ours["Customer Beta Retail"]
    ledgers = {lb.source_key: lb.balance for lb in ours.values()}
    ledgers[customer.source_key] += Decimal("123.45")  # revalued at current rates
    source = SourceBalances(
        AS_OF,
        ledgers,
        foreign_ledgers=frozenset({customer.source_key}),
        book_values={frozenset({customer.source_key}): book},
    )
    report = Validator(db, entity_id, AS_OF, Decimal(0), connection.id).run(source)
    return report, customer


def test_a_foreign_ledger_is_compared_with_the_book_value(
    db: Session, synced: S.Connection
) -> None:
    entity_id = db.scalar(select(A.Entity.id))
    balance = next(
        lb.balance
        for lb in Validator(db, entity_id, AS_OF).ledger_balances(AS_OF)
        if lb.name == "Customer Beta Retail"
    )
    report, _ = _validate(db, synced, balance)
    codes = [f.check_code for f in report.findings]
    assert "closing_mismatch" not in codes
    assert "foreign_ledgers_at_book_value" in codes


def test_a_foreign_ledger_off_its_book_value_fails(db: Session, synced: S.Connection) -> None:
    report, customer = _validate(db, synced, Decimal("1.00"))
    failed = [f for f in report.findings if f.check_code == "closing_mismatch"]
    assert [(f.object_id, f.expected) for f in failed] == [(str(customer.id), Decimal("1.00"))]
