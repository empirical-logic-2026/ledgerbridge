"""The dashboard API on MySQL as report_ro (D1; ADR-049): the recorded test-company fixtures
synced, then the explorer's totals against the monthly sales views and the books, groups
with their subtotals, lists, the CSV export and its row limit, companies on hold hidden, and
the data health read through `v_data_health` (./dev.ps1 up, or only the test MySQL with
migrations applied)."""

import csv
import io
from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import bindparam, delete, func, select, text
from sqlalchemy.orm import Session

from api import access as access_module
from api.main import create_app
from api.v1 import datasets as datasets_module
from connectors.tally.connector import TallyConnector
from connectors.tally.fixtures import DEFAULT_DIR, FixtureTransport
from core.db import get_engine
from core.models import accounting as A  # noqa: N812
from tests.test_migrations_integration import _config
from tests.test_sync_integration import CONNECTION, _cleanup
from workers.extract import get_or_create_connection
from workers.sync import run_sync

pytestmark = pytest.mark.integration
LINES = "/api/v1/datasets/voucher_lines"


@pytest.fixture(scope="module")
def synced() -> Iterator[int]:
    """The test company synced from the recorded fixtures; its entity id."""
    if not (DEFAULT_DIR / "manifest.json").exists():
        pytest.skip("no recorded fixtures")
    command.upgrade(_config(), "head")
    patch = pytest.MonkeyPatch()
    patch.setattr(
        "connectors.registry.default_config", lambda code: {"url": "http://tally.test:9000"}
    )
    connector = TallyConnector.from_config(
        {"url": "http://tally.test:9000"}, transport=FixtureTransport(DEFAULT_DIR)
    )
    with Session(get_engine()) as session:
        _cleanup(session)
        connection = get_or_create_connection(session, CONNECTION, "tally")
        session.commit()
        assert run_sync(session, connection, connector).status == "succeeded"
        entity_id = session.scalar(
            select(A.EntitySource.entity_id).where(A.EntitySource.connection_id == connection.id)
        )
        # Only this company is visible to the API in these tests (others: on hold).
        held = list(session.scalars(select(A.Entity.id).where(A.Entity.id != entity_id)))
        for other in held:
            session.get_one(A.Entity, other).is_on_hold = True
        session.commit()
        try:
            yield entity_id
        finally:
            for other in held:
                session.get_one(A.Entity, other).is_on_hold = False
            session.commit()
            _cleanup(session)
            session.commit()
    patch.undo()


@pytest.fixture
def client(synced: int) -> TestClient:
    return TestClient(create_app(), base_url="http://localhost")


def _get(client: TestClient, path: str, **params: object) -> dict:
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _sales_group_id(entity_id: int) -> int:
    with Session(get_engine()) as session:
        return session.scalar(
            select(A.AccountGroup.id).where(
                A.AccountGroup.entity_id == entity_id,
                A.AccountGroup.predefined_role == "sales_accounts",
            )
        )


def test_companies_with_their_health_read_as_report_ro(client: TestClient, synced: int) -> None:
    companies = _get(client, "/api/v1/companies")
    assert [c["id"] for c in companies] == [synced]
    health = companies[0]["health"]
    assert health["last_sync_at"] is not None  # from ledgerbridge_system, through the view
    periods = _get(client, "/api/v1/periods")
    assert periods["financial_years"] and periods["financial_years"][0]["label"].startswith("FY ")


def test_monthly_sales_from_the_explorer_equal_the_views(client: TestClient, synced: int) -> None:
    """Net sales = minus the net of the lines under the Sales Accounts group and below."""
    result = _get(client, LINES, group_by="month", measure="net", page_size=500,
                  ledger_group=_sales_group_id(synced))  # fmt: skip
    ours = {r["keys"]["month"]["id"]: -Decimal(r["values"]["net"]) for r in result["rows"]}
    with Session(get_engine("report")) as session:
        view = {
            f"{m:%Y-%m}": Decimal(str(n))
            for m, n in session.execute(
                text("SELECT month_start, net_sales FROM ledgerbridge_reporting.v_monthly_sales "
                     "WHERE entity_id = :e"), {"e": synced},
            )
        }  # fmt: skip
    assert ours and ours == view
    assert -Decimal(result["total"]["net"]) == sum(view.values())


def test_groups_subtotals_and_the_total_add_up(client: TestClient, synced: int) -> None:
    result = _get(client, LINES, group_by=["voucher_type", "month"],
                  measure=["debit", "credit", "voucher_count"], page_size=500)  # fmt: skip
    rows, subtotals, total = result["rows"], result["subtotals"], result["total"]
    assert len(rows) == result["total_rows"]
    assert Decimal(total["debit"]) == Decimal(total["credit"])  # the books balance
    assert sum(Decimal(r["values"]["debit"]) for r in rows) == Decimal(total["debit"])
    for sub in subtotals:
        assert sub["level"] == 1
        kind = sub["keys"]["voucher_type"]["id"]
        mine = [r for r in rows if r["keys"]["voucher_type"]["id"] == kind]
        for measure in ("debit", "credit"):
            assert Decimal(sub["values"][measure]) == sum(
                Decimal(r["values"][measure]) for r in mine
            )
    assert {s["keys"]["voucher_type"]["id"] for s in subtotals} == {
        r["keys"]["voucher_type"]["id"] for r in rows
    }
    with Session(get_engine("report")) as session:
        vouchers = session.scalar(
            select(func.count(func.distinct(A.VoucherLine.voucher_id)))
            .join(A.Voucher, A.Voucher.id == A.VoucherLine.voucher_id)
            .where(A.VoucherLine.entity_id == synced, A.VoucherLine.is_effective.is_(True),
                   A.Voucher.is_deleted.is_(False))
        )  # fmt: skip
    assert total["voucher_count"] == vouchers
    by_vouchers = _get(client, "/api/v1/datasets/vouchers", group_by="company",
                       measure=["amount", "voucher_count"])  # fmt: skip
    assert by_vouchers["total"]["voucher_count"] == vouchers
    assert Decimal(by_vouchers["total"]["amount"]) == Decimal(total["debit"])


def test_list_pages_and_sorting(client: TestClient, synced: int) -> None:
    first = _get(client, LINES, page_size=10, sort="-debit")
    assert len(first["rows"]) == 10 and first["total_rows"] > 10
    debits = [Decimal(r["values"]["debit"]) for r in first["rows"]]
    assert debits == sorted(debits, reverse=True)
    assert set(first["rows"][0]["keys"]) == {"date", "voucher_number", "voucher_type",
                                              "ledger", "party"}  # fmt: skip
    second = _get(client, LINES, page_size=10, page=2, sort="-debit")
    assert second["rows"] != first["rows"]


def test_csv_is_the_same_result_with_a_row_limit(
    client: TestClient, synced: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    params = {"group_by": ["voucher_type", "month"], "measure": ["debit"]}
    shown = _get(client, LINES, page_size=500, **params)
    response = client.get(f"{LINES}/csv", params=params)
    assert response.status_code == 200
    assert response.headers["x-row-limit-reached"] == "false"
    rows = list(csv.reader(io.StringIO(response.text.lstrip("\ufeff"))))
    assert rows[0] == ["Voucher type", "Month", "Debit"]
    assert rows[-1][0] == "Total" and Decimal(rows[-1][2]) == Decimal(shown["total"]["debit"])
    assert sum(1 for r in rows if r[0].endswith("(subtotal)")) == len(shown["subtotals"])
    assert len(rows) == 1 + len(shown["rows"]) + len(shown["subtotals"]) + 1

    monkeypatch.setattr(datasets_module, "CSV_ROW_LIMIT", 5)
    limited = client.get(f"{LINES}/csv")
    assert limited.headers["x-row-limit-reached"] == "true"
    lines = list(csv.reader(io.StringIO(limited.text.lstrip("\ufeff"))))
    assert len(lines) == 1 + 5 + 1 + 1  # header, 5 rows, total, the note
    assert lines[-1][0].startswith("Stopped at 5 rows")


def test_a_company_on_hold_is_hidden(client: TestClient, synced: int) -> None:
    with Session(get_engine()) as session:
        session.get_one(A.Entity, synced).is_on_hold = True
        session.commit()
        try:
            assert _get(client, "/api/v1/companies") == []
            response = client.get(LINES, params={"company": synced})
            assert response.status_code == 404
            assert _get(client, LINES)["total_rows"] == 0  # nothing visible at all
        finally:
            session.get_one(A.Entity, synced).is_on_hold = False
            session.commit()
    assert access_module.current_access  # the one place M5 replaces


# --- the Overview (D1 part b) -------------------------------------------------------------

YEAR = 2026  # the test company's books begin 1-Apr-2025; its vouchers are Apr to Sep 2026
YEAR_START, AS_OF, PREVIOUS_YEAR_END = date(2026, 4, 1), date(2026, 9, 30), date(2026, 3, 31)


@pytest.fixture
def statements_stored(synced: int) -> Iterator[None]:
    """Our statements at the date and at the previous year end, as `./dev.ps1 statements`
    stores them (the source's own lines aren't needed for ours)."""
    from connectors.base import SourceStatements
    from core import statements
    from core.models.reporting import StatementLine

    with Session(get_engine()) as session:
        connection_id = session.scalar(
            select(A.EntitySource.connection_id).where(A.EntitySource.entity_id == synced)
        )
        for on in (PREVIOUS_YEAR_END, AS_OF):
            source = SourceStatements(as_of=on, lines=(), opening_stock=None, closing_stock=None)
            statements.refresh(session, synced, connection_id, "live", source)
        session.commit()
        try:
            yield
        finally:
            for model in (StatementLine, A.StockValue, A.FxRevaluationSnapshot):
                session.execute(delete(model).where(model.entity_id == synced))
            session.commit()


def _stored_profit(entity_id: int, on: date, label: str) -> Decimal:
    with Session(get_engine("report")) as session:
        amount = session.scalar(
            text("SELECT amount FROM ledgerbridge_reporting.v_profit_loss "
                 "WHERE entity_id = :e AND as_of = :d AND label = :l"),
            {"e": entity_id, "d": on, "l": label},
        )  # fmt: skip
    return -Decimal(str(amount))


def test_the_overview_equals_the_views_and_the_validated_balances(
    client: TestClient, synced: int, statements_stored: None
) -> None:
    from core.statements import GROSS_PROFIT, NET_PROFIT
    from core.validation import Validator

    found = _get(client, "/api/v1/overview", financial_year=YEAR, as_of=AS_OF.isoformat())
    assert found["companies"] == [synced] and found["combined"] is False
    assert found["period_start"] == YEAR_START.isoformat()

    # Sales and the monthly chart: the monthly sales view (proven against the source).
    with Session(get_engine("report")) as session:
        view = {
            f"{m:%Y-%m-%d}": Decimal(str(n))
            for m, n in session.execute(
                text("SELECT month_start, net_sales FROM ledgerbridge_reporting.v_monthly_sales "
                     "WHERE entity_id = :e AND month_start BETWEEN :s AND :t"),
                {"e": synced, "s": YEAR_START, "t": AS_OF},
            )
        }  # fmt: skip
    monthly = {m["month"]: Decimal(m["net_sales"]) for m in found["monthly_sales"]}
    assert monthly and monthly == view
    assert Decimal(found["sales"]) == sum(view.values())

    # Profit: the stored Profit & Loss at the date less the one at the previous year end.
    for key, label in (("gross_profit", GROSS_PROFIT), ("net_profit", NET_PROFIT)):
        expected = _stored_profit(synced, AS_OF, label) - _stored_profit(
            synced, PREVIOUS_YEAR_END, label
        )
        assert Decimal(found[key]) == expected, key

    # Balances: the validator's ledger balances (checked against the source's closing ones).
    with Session(get_engine()) as session:
        balances = {
            b.id: b.balance for b in Validator(session, synced, AS_OF).ledger_balances(AS_OF)
        }

        def under(*roles: str) -> Decimal:
            ids = session.scalars(
                text("SELECT l.id FROM ledgerbridge_accounting.ledgers l JOIN "
                     "ledgerbridge_reporting.v_group_ancestors a ON a.group_id = l.group_id "
                     "JOIN ledgerbridge_accounting.account_groups g ON g.id = a.ancestor_id "
                     "WHERE l.entity_id = :e AND g.predefined_role IN :r AND l.is_deleted = 0"
                     ).bindparams(bindparam("r", expanding=True)),
                {"e": synced, "r": list(roles)},
            )  # fmt: skip
            return sum((balances[i] for i in ids), Decimal(0))

        assert Decimal(found["cash_and_bank"]) == under("cash_in_hand", "bank_accounts")
        assert Decimal(found["receivables"]) == under("sundry_debtors")
        assert Decimal(found["payables"]) == -under("sundry_creditors")
    assert Decimal(found["cash_and_bank"]) != 0 and Decimal(found["receivables"]) != 0


def test_the_overview_without_a_stored_statement_and_out_of_its_year(
    client: TestClient, synced: int, statements_stored: None
) -> None:
    mid_month = _get(client, "/api/v1/overview", financial_year=YEAR, as_of="2026-09-15")
    assert mid_month["gross_profit"] is None and mid_month["net_profit"] is None
    assert Decimal(mid_month["sales"]) == sum(
        Decimal(m["net_sales"]) for m in mid_month["monthly_sales"]
    )
    outside = client.get("/api/v1/overview", params={"financial_year": YEAR, "as_of": "2027-04-01"})
    assert outside.status_code == 422
