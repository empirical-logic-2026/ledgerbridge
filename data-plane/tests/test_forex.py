"""Foreign-currency ledgers (VAL-013, ADR-035; pilot 2026-10-16): Tally reports such a
ledger's closing balance, and its group totals, at current rates; its trial balance shows
the difference to the rupee amounts entered as "Unadjusted Forex Gain/Loss", and its Ledger
Vouchers show the amounts entered. Validation compares the foreign-currency ledgers with
that book value; each line keeps its foreign amount."""

import re
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from connectors.base import SourceBalances
from connectors.tally.connector import TallyConnector, _foreign, report_rows
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


# Synthetic, in the layout Tally exports (the test company's sale FX-SAL-1): the dollar
# customer's vouchers in August 2026 as its ledger-voucher collection lists them.
USD_SALE = """<ENVELOPE><BODY><DATA><COLLECTION>
<VOUCHER VCHTYPE="Sales"><GUID>fx-sal-1</GUID><ALTERID>1</ALTERID><DATE>20260801</DATE>
<VOUCHERTYPENAME>Sales</VOUCHERTYPENAME><VOUCHERNUMBER>9</VOUCHERNUMBER>
<ISOPTIONAL>No</ISOPTIONAL><ISCANCELLED>No</ISCANCELLED>
<ALLLEDGERENTRIES.LIST><LEDGERNAME>Customer Delta USD</LEDGERNAME>
<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE><AMOUNT>-8200.00</AMOUNT></ALLLEDGERENTRIES.LIST>
<ALLLEDGERENTRIES.LIST><LEDGERNAME>Sales - Services</LEDGERNAME>
<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE><AMOUNT>8200.00</AMOUNT></ALLLEDGERENTRIES.LIST>
</VOUCHER></COLLECTION></DATA></BODY></ENVELOPE>"""
EMPTY = "<ENVELOPE><BODY><DATA><COLLECTION></COLLECTION></DATA></BODY></ENVELOPE>"


def _trial_balance(*lines: tuple[str, str, str]) -> str:
    """A trial balance export: (name, debit, credit) in Tally's signs."""
    body = "".join(
        f"<DSPACCNAME><DSPDISPNAME>{name}</DSPDISPNAME></DSPACCNAME><DSPACCINFO>"
        f"<DSPCLDRAMT><DSPCLDRAMTA>{dr}</DSPCLDRAMTA></DSPCLDRAMT>"
        f"<DSPCLCRAMT><DSPCLCRAMTA>{cr}</DSPCLCRAMTA></DSPCLCRAMT></DSPACCINFO>"
        for name, dr, cr in lines
    )
    return f"<ENVELOPE>{body}</ENVELOPE>"


BOOKS_TB = _trial_balance(("Capital Account", "", "52010.00"), ("Current Assets", "-64010.00", ""),
                          ("Loans (Liability)", "", "12000.00"))  # fmt: skip


def _replaying(trial_balance: str = BOOKS_TB) -> TallyConnector:
    """Answered by the responses recorded from the test company (2026-10-16): a US dollar
    customer with a sale of Rs 8,200 entered without a dollar amount; its vouchers and the
    trial balance at the books' beginning synthetic, in Tally's layout."""
    import httpx

    files = {
        "LBCompanies": "companies.xml",
        "LBGroupBalances": "group_balances.xml",
        "LBLedgerBalances": "ledger_balances.xml",
        "LBStockValues": "stock_values.xml",
    }

    def answer(request: httpx.Request) -> httpx.Response:
        text = request.content.decode()
        name = text.split("<ID>")[1].split("</ID>")[0]
        if name == "LBLedgerVouchers":
            august = '<SVFROMDATE TYPE="Date">20260801</SVFROMDATE>' in text
            return httpx.Response(200, content=(USD_SALE if august else EMPTY).encode())
        if name == "Trial Balance":
            start = re.search(r'<SVFROMDATE TYPE="Date">(\d{8})</SVFROMDATE>', text)
            end = re.search(r'<SVTODATE TYPE="Date">(\d{8})</SVTODATE>', text)
            same_day = start is not None and end is not None and start.group(1) == end.group(1)
            if same_day:
                return httpx.Response(200, content=trial_balance.encode())
            return httpx.Response(200, content=b"<ENVELOPE/>")
        if name in (
            "Balance Sheet",
            "Profit and Loss",
            "LBStockGroupValues",
            "LBGodownValues",
        ):
            return httpx.Response(200, content=b"<ENVELOPE/>")
        return httpx.Response(200, content=(FOREX_FIXTURES / files[name]).read_bytes())

    return TallyConnector.from_config(
        {"url": "http://tally.test:9000"}, transport=httpx.MockTransport(answer)
    )


def test_the_book_value_is_the_opening_plus_the_sources_own_vouchers() -> None:
    """Tally values the dollar customer at its dollar amount ($0, so Rs 0) in its closing
    balance; its book value is its opening plus Tally's own vouchers on it up to the date
    (pilot 2026-10-16: every voucher matched ours while the closing balances differed, and
    Ledger Vouchers showed no calculated line to subtract)."""
    connector = _replaying()
    (entity,) = connector.list_entities()
    balances = connector.closing_balances(entity, AS_OF)
    (key,) = balances.foreign_ledgers
    assert balances.ledgers[key] == 0  # revalued: information only
    assert balances.book_values == {frozenset({key}): Decimal("8200.00")}
    # An earlier date (a year end) uses the vouchers read already: before the sale, 0.
    earlier = connector.closing_balances(entity, date(2026, 7, 31))
    assert earlier.book_values == {frozenset({key}): Decimal(0)}
    rows = report_rows((FOREX_FIXTURES / "ledger_vouchers_report.xml").read_bytes())
    assert [(r.account, r.voucher_type, r.amount) for r in rows] == [
        ("Sales - Services", "Sale", Decimal("8200.00")),
        ("Unadjusted Forex Gain/Loss", "", Decimal("-8200.00")),  # calculated, no voucher
    ]


def test_the_opening_difference_is_what_tallys_trial_balance_shows() -> None:
    """Pilot 2026-10-16: Tally's trial balance and balance sheet at the books' beginning
    showed no difference line while the group openings didn't total zero. The warning
    follows Tally's own line, and is zero without it."""
    connector = _replaying()
    (entity,) = connector.list_entities()
    assert connector.closing_balances(entity, AS_OF).opening_difference == 0
    shown = _trial_balance(("Capital Account", "", "52010.00"),
                           ("Difference in opening balances", "-7.00", ""))  # fmt: skip
    connector = _replaying(shown)
    (entity,) = connector.list_entities()
    assert connector.closing_balances(entity, AS_OF).opening_difference == Decimal("7.00")
    connector = _replaying("<RESPONSE>Unknown Request</RESPONSE>")  # unreadable: computed
    (entity,) = connector.list_entities()
    assert connector.closing_balances(entity, AS_OF).opening_difference == 0


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
