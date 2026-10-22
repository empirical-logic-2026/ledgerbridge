"""Replays the test company's statements and stock values, recorded with accounts integrated
with inventory and without (tests/fixtures/tally/rules/stock_values/, 2026-10-22).

Answers report requests (Trial Balance, Balance Sheet, Profit and Loss, Stock Summary) and
the collections recorded with them by their request id and the period's To date.
"""

import re
from pathlib import Path

import httpx

from tests.conftest import FIXTURES

FOLDER = FIXTURES / "tally" / "rules" / "stock_values"
_ID = re.compile(r"<ID>([^<]+)</ID>")
_TO = re.compile(r'<SVTODATE TYPE="Date">(\d{4})(\d{2})(\d{2})</SVTODATE>')
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


def replay(case: str) -> httpx.MockTransport:
    folder: Path = FOLDER / case

    def answer(request: httpx.Request) -> httpx.Response:
        body = request.read().decode("utf-8")
        kind = _ID.search(body).group(1)  # type: ignore[union-attr]
        if kind == "LBCompanies":
            return httpx.Response(200, content=(folder / "companies.xml").read_bytes())
        to = _TO.search(body)
        file = folder / f"{FILES[kind]}_{to.group(1)}-{to.group(2)}-{to.group(3)}.xml"  # type: ignore[union-attr]
        return httpx.Response(200, content=file.read_bytes())

    return httpx.MockTransport(answer)
