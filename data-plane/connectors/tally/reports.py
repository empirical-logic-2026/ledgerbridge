"""Tally's own statements, read from its report exports (Trial Balance, Balance Sheet, Profit
and Loss): the figures our statements must match line by line (ADR-040).

Where it fits: `connector.source_statements` requests the three reports for a period
(envelopes.report_request, read-only) and passes each answer here. The exports list one line
per primary group (plus Tally's own lines such as Profit & Loss A/c, Cost of Sales and
Unadjusted Forex Gain/Loss), each a name followed by its amounts; layouts recorded from the
test company with accounts integrated with inventory and without (2026-10-22):

- Trial Balance: DSPACCNAME/DSPDISPNAME, then DSPACCINFO with DSPCLDRAMT/DSPCLDRAMTA (debit,
  written negative) and DSPCLCRAMT/DSPCLCRAMTA (credit, positive);
- Balance Sheet: BSNAME/DSPACCNAME/DSPDISPNAME, then BSAMT with BSSUBAMT and BSMAINAMT
  (liabilities positive, assets negative);
- Profit and Loss: DSPACCNAME/DSPDISPNAME, then PLAMT with PLSUBAMT (lines inside a block,
  e.g. Opening Stock) and BSMAINAMT (income positive, expenses negative).

Every amount is turned into the canonical sign (debit positive): the negative of Tally's.
"""

import xml.etree.ElementTree as ET  # noqa: N817
from decimal import Decimal

from connectors.base import StatementLine
from connectors.tally import parser
from connectors.tally.signs import tally_amount

# Tally's own lines in its Profit and Loss export that carry the stock values its profit
# uses (as recorded; the closing stock is shown as a deduction, with the same sign).
OPENING_STOCK = "Opening Stock"
CLOSING_STOCK = "Less: Closing Stock"
ZERO = Decimal(0)


def _canonical(text: str | None) -> Decimal | None:
    """Tally's amount in the canonical sign; None when the field is empty."""
    value = tally_amount(text)
    if value is None:
        return None
    return -value if value else ZERO


def _name(element: ET.Element) -> str:
    return (element.findtext("DSPDISPNAME") or "").strip()


def trial_balance(body: bytes) -> list[StatementLine]:
    """The Trial Balance export: each line's debit and credit totals (positive)."""
    lines, name = [], None
    for element in parser.parse_response(body).iter():
        if element.tag == "DSPACCNAME":
            name = _name(element)
        elif element.tag == "DSPACCINFO" and name is not None:
            debit = _canonical(element.findtext("DSPCLDRAMT/DSPCLDRAMTA")) or ZERO
            credit = -(_canonical(element.findtext("DSPCLCRAMT/DSPCLCRAMTA")) or ZERO)
            lines.append(
                StatementLine("trial_balance", name, "main", debit - credit, debit, credit)
            )
            name = None
    return lines


def balance_sheet(body: bytes) -> list[StatementLine]:
    """The Balance Sheet export: main lines (BSMAINAMT) and lines inside a group's block
    (BSSUBAMT)."""
    return _amount_lines(body, "balance_sheet", "BSAMT", "BSSUBAMT")


def profit_and_loss(body: bytes) -> list[StatementLine]:
    """The Profit and Loss export: main lines (BSMAINAMT) and lines inside a block such as
    Cost of Sales (PLSUBAMT)."""
    return _amount_lines(body, "profit_loss", "PLAMT", "PLSUBAMT")


def _amount_lines(
    body: bytes, statement: str, amount_tag: str, sub_tag: str
) -> list[StatementLine]:
    lines, name = [], None
    for element in parser.parse_response(body).iter():
        if element.tag == "DSPACCNAME":
            name = _name(element)
        elif element.tag == amount_tag and name is not None:
            sub = _canonical(element.findtext(sub_tag))
            main = _canonical(element.findtext("BSMAINAMT"))
            if sub is not None:
                lines.append(StatementLine(statement, name, "sub", sub))
            else:
                lines.append(StatementLine(statement, name, "main", main or ZERO))
            name = None
    return lines


def stock_values(lines: list[StatementLine]) -> tuple[Decimal | None, Decimal | None]:
    """(opening, closing) stock as Tally's Profit and Loss uses it (canonical sign: a debit);
    None when its export shows no such line (no stock)."""
    found = {line.label: line.amount for line in lines if line.level == "sub"}
    return found.get(OPENING_STOCK), found.get(CLOSING_STOCK)
