"""Tally statement exports and stock figures used by the Profit and Loss statement."""

from datetime import date
from decimal import Decimal

import pytest

from connectors.base import SourceEntity, SourceStatements
from connectors.tally import reports
from connectors.tally.client import TallyClient
from connectors.tally.connector import TallyConnector, _Group, _LedgerFigures
from tests.conftest import FIXTURES

STOCK_VALUES = FIXTURES / "tally" / "rules" / "stock_values"


@pytest.mark.parametrize(
    ("integration", "expected"),
    [
        ("integrated", (Decimal("2010.00"), Decimal("5580.00"))),
        ("not_integrated", (Decimal("1500.00"), Decimal("1500.00"))),
    ],
)
def test_profit_and_loss_stock_values_follow_tallys_report(
    integration: str, expected: tuple[Decimal, Decimal]
) -> None:
    report = (STOCK_VALUES / integration / "profit_and_loss_2026-10-02.xml").read_bytes()

    assert reports.stock_values(reports.profit_and_loss(report)) == expected


def test_trial_balance_and_statement_section_parsing() -> None:
    trial_balance = b"""<ENVELOPE><BODY><DATA>
      <DSPACCNAME><DSPDISPNAME>Cash</DSPDISPNAME></DSPACCNAME>
      <DSPACCINFO>
        <DSPCLDRAMT><DSPCLDRAMTA>-125.00</DSPCLDRAMTA></DSPCLDRAMT>
        <DSPCLCRAMT><DSPCLCRAMTA>25.00</DSPCLCRAMTA></DSPCLCRAMT>
      </DSPACCINFO>
    </DATA></BODY></ENVELOPE>"""
    balance_sheet = b"""<ENVELOPE><BODY><DATA>
      <DSPACCNAME><DSPDISPNAME>Fixed Assets</DSPDISPNAME></DSPACCNAME>
      <BSAMT><BSMAINAMT>-100.00</BSMAINAMT></BSAMT>
      <DSPACCNAME><DSPDISPNAME>Computer</DSPDISPNAME></DSPACCNAME>
      <BSAMT><BSSUBAMT>-80.00</BSSUBAMT></BSAMT>
    </DATA></BODY></ENVELOPE>"""
    profit_and_loss = b"""<ENVELOPE><BODY><DATA>
      <DSPACCNAME><DSPDISPNAME>Cost of Sales</DSPDISPNAME></DSPACCNAME>
      <PLAMT><BSMAINAMT>-900.00</BSMAINAMT></PLAMT>
      <DSPACCNAME><DSPDISPNAME>Opening Stock</DSPDISPNAME></DSPACCNAME>
      <PLAMT><PLSUBAMT>-100.00</PLSUBAMT></PLAMT>
    </DATA></BODY></ENVELOPE>"""

    tb_line = reports.trial_balance(trial_balance)[0]
    bs_lines = reports.balance_sheet(balance_sheet)
    pl_lines = reports.profit_and_loss(profit_and_loss)

    assert (tb_line.amount, tb_line.debit, tb_line.credit) == (
        Decimal(100),
        Decimal(125),
        Decimal(25),
    )
    assert [(line.label, line.level, line.amount, line.section) for line in bs_lines] == [
        ("Fixed Assets", "main", Decimal(100), None),
        ("Computer", "sub", Decimal(80), "Fixed Assets"),
    ]
    assert [(line.label, line.level, line.amount, line.section) for line in pl_lines] == [
        ("Cost of Sales", "main", Decimal(900), None),
        ("Opening Stock", "sub", Decimal(100), "Cost of Sales"),
    ]


@pytest.mark.parametrize(
    ("integrated", "stock"),
    [
        (True, (Decimal("1000"), Decimal("4000"))),
        (False, (Decimal("700"), Decimal("800"))),
    ],
)
def test_closing_balances_use_pnl_stock_over_group_and_item_totals(
    monkeypatch: pytest.MonkeyPatch,
    integrated: bool,
    stock: tuple[Decimal, Decimal],
) -> None:
    connector = TallyConnector(TallyClient("http://127.0.0.1:9000"))
    statements = SourceStatements(
        as_of=date(2026, 10, 2),
        lines=(),
        opening_stock=stock[0],
        closing_stock=stock[1],
        integrated=integrated,
    )
    groups = [_Group("Stock", "Assets", "Stock-in-Hand", Decimal(80), Decimal(90), True)]
    figures = _LedgerFigures(counted_openings=Decimal(10))
    monkeypatch.setattr(connector, "source_statements", lambda *_: statements)
    monkeypatch.setattr(connector, "_group_balances", lambda *_: groups)
    monkeypatch.setattr(connector, "_ledger_figures", lambda *args: figures)
    monkeypatch.setattr(connector, "_item_values", lambda *_: (Decimal(100), Decimal(200)))
    monkeypatch.setattr(connector, "opening_difference_shown", lambda *_: None)
    monkeypatch.setattr(connector, "_book_values", lambda *args: {})

    balances = connector.closing_balances(
        SourceEntity("entity-key", "Test company", date(2026, 4, 1)),
        date(2026, 10, 2),
    )

    assert (balances.opening_stock, balances.closing_stock) == stock
    assert balances.integrated is integrated
    assert balances.statements is statements
