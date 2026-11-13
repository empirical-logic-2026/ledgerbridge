"""Reads Tally's Profit & Loss A/c from its HTML export (tests only; ADR-056): the one export
that keeps Tally's horizontal layout (recorded 2026-11-13, tests/fixtures/tally/rules/pl_sides).

The report is nested tables: the outer table's second row holds the body, its third the
Totals; in each, the first column is the left side and the second the right side; each line
is a row of its own with the label and the amount in cells of their own. A line without a
label is the gross block's subtotal; a line with a label and no amount is a group with
nothing in the period.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path

AMOUNT = re.compile(r"^-?[\d,]+\.\d\d$")


@dataclass
class TallyPL:
    period: str  # as Tally writes it: "1-Apr-25 to 2-Nov-26"
    company: str
    left: list[tuple[str, Decimal | None]] = field(default_factory=list)
    right: list[tuple[str, Decimal | None]] = field(default_factory=list)


class _Cells(HTMLParser):
    """Every text with its position: the tags table/tr/td it sits in, numbered."""

    def __init__(self) -> None:
        super().__init__()
        self.path: list[str] = []
        self.counts: list[int] = [0]
        self.cells: list[tuple[list[str], str]] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ("table", "tr", "td"):
            self.path.append(f"{tag}{self.counts[-1]}")
            self.counts[-1] += 1
            self.counts.append(0)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("table", "tr", "td"):
            while self.path:
                closed = self.path.pop()
                self.counts.pop()
                if closed.startswith(tag):
                    break

    def handle_data(self, data: str) -> None:
        text = " ".join(data.replace("\xa0", " ").split())
        if text:
            self.cells.append((list(self.path), text))


def _amount(text: str) -> Decimal:
    return Decimal(text.replace(",", ""))


def read(path: Path) -> TallyPL:
    cells = _Cells()
    cells.feed(path.read_text(encoding="utf-8", errors="replace"))
    found = TallyPL("", "")
    lines: dict[tuple[str, str, str], list[str]] = {}
    for where, text in cells.cells:
        if len(where) < 8 or where[0] != "table1":
            continue
        if where[1] == "tr0":  # the heading: company and period, on both sides
            if " to " in text:
                found.period = text
            elif text != "Particulars":
                found.company = text
            continue
        side, line = where[5], where[7]
        lines.setdefault((where[1], side, line), []).append(text)
    for (_, side, _), texts in lines.items():
        label = " ".join(t for t in texts if not AMOUNT.match(t))
        amounts = [_amount(t) for t in texts if AMOUNT.match(t)]
        row = (label, amounts[0] if amounts else None)
        (found.left if side == "td0" else found.right).append(row)
    return found
