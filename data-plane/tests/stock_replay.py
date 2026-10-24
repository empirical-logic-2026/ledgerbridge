"""Replays the test company's statements and stock values, recorded with accounts integrated
with inventory and without (tests/fixtures/tally/rules/stock_values/, 2026-10-22), and after
the statement layout seed (tests/fixtures/tally/rules/statement_layout/, 2026-10-23) and the
netting seed (tests/fixtures/tally/rules/statement_netting/, 2026-10-24).

The groups' reporting setting (LBGroupReporting) is dated nothing; recordings made before it
was read answer with no groups: every group's setting was No then (the test company's group
records, read 2026-10-24).

Answers report requests (Trial Balance, Balance Sheet, Profit and Loss, Stock Summary) and
the collections recorded with them by their request id and the period's To date.
"""

import re
from pathlib import Path

import httpx

from tests.conftest import FIXTURES

FOLDER = FIXTURES / "tally" / "rules" / "stock_values"
LAYOUT = FIXTURES / "tally" / "rules" / "statement_layout"
NETTING = FIXTURES / "tally" / "rules" / "statement_netting"
YEAR_END = FIXTURES / "tally" / "rules" / "statement_year_end"
EMPTY = b"<ENVELOPE><BODY><DATA><COLLECTION></COLLECTION></DATA></BODY></ENVELOPE>"
_ID = re.compile(r"<ID>([^<]+)</ID>")
_TO = re.compile(r'<SVTODATE TYPE="Date">(\d{4})(\d{2})(\d{2})</SVTODATE>')
_FROM = re.compile(r'<SVFROMDATE TYPE="Date">(\d{8})</SVFROMDATE>')
_BOOKS = re.compile(r"<BOOKSFROM[^>]*>(\d{8})</BOOKSFROM>")
FILES = {
    "Trial Balance": "trial_balance",
    "Balance Sheet": "balance_sheet",
    "Profit and Loss": "profit_and_loss",
    "Stock Summary": "stock_summary",
    "LBStockValues": "stock_value",
    "LBStockGroupValues": "stock_group_value",
    "LBGodownValues": "godown_value",
    "LBGroupBalances": "group_balance",
    "LBLedgerBalances": "ledger_balance",
}


def replay(case: str, root: Path = FOLDER) -> httpx.MockTransport:
    folder: Path = root / case

    def answer(request: httpx.Request) -> httpx.Response:
        body = request.read().decode("utf-8")
        kind = _ID.search(body).group(1)  # type: ignore[union-attr]
        if kind == "LBCompanies":
            return httpx.Response(200, content=(folder / "companies.xml").read_bytes())
        if kind == "LBGroupReporting":
            setting = folder / "group_reporting.xml"
            return httpx.Response(200, content=setting.read_bytes() if setting.exists() else EMPTY)
        to = _TO.search(body)
        # A period starting after the books' beginning (the current financial year): its
        # own recording, prefixed fy_ (statement_year_end).
        books = _BOOKS.search(
            (folder / "companies.xml").read_text(encoding="utf-8", errors="replace")
        )
        start = _FROM.search(body)
        prefix = "fy_" if books and start and start.group(1) != books.group(1) else ""
        file = folder / f"{prefix}{FILES[kind]}_{to.group(1)}-{to.group(2)}-{to.group(3)}.xml"  # type: ignore[union-attr]
        return httpx.Response(200, content=file.read_bytes())

    return httpx.MockTransport(answer)
