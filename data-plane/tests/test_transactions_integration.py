"""`GET /api/v1/transactions` on MySQL, read as report_ro (RPT-014; F-TRN-001): the recorded test
company synced with the cost-centre and bank recordings of 2026-11-05 (the fixture of
tests/test_cost_centres_integration.py): a payment with cost centres paid by cheque 000451
(CC-2), a purchase invoice with reference SUP-INV-4471 (CC-3), and an e-Fund Transfer with
UTR UTR20260902000017 (BANK-2). One row per effective ledger line, its voucher's other
ledgers as particulars, and the line's bills, cost centres and bank details."""

from collections import Counter, defaultdict
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.db import get_engine
from core.models import accounting as A  # noqa: N812
from tests import test_cost_centres_integration as cost_centres
from tests.test_cost_centres_integration import MONTHS, _get, _voucher_id

pytestmark = pytest.mark.integration

# The cost-centre test's module fixtures: the synced test company and the API client.
synced = cost_centres.synced
client = cost_centres.client

D = Decimal


def _rows(client: TestClient, **params: object) -> list[dict]:
    page = _get(client, "/api/v1/transactions", **params)
    assert page["truncated"] is False
    return page["rows"]


def _of(rows: list[dict], voucher_id: int) -> list[dict]:
    return [r for r in rows if r["voucher_id"] == voucher_id]


def test_one_row_per_effective_line_and_every_voucher_balances(
    client: TestClient, synced: int
) -> None:
    rows = _rows(client, month=MONTHS)
    with Session(get_engine()) as s:
        expected = s.scalar(
            select(func.count())
            .select_from(A.VoucherLine)
            .join(A.Voucher, A.Voucher.id == A.VoucherLine.voucher_id)
            .where(
                A.VoucherLine.entity_id == synced,
                A.VoucherLine.is_effective.is_(True),
                A.Voucher.is_deleted.is_(False),
                A.VoucherLine.voucher_date.between("2026-04-01", "2026-09-30"),
            )
        )
    assert len(rows) == expected and len({r["line_id"] for r in rows}) == expected
    totals: dict[int, D] = defaultdict(D)
    for r in rows:
        assert (r["debit"] is None) != (r["credit"] is None) or D(
            r["debit"] or r["credit"] or 0
        ) == 0
        totals[r["voucher_id"]] += D(r["debit"] or 0) - D(r["credit"] or 0)
    assert all(total == 0 for total in totals.values())
    assert all(r["order_number"] is None for r in rows)  # not fetched yet
    assert [r["date"] for r in rows] == sorted(r["date"] for r in rows)


def test_particulars_are_the_other_side_and_the_line_details_are_on_their_lines(
    client: TestClient, synced: int
) -> None:
    rows = _rows(client, month=MONTHS)
    with Session(get_engine()) as s:
        payment = _voucher_id(s, synced, "CC-2")
        purchase = _voucher_id(s, synced, "CC-3")
        transfer = _voucher_id(s, synced, "BANK-2")
    lines = _of(rows, payment)
    expense = next(r for r in lines if r["ledger"] == "Electricity")
    bank = next(r for r in lines if r["credit"] is not None)
    assert expense["particulars"] == bank["ledger"]  # the other side
    assert bank["particulars"] == "Electricity"
    assert set(expense["cost_centres"].split(", ")) == {
        "Head Office",
        "Project Alpha",
        "Alpha Phase 1",
    }
    assert bank["cheque"] == "000451" and expense["cheque"] is None

    invoice = _of(rows, purchase)
    assert {r["reference"] for r in invoice} == {"SUP-INV-4471"}
    party = next(r for r in invoice if r["ledger"] == r["party"])
    assert party["bills"] is not None and "PI-9" in party["bills"].split(", ")
    purchases = next(r for r in invoice if r["ledger"] == "Purchases")
    assert set(purchases["cost_centres"].split(", ")) == {"Branch", "Head Office"}
    assert Counter(r["voucher_type"] for r in invoice) == Counter({"Purchase": len(invoice)})

    neft = next(r for r in _of(rows, transfer) if r["cheque"])
    assert neft["cheque"] == "NEFT-2026-0902" and neft["transaction_type"] == "e-Fund Transfer"
    # Tally's own id for the entry: kept apart, never shown as the UTR.
    assert neft["tally_bank_entry_id"] == "UTR20260902000017"
    assert not {"utr", "utr_source"} & set(neft)  # stored, never returned


def test_the_period_limits_the_rows(client: TestClient, synced: int) -> None:
    september = _rows(client, month=["2026-09"])
    assert september and {r["date"][:7] for r in september} == {"2026-09"}
    ranged = _rows(client, date_from="2026-09-01", date_to="2026-09-01")
    assert {r["date"] for r in ranged} == {"2026-09-01"}
