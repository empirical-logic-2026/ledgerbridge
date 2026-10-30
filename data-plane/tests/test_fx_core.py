"""Foreign currency, the core (FX-001, FX-003, FX-006): each foreign-currency line's currency,
foreign amount and rate; ledgers' currencies and foreign openings; currency masters with their
rate lists; voucher-derived rates; foreign balances per date. Base-currency figures unchanged.

The test company can't hold foreign amounts (Tally's import refuses them, ADR-035), so the
foreign parts are synthetic, written the way Tally exports them, on the test company's
recorded books (statement_year_end/books, 2026-10-24): the dollar customer's sale gets a
dollar amount, and a currency master with a rate list is added. Customer Hotel USD's dollar
opening is the one the developer entered in TallyPrime (on a ledger Tally keeps in rupees).
"""

import hashlib
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from connectors.tally import mapping
from connectors.tally.connector import TallyConnector
from connectors.tally.fixtures import FixtureTransport
from connectors.tally.signs import tally_foreign_parts, tally_foreign_unread
from core import base_check, fx
from core.canonical import CanonicalLine, CanonicalVoucher
from core.models import accounting as A  # noqa: N812
from core.models import system as S  # noqa: N812
from core.models.source import RawRecord
from core.transform import Transformer, TransformResult, _Raw
from tests.conftest import COMPANY
from tests.stock_replay import YEAR_END
from workers.extract import get_or_create_connection
from workers.report import note_code
from workers.sync import run_sync

ET = __import__("xml.etree.ElementTree").etree.ElementTree
BOOKS: Path = YEAR_END / "books"
SALE_LINE = (
    '<AMOUNT TYPE="Amount">-8200.00</AMOUNT>'  # the dollar customer's line of FX-SAL-1, in rupees
)
SALE_IN_DOLLARS = '<AMOUNT TYPE="Amount">-$100.00 @ ?82.00/$ = -?8200.00</AMOUNT>'
USD_MASTER = (
    '<CURRENCY NAME="$" RESERVEDNAME=""><GUID>synthetic-usd</GUID><ALTERID> 1</ALTERID>'
    "<MASTERID> 1</MASTERID><ORIGINALNAME>$</ORIGINALNAME><EXPANDEDSYMBOL>USD</EXPANDEDSYMBOL>"
    "<MAILINGNAME>US Dollar</MAILINGNAME><DECIMALPLACES> 2</DECIMALPLACES>"
    "<DAILYSTDRATES.LIST><DATE>20250401</DATE><SPECIFIEDRATE>80.00</SPECIFIEDRATE>"
    "</DAILYSTDRATES.LIST>"
    "<DAILYSTDRATES.LIST><DATE>20260331</DATE><SPECIFIEDRATE>83.00</SPECIFIEDRATE>"
    "</DAILYSTDRATES.LIST>"
    "<DAILYSELLINGRATES.LIST><DATE>20260331</DATE><SPECIFIEDRATE>84.00</SPECIFIEDRATE>"
    "</DAILYSELLINGRATES.LIST>"
    "<DAILYBUYINGRATES.LIST><DATE>20260331</DATE><SPECIFIEDRATE>0</SPECIFIEDRATE>"
    "</DAILYBUYINGRATES.LIST>"
    "</CURRENCY>"
)


@pytest.mark.parametrize(
    ("text", "parts"),
    [
        ("-$100.00 @ ?82.00/$ = -?8200.00", ("$", Decimal("-100.00"), Decimal("82.00"))),
        ("-$1000.00 @ ? 80/$ = -? 80000.00", ("$", Decimal("-1000.00"), Decimal("80"))),
        ("-€1,250.50 @ ?90.10/€ = -?112,670.05", ("€", Decimal("-1250.50"), Decimal("90.10"))),
        ("$50.00 = ?4100.00", ("$", Decimal("50.00"), None)),  # no rate written
        # The rupee sign however it is written: only the digits around it are read.
        ("-$100.00 @ ₹82.00/$ = -₹8200.00", ("$", Decimal("-100.00"), Decimal("82.00"))),
        ("-$100.00 @ Rs.82.00/$ = -Rs.8200.00", ("$", Decimal("-100.00"), Decimal("82.00"))),
        ("-$100.00 @ Rs. 82.00/$ = -Rs. 8200.00", ("$", Decimal("-100.00"), Decimal("82.00"))),
        ("-$100 @ Rs 82/$ = -Rs 8200", ("$", Decimal("-100"), Decimal("82"))),
        ("-£50.00 @ INR 100/£ = -INR 5000", ("£", Decimal("-50.00"), Decimal("100"))),
        ("$-100.00 @ ?82.00/$ = ?-8200.00", ("$", Decimal("-100.00"), Decimal("82.00"))),
        ("-US$ 100 @ ?82/US$ = -?8200", ("US$", Decimal("-100"), Decimal("82"))),
        (
            "-Dhs.100.00 @ Rs.22.50/Dhs. = -Rs.2250.00",
            ("Dhs.", Decimal("-100.00"), Decimal("22.50")),
        ),
        ("8200.00", None),  # base currency only
        ("", None),
    ],
)
def test_a_foreign_amount_gives_its_currency_amount_and_rate(text: str, parts: object) -> None:
    assert tally_foreign_parts(text) == parts


@pytest.mark.parametrize(
    ("text", "unread"),
    [
        ("-$100.00 @ ?82.00/$ = -?8200.00", False),
        ("-$100.00 @ ₹82.00/$ = -₹8200.00", False),
        ("-$100.00 @ Rs.82.00/$ = -Rs.8200.00", False),
        ("8200.00", False),  # base currency only
        ("", False),
        (None, False),
        ("-$100.00 @ ?82.00/$", True),  # no base amount after `=`
        ("-$ @ ?82.00/$ = -?8200.00", True),  # no foreign amount
        ("-$100.00 @ ?82.00/$ = -?", True),  # the base amount unreadable
    ],
)
def test_a_foreign_amount_that_cant_be_read_is_flagged(text: str | None, unread: bool) -> None:
    assert tally_foreign_unread(text) is unread


def test_an_unreadable_foreign_amount_is_counted_and_noted() -> None:
    line = mapping._line(  # a ledger entry written in a form not seen before
        _element(
            "<ALLLEDGERENTRIES.LIST><LEDGERNAME>Customer</LEDGERNAME>"
            "<AMOUNT>-$100.00 @ ?82.00/$</AMOUNT></ALLLEDGERENTRIES.LIST>"
        )
    )
    assert line.foreign_unread and line.amount_fc is None
    read = CanonicalLine("Sales", Decimal(8200), amount_fc=Decimal(-100))
    voucher = CanonicalVoucher(
        source_key="v", voucher_type_name="Sales", voucher_number="1",
        voucher_date=date(2026, 8, 1),
        lines=(line, read),
    )  # fmt: skip
    item, result = _Raw(row=RawRecord(), records=[voucher]), TransformResult()
    Transformer._count_foreign(item, result)
    assert (result.foreign_read, result.foreign_unread) == (1, 1)
    assert item.warnings == ["foreign amount not read: voucher_lines.amount_fc"]
    assert note_code(item.warnings[0]) == "LB-TRF-011"


def _element(xml: str) -> object:
    return ET.fromstring(xml)


def test_ledgers_keep_their_own_currency_and_their_openings_foreign_part() -> None:
    hotel = mapping.ledger(
        _element(
            '<LEDGER NAME="Hotel"><NAME>Hotel</NAME><PARENT>Sundry Debtors</PARENT>'
            "<CURRENCYNAME>?</CURRENCYNAME>"
            "<OPENINGBALANCE>-$1000.00 @ ? 80/$ = -? 80000.00</OPENINGBALANCE></LEDGER>"
        ),
        "hotel",
        "company",
    )[0]
    assert (hotel.currency_name, hotel.opening_currency_name) == ("?", "$")
    assert hotel.opening_balance == Decimal(80000)  # the books' figure, a debit
    assert hotel.opening_balance_fc == Decimal(1000)
    plain = mapping.ledger(
        _element(
            '<LEDGER NAME="Cash"><NAME>Cash</NAME><PARENT>Cash-in-Hand</PARENT>'
            "<CURRENCYNAME>?</CURRENCYNAME><OPENINGBALANCE>-500.00</OPENINGBALANCE></LEDGER>"
        ),
        "cash",
        "company",
    )[0]
    assert (plain.opening_currency_name, plain.opening_balance_fc) == (None, None)


def test_a_currency_master_gives_its_code_and_rate_lists() -> None:
    usd = mapping.currency(_element(USD_MASTER), "synthetic-usd")
    assert (usd.name, usd.code, usd.formal_name, usd.decimal_places) == ("$", "USD", "US Dollar", 2)
    assert [(r.kind, r.rate_date, r.rate) for r in usd.rates] == [
        ("standard", date(2025, 4, 1), Decimal("80.00")),
        ("standard", date(2026, 3, 31), Decimal("83.00")),
        ("selling", date(2026, 3, 31), Decimal("84.00")),  # a zero buying rate is no rate
    ]


@pytest.fixture
def foreign_books(db: Session, monkeypatch: pytest.MonkeyPatch) -> S.Connection:
    """The year-end books synced, then made foreign the way a real company is: the sale's
    dollar line, and a currency master with its rate lists."""
    monkeypatch.setattr(
        "connectors.registry.default_config", lambda code: {"url": "http://tally.test:9000"}
    )
    connection = get_or_create_connection(db, "tally-test", "tally")
    db.commit()
    connector = TallyConnector.from_config(
        {"url": "http://tally.test:9000"}, transport=FixtureTransport(BOOKS)
    )
    assert run_sync(db, connection, connector, [COMPANY]).status == "succeeded"
    sale = next(
        r for r in db.scalars(select(RawRecord).where(RawRecord.object_type == "voucher"))
        if "[lb-seed:FX-SAL-1]" in r.payload
    )  # fmt: skip
    assert sale.payload.count(SALE_LINE) == 1
    sale.payload = sale.payload.replace(SALE_LINE, SALE_IN_DOLLARS)
    company = db.scalars(select(RawRecord.source_entity_key)).first()
    db.add(
        RawRecord(
            connection_id=connection.id, source_entity_key=company, object_type="currency",
            source_key="synthetic-usd", source_alter_id=1, payload_format="xml",
            payload=USD_MASTER, payload_hash=hashlib.sha256(USD_MASTER.encode()).hexdigest(),
            received_at=datetime(2026, 10, 24), process_status="pending",
        )
    )  # fmt: skip
    db.commit()
    return connection


def test_the_transform_stores_foreign_figures_and_leaves_base_figures_alone(
    db: Session, foreign_books: S.Connection
) -> None:
    before = base_check.snapshot(db, foreign_books.id)
    connector = TallyConnector.from_config(
        {"url": "http://tally.test:9000"}, transport=FixtureTransport(BOOKS)
    )
    result = Transformer(db, foreign_books.id, connector).run(rebuild=True)
    # The sale's dollar line and Customer Hotel USD's opening; none unreadable.
    assert (result.foreign_read, result.foreign_unread) == (2, 0)
    found = base_check.compare(before, base_check.snapshot(db, foreign_books.id))
    assert found.unchanged and found.vouchers > 50 and found.ledgers > 40  # the books unchanged

    line = db.execute(
        select(A.VoucherLine).where(A.VoucherLine.currency_name.is_not(None))
    ).scalar_one()
    assert (line.currency_name, line.amount_fc, line.exchange_rate, line.amount) == (
        "$", Decimal(100), Decimal(82), Decimal(8200),
    )  # fmt: skip
    usd = db.scalars(select(A.CurrencySource)).one()
    assert (usd.name, usd.currency_code) == ("$", "USD")
    assert db.get(A.Currency, "USD").symbol == "$"

    by_name = {x.name: x for x in db.scalars(select(A.Ledger))}
    delta, hotel = by_name["Customer Delta USD"], by_name["Customer Hotel USD"]
    # Each ledger's own currency as Tally defines it (CURRENCYNAME), and whether it's foreign.
    assert (delta.currency_code, delta.currency_name, delta.is_foreign_currency) == (
        "USD", "$", True,
    )  # fmt: skip
    # Tally keeps Hotel in rupees ("?" is the rupee sign as exported); its opening is in dollars.
    assert (hotel.currency_code, hotel.currency_name, hotel.is_foreign_currency) == (
        "INR", "?", False,
    )  # fmt: skip
    assert (hotel.opening_currency_name, hotel.opening_balance_fc) == ("$", Decimal(1000))
    foreign = {x.name for x in by_name.values() if x.is_foreign_currency}
    assert foreign == {"Customer Delta USD", "Vendor Echo USD"}
    assert all(x.currency_code == "INR" for x in by_name.values() if not x.is_foreign_currency)

    rates = {
        (r.source, r.rate_kind, r.rate_date): (r.rate, r.currency_code, r.voucher_count)
        for r in db.scalars(select(A.ExchangeRate))
    }
    assert rates == {
        ("source_rate_list", "standard", date(2025, 4, 1)): (Decimal(80), "USD", None),
        ("source_rate_list", "standard", date(2026, 3, 31)): (Decimal(83), "USD", None),
        ("source_rate_list", "selling", date(2026, 3, 31)): (Decimal(84), "USD", None),
        ("vouchers", "vouchers", date(2026, 8, 1)): (Decimal(82), "USD", 1),
    }

    entity_id = db.scalars(select(A.Entity.id)).one()
    balances = fx.foreign_balances(db, entity_id, date(2026, 10, 2))
    assert {by_id.name: (b.currency_name, b.balance_fc) for b in balances.values()
            for by_id in [db.get(A.Ledger, b.ledger_id)]} == {
        "Customer Delta USD": ("$", Decimal(100)),
        "Customer Hotel USD": ("$", Decimal(1000)),
    }  # fmt: skip
    before_sale = fx.foreign_balances(db, entity_id, date(2026, 7, 31))
    assert {db.get(A.Ledger, b.ledger_id).name: b.balance_fc for b in before_sale.values()} == {
        "Customer Hotel USD": Decimal(1000)
    }


def test_the_base_check_finds_a_changed_amount(db: Session, foreign_books: S.Connection) -> None:
    before = base_check.snapshot(db, foreign_books.id)
    line = db.scalars(select(A.VoucherLine)).first()
    line.amount += 1
    db.commit()
    found = base_check.compare(before, base_check.snapshot(db, foreign_books.id))
    assert (found.vouchers_differing, found.ledgers_differing) == (1, 1)
    assert not found.unchanged


def test_a_master_without_an_iso_code_in_its_formal_name() -> None:
    """The ISO code may be in another field than the formal name; a master renamed keeps its
    other name as an alias (a ledger's CURRENCYNAME may use either)."""
    master = mapping.currency(
        _element(
            '<CURRENCY NAME="Dollar"><ORIGINALNAME>$</ORIGINALNAME>'
            "<EXPANDEDSYMBOL>US Dollar</EXPANDEDSYMBOL><MAILINGNAME>USD</MAILINGNAME></CURRENCY>"
        ),
        "k",
    )
    assert (master.name, master.code, master.aliases) == ("$", "USD", ("Dollar",))
    plain = mapping.currency(
        _element('<CURRENCY NAME="$"><EXPANDEDSYMBOL>US Dollar</EXPANDEDSYMBOL></CURRENCY>'), "k"
    )
    assert (plain.code, plain.aliases) == (None, ())


def test_foreign_ledgers_are_found_without_iso_codes_and_by_alias(
    db: Session, foreign_books: S.Connection
) -> None:
    """Pilot 2026-10-30: every ledger was INR. Without any ISO code from the masters, the
    base currency is the one most ledgers are kept in, the others are foreign (code NULL);
    a ledger naming its currency by the master's other name gets the master's code."""
    connector = TallyConnector.from_config(
        {"url": "http://tally.test:9000"}, transport=FixtureTransport(BOOKS)
    )
    Transformer(db, foreign_books.id, connector).run(rebuild=True)
    entity_id = db.scalars(select(A.Entity.id)).one()
    for master in db.scalars(select(A.CurrencySource)):
        master.currency_code = None
    db.commit()
    assert fx.base_currency_name(db, entity_id) == "?"  # most ledgers are kept in rupees
    assert fx.refresh_ledger_currencies(db, entity_id) == 2
    by_name = {x.name: x for x in db.scalars(select(A.Ledger))}
    assert (
        by_name["Customer Delta USD"].is_foreign_currency,
        by_name["Customer Delta USD"].currency_code,
    ) == (True, None)
    assert by_name["Cash"].currency_code == "INR" and not by_name["Cash"].is_foreign_currency

    master = db.scalars(select(A.CurrencySource).where(A.CurrencySource.name == "$")).one()
    master.currency_code = "USD"
    master.extra = {"_aliases": ["Dollar"]}
    by_name["Customer Delta USD"].currency_name = "Dollar"
    db.commit()
    assert fx.currency_codes(db, entity_id)["Dollar"] == "USD"
    fx.refresh_ledger_currencies(db, entity_id)
    delta = db.get(A.Ledger, by_name["Customer Delta USD"].id)
    assert (delta.is_foreign_currency, delta.currency_code) == (True, "USD")
