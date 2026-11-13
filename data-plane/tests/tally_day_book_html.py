"""Reads Tally's Day Book from its HTML export (tests only; ADR-057): one day, as Tally shows it
(recorded 2026-11-13, tests/fixtures/tally/rules/day_book).

The report is nested tables: the outer table's third row holds the vouchers, one row each;
in a voucher's row the cells are Date (1), Particulars (4), Vch Type (7), Debit Amount or
Inwards Qty (10) and Credit Amount or Outwards Qty (13). An empty cell is left out.
"""

from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

COLUMNS = {"td1": "date", "td4": "particulars", "td7": "voucher_type", "td10": "first",
           "td13": "second"}  # fmt: skip


@dataclass(frozen=True)
class Row:
    date: str  # as Tally writes it: "2-Oct-26"
    particulars: str
    voucher_type: str
    first: str  # the Debit Amount or Inwards Qty column, as written ("2,000.00", "3 Nos")
    second: str  # the Credit Amount or Outwards Qty column


class _Cells(HTMLParser):
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


def read(path: Path) -> list[Row]:
    cells = _Cells()
    cells.feed(path.read_text(encoding="utf-8", errors="replace"))
    rows: dict[str, dict[str, str]] = {}
    for where, text in cells.cells:
        if len(where) >= 9 and where[0] == "table1" and where[1] == "tr2":
            column = COLUMNS.get(where[-1])
            if column:
                rows.setdefault(where[4], {})[column] = text
    return [
        Row(r.get("date", ""), r.get("particulars", ""), r.get("voucher_type", ""),
            r.get("first", ""), r.get("second", ""))
        for r in rows.values()
    ]  # fmt: skip
