"""The dashboard API on MySQL as report_ro (D1; ADR-049): the recorded test-company fixtures
synced, then the explorer's totals against the monthly sales views and the books, groups
with their subtotals, lists, the CSV export and its row limit, companies on hold hidden, and
the data health read through `v_data_health` (./dev.ps1 up, or only the test MySQL with
migrations applied)."""

import csv
import io
from collections.abc import Iterator
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

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


# --- the dashboard home (D1 part b) -------------------------------------------------------

# The test company's books begin 1-Apr-2025; its vouchers are Apr to Sep 2026. Statements are
# stored at the month ends from Mar to Sep 2026 (31-Mar is the previous year end).
MONTH_ENDS = [date(2026, 3, 31), date(2026, 4, 30), date(2026, 5, 31), date(2026, 6, 30),
              date(2026, 7, 31), date(2026, 8, 31), date(2026, 9, 30)]  # fmt: skip
MONTHS = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]


@pytest.fixture
def statements_stored(synced: int) -> Iterator[None]:
    """Our statements at the month ends, as `./dev.ps1 statements` stores them (the
    source's own lines aren't needed for ours)."""
    from connectors.base import SourceStatements
    from core import statements
    from core.models.reporting import StatementLine

    with Session(get_engine()) as session:
        connection_id = session.scalar(
            select(A.EntitySource.connection_id).where(A.EntitySource.entity_id == synced)
        )
        for on in MONTH_ENDS:
            source = SourceStatements(as_of=on, lines=(), opening_stock=None, closing_stock=None)
            statements.refresh(session, synced, connection_id, "live", source)
        session.commit()
        try:
            yield
        finally:
            for model in (StatementLine, A.StockValue, A.FxRevaluationSnapshot):
                session.execute(delete(model).where(model.entity_id == synced))
            session.commit()


def _stored(entity_id: int, on: date, label: str) -> Decimal:
    with Session(get_engine("report")) as session:
        amount = session.scalar(
            text("SELECT amount FROM ledgerbridge_reporting.v_profit_loss "
                 "WHERE entity_id = :e AND as_of = :d AND label = :l"),
            {"e": entity_id, "d": on, "l": label},
        )  # fmt: skip
    return Decimal(str(amount or 0))


def _profit(entity_id: int, start: date, end: date, label: str) -> Decimal:
    return -(_stored(entity_id, end, label) - _stored(entity_id, start, label))


def _view(entity_id: int, view: str) -> list[tuple]:
    with Session(get_engine("report")) as session:
        return list(
            session.execute(
                text(f"SELECT month_start, net_sales FROM ledgerbridge_reporting.{view} "  # noqa: S608
                     "WHERE entity_id = :e AND month_start BETWEEN '2026-04-01' AND '2026-09-30'"),
                {"e": entity_id},
            )
        )  # fmt: skip


def test_the_home_equals_the_views_the_statements_and_the_validated_balances(
    client: TestClient, synced: int, statements_stored: None
) -> None:
    from core.statements import GROSS_PROFIT, NET_PROFIT
    from core.validation import Validator

    found = _get(client, "/api/v1/home", month=MONTHS)
    assert found["companies"] == [synced] and found["combined"] is False
    assert found["period"] == {
        "start": "2026-04-01", "end": "2026-09-30", "months": [f"{m}-01" for m in MONTHS],
    }  # fmt: skip

    # Sales: the monthly sales views (proven against the source), month by month and per
    # voucher type (the channels), and the only company's share (F-SAL-004, F-SAL-009,
    # F-SAL-015).
    view = {f"{m:%Y-%m-%d}": Decimal(str(n)) for m, n in _view(synced, "v_monthly_sales")}
    by_type = sum(Decimal(str(n)) for _, n in _view(synced, "v_monthly_sales_by_voucher_type"))
    monthly = {m["month"]: Decimal(m["sales"]) for m in found["monthly"] if Decimal(m["sales"])}
    assert monthly and monthly == {m: v for m, v in view.items() if v}
    assert sum(Decimal(c["net_sales"]) for c in found["channels"]) == by_type
    (share,) = found["by_company"]
    assert Decimal(share["net_sales"]) == sum(view.values())
    assert Decimal(share["share_pct"]) == 100

    # Profit & Loss: the stored statements, 30-Sep less 31-Mar (F-PL-001 to F-PL-004).
    pl = found["profit_loss"]
    assert pl["available"] and pl["as_of"] == "2026-09-30" and pl["shifted"] is False
    start, end = MONTH_ENDS[0], MONTH_ENDS[-1]
    assert Decimal(pl["gross_profit"]["value"]) == _profit(synced, start, end, GROSS_PROFIT)
    assert Decimal(pl["net_profit"]["value"]) == _profit(synced, start, end, NET_PROFIT)
    assert Decimal(pl["net_sales"]["value"]) == sum(view.values())
    net_sales, cost = Decimal(pl["net_sales"]["value"]), Decimal(pl["cost_of_sales"]["value"])
    assert net_sales - cost == Decimal(pl["gross_profit"]["value"])  # no direct incomes here

    # Months add up: April alone, then May to September.
    april = _get(client, "/api/v1/home", month="2026-04")["profit_loss"]["net_profit"]["value"]
    rest = _get(client, "/api/v1/home", month=MONTHS[1:])["profit_loss"]["net_profit"]["value"]
    assert Decimal(april) + Decimal(rest) == Decimal(pl["net_profit"]["value"])

    # The key figures: margins as a percentage of net sales (F-PL-005, F-PL-006); each month's
    # profit is that month's statement less the one before, and the months add up to the card.
    net = Decimal(pl["net_profit"]["value"])
    assert Decimal(pl["net_profit_pct"]["value"]) == (net / net_sales * 100).quantize(
        Decimal("0.1"), ROUND_HALF_UP
    )
    gross = Decimal(pl["gross_profit"]["value"])
    assert Decimal(pl["gross_margin_pct"]["value"]) == (gross / net_sales * 100).quantize(
        Decimal("0.1"), ROUND_HALF_UP
    )
    for before, month_end, m in zip(MONTH_ENDS[:-1], MONTH_ENDS[1:], found["monthly"], strict=True):
        assert Decimal(m["net_profit"]) == _profit(synced, before, month_end, NET_PROFIT)
        assert Decimal(m["gross_profit"]) == _profit(synced, before, month_end, GROSS_PROFIT)
    assert sum(Decimal(m["net_profit"]) for m in found["monthly"]) == net

    # Customers (F-SAL-011): those with sales in the period, as the Sales dashboard counts them (one
    # company here, so by name and by party are the same).
    sales = _get(client, "/api/v1/sales/dashboard", month=MONTHS)
    assert found["customers"]["value"] == sales["customers"] > 0

    # Balance Sheet: the stored statement at 30-Sep (F-BS-001, F-BS-002).
    bs = found["balance_sheet"]
    assert bs["available"] and bs["as_of"] == "2026-09-30"
    assert Decimal(bs["total_assets"]) >= Decimal(bs["current_assets"]) > 0

    # Balances: the validator's ledger balances, checked against the source's (F-BAL-002 to
    # F-BAL-004).
    with Session(get_engine()) as session:
        balances = {b.id: b.balance for b in Validator(session, synced, end).ledger_balances(end)}

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

        b = found["balances"]
        assert Decimal(b["cash_and_bank"]) == under("cash_in_hand", "bank_accounts") != 0
        assert Decimal(b["receivables"]) == under("sundry_debtors")
        assert Decimal(b["payables"]) == -under("sundry_creditors")


def test_profit_runs_to_the_last_stored_date_and_compares_with_a_period_before(
    client: TestClient, synced: int, statements_stored: None
) -> None:
    # A range not ending on a stored date (RPT-016, F-CMP-002): sales to its end, profit to
    # the last stored date within it, and said so.
    mid = _get(client, "/api/v1/home", date_from="2026-04-01", date_to="2026-09-15")
    to_august = _get(client, "/api/v1/home", month=MONTHS[:5])
    pl = mid["profit_loss"]
    assert pl["available"] is True and pl["cut"] is True and pl["as_of"] == "2026-08-31"
    assert pl["net_profit"] == to_august["profit_loss"]["net_profit"]
    assert mid["balance_sheet"]["as_of"] == "2026-08-31"
    assert sum(Decimal(m["sales"]) for m in mid["monthly"]) > 0
    # Before any stored date: no profit, with the reason.
    early = _get(client, "/api/v1/home", date_from="2026-10-01", date_to="2026-10-15")
    assert early["profit_loss"]["available"] is False
    assert (
        "no statement is stored between 01-Oct-2026 and 15-Oct-2026"
        in early["profit_loss"]["reason"]
    )
    # A range on stored dates: the same as the months.
    exact = _get(client, "/api/v1/home", date_from="2026-04-01", date_to="2026-09-30")
    months = _get(client, "/api/v1/home", month=MONTHS)
    assert exact["profit_loss"]["cut"] is False
    assert exact["profit_loss"]["net_profit"] == months["profit_loss"]["net_profit"]
    # Last year (`true`, as old links say): no statements for 2025's month ends, so no
    # comparison, with the reason.
    found = _get(client, "/api/v1/home", month=MONTHS, compare="true")
    compared = found["profit_loss"]
    assert found["compared_with"]["kind"] == "last_year"
    assert compared["net_profit"]["before"] is None
    assert compared["net_profit"]["change_pct"] is None
    assert "no statement is stored" in compared["before_reason"]
    assert compared["net_profit_pct"]["before"] is None
    # The previous period: May is compared with April.
    may = _get(client, "/api/v1/home", month="2026-05", compare="previous")
    april = _get(client, "/api/v1/home", month="2026-04")["profit_loss"]
    assert may["compared_with"] == {
        "kind": "previous", "label": "Previous period", "start": "2026-04-01",
        "end": "2026-04-30", "months": ["2026-04-01"],
    }  # fmt: skip
    assert may["profit_loss"]["net_profit"]["before"] == april["net_profit"]["value"]
    assert may["customers"]["before"] == april_customers(client)
    # Month to date: the same days of the month before.
    mtd = _get(client, "/api/v1/home", date_from="2026-06-01", date_to="2026-06-15",
               compare="previous", span="month")  # fmt: skip
    assert (mtd["compared_with"]["start"], mtd["compared_with"]["end"]) == (
        "2026-05-01", "2026-05-15",
    )  # fmt: skip
    # Each month's profit needs the whole month: the range's part of September has none.
    assert [m["net_profit"] is None for m in mid["monthly"]] == [False] * 5 + [True]


def test_the_overview_trend_summary_and_top_customers(
    client: TestClient, synced: int, statements_stored: None
) -> None:
    found = _get(client, "/api/v1/home", month=MONTHS)
    # The trend (F-OVR-001): the twelve months to September, each month as the home has it.
    trend = {t["month"]: t for t in found["trend"]}
    assert list(trend)[0] == "2025-10-01" and list(trend)[-1] == "2026-09-01" and len(trend) == 12
    for m in found["monthly"]:
        assert _d(trend[m["month"]]["net_sales"]) == _d(m["sales"])
        assert _d(trend[m["month"]]["net_profit"]) == _d(m["net_profit"])
    september = _get(client, "/api/v1/home", month="2026-09")
    assert _d(trend["2026-09-01"]["cash_and_bank"]) == _d(september["balances"]["cash_and_bank"])
    assert trend["2026-09-01"]["customers"] == september["customers"]["value"]
    assert trend["2025-10-01"]["gross_profit"] is None  # no statements before Mar-2026
    # The summary against last year (F-OVR-003): this period as the card, last year none.
    summary = {line["key"]: line for line in found["summary"]}
    pl = found["profit_loss"]
    assert _d(summary["net_profit"]["value"]) == _d(pl["net_profit"]["value"])
    assert _d(summary["net_profit_pct"]["value"]) == _d(pl["net_profit_pct"]["value"])
    assert summary["net_sales"]["last_year"] is None and found["summary_reason"]
    # Top customers (F-OVR-002): the largest first, as their pages have them.
    top = found["top_customers"]
    assert top and [Decimal(c["net_sales"]) for c in top] == sorted(
        (Decimal(c["net_sales"]) for c in top), reverse=True
    )
    first = top[0]
    page = _get(client, f"/api/v1/parties/customers/{first['party_id']}", month=MONTHS)
    assert _d(first["balance"]) == _d(page["balance"])
    assert _d(first["overdue"]) == _d(page["overdue"])
    assert _d(first["net_sales"]) == _d(page["net"]["value"])
    assert first["status"] == ("overdue" if Decimal(first["overdue"]) > 0 else "current")


def _d(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def april_customers(client: TestClient) -> int:
    return _get(client, "/api/v1/home", month="2026-04")["customers"]["value"]


def test_bad_periods_are_refused(client: TestClient, synced: int) -> None:
    bad = [
        {},
        {"month": "2026-4"},
        {"month": "2026-04", "date_from": "2026-04-01"},
        {"date_from": "2026-05-01", "date_to": "2026-04-01"},
    ]
    for params in bad:
        assert client.get("/api/v1/home", params=params).status_code == 422, params


def test_the_companies_show_whether_the_source_had_them_loaded(
    client: TestClient, synced: int
) -> None:
    (company,) = _get(client, "/api/v1/companies")
    health = company["health"]
    assert health["source_name"] == "Tally"
    assert health["source_loaded"] is True and health["source_checked_by"] == "sync"
    assert health["source_checked_at"] is not None


# --- the Profit & Loss report page (D1 part c1) -------------------------------------------

PL = "/api/v1/reports/profit-loss"


def _line(report: dict, label: str) -> dict:
    return next(line for line in report["lines"] if line["label"] == label)


def test_the_profit_and_loss_report_adds_up(
    client: TestClient, synced: int, statements_stored: None
) -> None:
    from core.statements import GROSS_PROFIT, NET_PROFIT

    home = _get(client, "/api/v1/home", month=MONTHS)["profit_loss"]
    by_company = _get(client, PL, month=MONTHS, view="company")
    assert [c["key"] for c in by_company["columns"]] == [f"company:{synced}", "total"]
    assert by_company["combined"] is False and by_company["reason"] is None
    labels = [line["label"] for line in by_company["lines"]]
    assert labels.index(GROSS_PROFIT) < labels.index(NET_PROFIT)  # the source's order
    for label, key in ((NET_PROFIT, "net_profit"), (GROSS_PROFIT, "gross_profit")):
        line = _line(by_company, label)
        assert Decimal(line["values"]["total"]) == Decimal(home[key]["value"])
        assert line["values"]["total"] == line["values"][f"company:{synced}"]

    # Month by month and quarter by quarter: every line's columns add up to its total.
    for view in ("month", "quarter"):
        report = _get(client, PL, month=MONTHS, view=view)
        kinds = {c["kind"] for c in report["columns"]}
        assert kinds == {view, "total"}
        for line in report["lines"]:
            parts = [Decimal(v) for k, v in line["values"].items() if k != "total" and v]
            assert sum(parts, Decimal(0)) == Decimal(line["values"]["total"]), (view, line["label"])

    # % of sales: net sales is 100% of itself.
    sales = next(line for line in by_company["lines"] if line["pct_of_sales"]["total"] == "100.0")
    assert Decimal(sales["values"]["total"]) == Decimal(home["net_sales"]["value"])

    # Last year: a column, unavailable (no statements for 2025's month ends here), and why.
    compared = _get(client, PL, month=MONTHS, compare="true")
    assert compared["columns"][-1] == {"key": "before", "label": "Last year", "kind": "before"}
    assert all(line["values"]["before"] is None for line in compared["lines"])
    assert "no statement is stored" in compared["before_reason"]
    # The previous period: May against April, the change against it.
    may = _get(client, PL, month="2026-05", compare="previous")
    april = _get(client, PL, month="2026-04")
    april_totals = {line["key"]: line["values"]["total"] for line in april["lines"]}
    assert may["columns"][-1]["label"] == "Previous period"
    assert {line["key"]: line["values"]["before"] for line in may["lines"]} == april_totals

    # A range not ending on a stored date: the figures to the last stored date within it.
    mid = _get(client, PL, date_from="2026-04-01", date_to="2026-09-15")
    to_august = _get(client, PL, month=MONTHS[:5])
    assert [line["values"]["total"] for line in mid["lines"]] == [
        line["values"]["total"] for line in to_august["lines"]
    ]
    assert client.get(PL, params={"month": MONTHS, "view": "ledger"}).status_code == 422


def test_matches_tally_counts_the_source_lines_that_differ(
    client: TestClient, synced: int, statements_stored: None
) -> None:
    """With the source's own lines stored equal to ours, the report matches; one differing
    line makes it not match (stored as `./dev.ps1 statements` stores them)."""
    from connectors.base import SourceStatements, StatementLine
    from core import statements
    from core.models.reporting import StatementLine as Row

    before = _get(client, PL, month=MONTHS)["matching"]
    assert before["compared"] == 0 and before["matches"] is False  # nothing to compare yet
    assert before["unchecked"] > 0

    def store_source(on: date, change: Decimal) -> None:
        with Session(get_engine()) as session:
            ours = session.execute(
                select(Row.label, Row.level, Row.amount).where(
                    Row.entity_id == synced, Row.as_of == on, Row.figures == "ours",
                    Row.statement == "profit_loss", Row.level != "detail",
                )
            ).all()  # fmt: skip
            lines = tuple(
                StatementLine("profit_loss", label, level, amount + (change if i == 0 else 0))
                for i, (label, level, amount) in enumerate(ours)
            )
            connection_id = session.scalar(
                select(A.EntitySource.connection_id).where(A.EntitySource.entity_id == synced)
            )
            source = SourceStatements(as_of=on, lines=lines, opening_stock=None, closing_stock=None)
            statements.refresh(session, synced, connection_id, "live", source)
            session.commit()

    store_source(MONTH_ENDS[-1], Decimal(0))
    partly = _get(client, PL, month=MONTHS)["matching"]
    assert partly["differing"] == 0 and partly["unchecked"] > 0  # other dates not compared
    assert partly["matches"] is False
    for on in MONTH_ENDS:
        store_source(on, Decimal(0))
    matched = _get(client, PL, month=MONTHS)["matching"]
    assert matched["compared"] > 0 and matched["differing"] == 0 and matched["unchecked"] == 0
    assert matched["matches"] is True
    used = matched["dates"]  # the month ends (31-Mar too where the books began earlier)
    assert used[-1] == "2026-09-30" and set(used) <= {f"{d:%Y-%m-%d}" for d in MONTH_ENDS}

    store_source(MONTH_ENDS[-1], Decimal(1))
    differs = _get(client, PL, month=MONTHS)["matching"]
    assert differs["differing"] >= 1 and differs["matches"] is False


# --- the top filter bar's facets (navigation) ----------------------------------------------


def test_facet_values_for_the_selected_companies(client: TestClient, synced: int) -> None:
    with Session(get_engine("report")) as session:
        customers = set(
            session.scalars(
                select(A.Party.name).where(
                    A.Party.entity_id == synced,
                    A.Party.party_type.in_(("customer", "both")),
                    A.Party.is_deleted.is_(False),
                )
            )
        )
        sales_types = set(
            session.scalars(
                select(A.VoucherType.name).where(
                    A.VoucherType.entity_id == synced, A.VoucherType.base_type == "sales"
                )
            )
        )
    found = _get(client, "/api/v1/facets/customer")
    assert {v["value"] for v in found} == customers and all(v["companies"] == 1 for v in found)
    assert {v["value"] for v in _get(client, "/api/v1/facets/channel")} == sales_types
    assert _get(client, "/api/v1/facets/voucher_type")
    assert _get(client, "/api/v1/facets/ledger_group")
    first = sorted(customers)[0]
    narrowed = _get(client, "/api/v1/facets/customer", search=first[1:4].upper())
    assert first in {v["value"] for v in narrowed}
    assert _get(client, "/api/v1/facets/customer", search="%_no such name_%") == []
    assert client.get("/api/v1/facets/ledger").status_code == 422
    assert client.get("/api/v1/facets/customer", params={"search": "x" * 101}).status_code == 422


# --- the Sales dashboard (D2) ---------------------------------------------------------------


def _sales_view(entity_id: int) -> dict[str, tuple[Decimal, ...]]:
    """month -> (gross, returns, other, net) from v_monthly_sales, Apr to Sep 2026."""
    with Session(get_engine("report")) as session:
        rows = session.execute(
            text("SELECT month_start, gross_sales, sales_returns, other_adjustments, net_sales "
                 "FROM ledgerbridge_reporting.v_monthly_sales WHERE entity_id = :e "
                 "AND month_start BETWEEN '2026-04-01' AND '2026-09-30'"),
            {"e": entity_id},
        )  # fmt: skip
        return {f"{m:%Y-%m-%d}": tuple(Decimal(str(x)) for x in rest) for m, *rest in rows}


def _invoices_in_view(entity_id: int) -> int:
    with Session(get_engine("report")) as session:
        return int(
            session.scalar(
                text(
                    "SELECT COALESCE(SUM(vouchers), 0) FROM "
                    "ledgerbridge_reporting.v_monthly_sales_by_voucher_type WHERE entity_id = :e "
                    "AND base_type = 'sales' AND month_start BETWEEN '2026-04-01' AND '2026-09-30'"
                ),
                {"e": entity_id},
            )  # fmt: skip
        )


def test_the_sales_dashboard_equals_the_monthly_sales_views(
    client: TestClient, synced: int
) -> None:
    found = _get(client, "/api/v1/sales/dashboard", month=MONTHS)
    view = _sales_view(synced)
    assert view, "the test company has sales"

    # Month by month: gross, returns, other adjustments and net, as the proven view has them.
    monthly = {
        m["month"]: (
            Decimal(m["gross"]),
            Decimal(m["returns"]),
            Decimal(m["other"]),
            Decimal(m["net"]),
        )
        for m in found["monthly"]
    }
    assert {m: v for m, v in monthly.items() if any(v)} == view

    # Key figures: the period's totals; invoices are the sales vouchers the view counts.
    k = found["key_figures"]
    net = sum(v[3] for v in view.values())
    gross = sum(v[0] for v in view.values())
    invoices = _invoices_in_view(synced)
    assert Decimal(k["net_sales"]["value"]) == net
    assert Decimal(k["sales_returns"]["value"]) == -sum(v[1] for v in view.values())
    assert Decimal(k["invoices"]["value"]) == invoices > 0
    assert Decimal(k["average_invoice"]["value"]) == (gross / invoices).quantize(Decimal("0.01"))
    assert k["net_sales"]["before"] is None and found["compared_with"] is None

    # Customers: the top ones and the rest add up to net sales.
    tops = found["top_customers"]
    assert tops and len(tops) <= 10
    nets = [Decimal(c["net_sales"]) for c in tops]
    assert nets == sorted(nets, reverse=True)
    assert sum(nets) + Decimal(found["other_customers"]) == net
    assert found["customers"] >= len(tops)

    # Largest invoices: sales vouchers of these companies, largest first.
    largest = found["largest_invoices"]
    amounts = [Decimal(i["amount"]) for i in largest]
    assert largest and amounts == sorted(amounts, reverse=True)
    assert {i["company"] for i in largest} == {synced}
    with Session(get_engine("report")) as session:
        types = session.execute(
            select(A.Voucher.id, A.VoucherType.base_type)
            .join(A.VoucherType, A.VoucherType.id == A.Voucher.voucher_type_id)
            .where(A.Voucher.id.in_([i["voucher_id"] for i in largest]))
        ).all()
    assert {base for _, base in types} == {"sales"}


def test_the_sales_dashboard_facets_and_comparison(client: TestClient, synced: int) -> None:
    whole = _get(client, "/api/v1/sales/dashboard", month=MONTHS, compare="true")
    net = Decimal(whole["key_figures"]["net_sales"]["value"])
    # Last year has no sales: a comparison with zero has no percentage.
    assert Decimal(whole["key_figures"]["net_sales"]["before"]) == 0
    assert whole["key_figures"]["net_sales"]["change_pct"] is None

    # One customer: their own net sales, as the top customers list has them.
    top = whole["top_customers"][0]
    one = _get(client, "/api/v1/sales/dashboard", month=MONTHS, customer=top["name"])
    assert Decimal(one["key_figures"]["net_sales"]["value"]) == Decimal(top["net_sales"])
    assert [c["name"] for c in one["top_customers"]] == [top["name"]]

    # The channels split net sales without loss, as the per-voucher-type view does.
    with Session(get_engine("report")) as session:
        channels = list(
            session.scalars(
                select(A.VoucherType.name).where(
                    A.VoucherType.entity_id == synced, A.VoucherType.is_deleted.is_(False)
                )
            )
        )
    by_channel = [
        Decimal(_get(client, "/api/v1/sales/dashboard", month=MONTHS, channel=c)["key_figures"]
                ["net_sales"]["value"])
        for c in sorted(set(channels))
    ]  # fmt: skip
    assert sum(by_channel) == net
    assert (
        _get(client, "/api/v1/sales/dashboard", month=MONTHS, customer="no such customer")[
            "top_customers"
        ]
        == []
    )
    assert (
        client.get("/api/v1/sales/dashboard", params={"month": MONTHS, "customer": "x" * 256})
    ).status_code == 422


# --- the Sales and Purchase registers (D2) --------------------------------------------------


def _books_vouchers(entity_id: int, bases: tuple[str, ...]) -> dict[int, tuple[Decimal, str]]:
    """voucher id -> (first effective entry's amount, its ledger) from the books."""
    with Session(get_engine("report")) as session:
        rows = session.execute(
            text("SELECT v.id, vl.amount, l.name FROM ledgerbridge_accounting.vouchers v "
                 "JOIN ledgerbridge_accounting.voucher_types t ON t.id = v.voucher_type_id "
                 "JOIN ledgerbridge_accounting.voucher_lines vl ON vl.voucher_id = v.id "
                 "JOIN ledgerbridge_accounting.ledgers l ON l.id = vl.ledger_id "
                 "WHERE v.entity_id = :e AND v.is_deleted = 0 AND vl.is_effective = 1 "
                 "AND t.base_type IN :b AND v.voucher_date BETWEEN '2026-04-01' AND '2026-09-30' "
                 "AND vl.line_no = (SELECT MIN(x.line_no) "
                 "FROM ledgerbridge_accounting.voucher_lines x "
                 "WHERE x.voucher_id = v.id AND x.is_effective = 1)"
                 ).bindparams(bindparam("b", expanding=True)),
            {"e": entity_id, "b": list(bases)},
        )  # fmt: skip
        return {vid: (Decimal(str(amount)), name) for vid, amount, name in rows}


def test_the_sales_register_is_the_day_book_of_sales_and_credit_notes(
    client: TestClient, synced: int
) -> None:
    found = _get(client, "/api/v1/registers/sales", month=MONTHS)
    rows = found["rows"]
    assert rows and found["truncated"] is False and found["side"] == "sales"

    # Every sales voucher and credit note, once, with its first entry as Debit or Credit.
    books = _books_vouchers(synced, ("sales", "credit_note"))
    assert {r["voucher_id"] for r in rows} == set(books) and len(rows) == len(books)
    for r in rows:
        amount, ledger = books[r["voucher_id"]]
        shown = Decimal(r["debit"] or 0) - Decimal(r["credit"] or 0)
        assert shown == amount and r["particulars"] == ledger
        assert (r["debit"] is None) != (r["credit"] is None)
    assert [r["date"] for r in rows] == sorted(r["date"] for r in rows)
    assert any(r["is_return"] for r in rows) or not any(v[1] for v in _sales_view(synced).values())

    # Its value on the sales ledgers is gross plus returns, month by month, as the proven view.
    by_month: dict[str, Decimal] = {}
    for r in rows:
        month = r["date"][:7] + "-01"
        by_month[month] = by_month.get(month, Decimal(0)) + Decimal(r["side_value"])
    view = {m: v[0] + v[1] for m, v in _sales_view(synced).items()}
    assert {m: v for m, v in by_month.items() if v} == {m: v for m, v in view.items() if v}


def test_the_purchase_register_and_the_facets(client: TestClient, synced: int) -> None:
    found = _get(client, "/api/v1/registers/purchases", month=MONTHS)
    books = _books_vouchers(synced, ("purchase", "debit_note"))
    assert {r["voucher_id"] for r in found["rows"]} == set(books)
    assert all(Decimal(r["side_value"]) >= 0 or r["is_return"] for r in found["rows"])

    sales = _get(client, "/api/v1/registers/sales", month=MONTHS)["rows"]
    one_type = sales[0]["voucher_type"]
    narrowed = _get(client, "/api/v1/registers/sales", month=MONTHS, voucher_type=one_type)
    assert {r["voucher_id"] for r in narrowed["rows"]} == {
        r["voucher_id"] for r in sales if r["voucher_type"] == one_type
    }
    named = next(r["party"] for r in sales if r["party"])
    by_party = _get(client, "/api/v1/registers/sales", month=MONTHS, party=named)["rows"]
    assert by_party and all(r["party"] == named for r in by_party)
    assert client.get("/api/v1/registers/receipts", params={"month": MONTHS}).status_code == 422


def test_a_long_register_says_it_was_cut(synced: int) -> None:
    from core.registers import register
    from core.report_periods import Period
    from core.sales import SALES_SIDE

    with Session(get_engine("report")) as session:
        months = Period.of_months([date(2026, m, 1) for m in range(4, 10)])
        found = register(session, [synced], months, SALES_SIDE, limit=1)
    assert len(found.rows) == 1 and found.truncated is True


# --- monthly sales and purchases, sales by channel (D2) -------------------------------------


def test_monthly_sales_with_the_closing_balance_equal_the_view(
    client: TestClient, synced: int
) -> None:
    found = _get(client, "/api/v1/monthly/sales", month=MONTHS)
    view = _sales_view(synced)
    months = {
        m["month"]: (
            Decimal(m["gross"]),
            Decimal(m["returns"]),
            Decimal(m["other"]),
            Decimal(m["net"]),
        )
        for m in found["months"]
    }
    assert {m: v for m, v in months.items() if any(v)} == view
    # The closing balance runs from the financial year's start (April): net added up.
    running = Decimal(0)
    for m in found["months"]:
        running += Decimal(m["net"])
        assert Decimal(m["closing"]) == running
    # A later month alone still closes on the year to date.
    september = _get(client, "/api/v1/monthly/sales", month="2026-09")["months"]
    assert [m["closing"] for m in september] == [found["months"][-1]["closing"]]


def test_monthly_purchases_equal_the_home_figures(client: TestClient, synced: int) -> None:
    found = _get(client, "/api/v1/monthly/purchases", month=MONTHS)
    home = _get(client, "/api/v1/home", month=MONTHS)
    assert {m["month"]: Decimal(m["net"]) for m in found["months"]} == {
        m["month"]: Decimal(m["purchases"]) for m in home["monthly"]
    }
    assert any(Decimal(m["net"]) for m in found["months"])
    assert Decimal(found["months"][-1]["closing"]) == sum(
        Decimal(m["net"]) for m in found["months"]
    )


def test_sales_by_channel_equal_the_view_by_voucher_type(client: TestClient, synced: int) -> None:
    found = _get(client, "/api/v1/sales/channels", month=MONTHS)
    with Session(get_engine("report")) as session:
        rows = session.execute(
            text("SELECT voucher_type, month_start, SUM(net_sales) FROM "
                 "ledgerbridge_reporting.v_monthly_sales_by_voucher_type WHERE entity_id = :e "
                 "AND month_start BETWEEN '2026-04-01' AND '2026-09-30' "
                 "GROUP BY voucher_type, month_start"),
            {"e": synced},
        ).all()  # fmt: skip
    view = {(name, f"{m:%Y-%m-%d}"): Decimal(str(n)) for name, m, n in rows if n}
    ours = {
        (c["name"], m["month"]): Decimal(m["net"])
        for c in found["channels"]
        for m in c["months"]
        if Decimal(m["net"])
    }
    assert ours and ours == view
    nets = [Decimal(c["net"]) for c in found["channels"]]
    assert nets == sorted(nets, reverse=True)
    assert all(len(c["months"]) == len(MONTHS) for c in found["channels"])
    shares = sum(Decimal(c["share_pct"]) for c in found["channels"])
    assert abs(shares - 100) <= Decimal("0.1") * len(found["channels"])


# --- customers and vendors (D2) -------------------------------------------------------------


def _party_balances(entity_id: int, names: set[str]) -> dict[str, Decimal]:
    """Each party name's ledger balance at 30-Sep from the validator (checked against the
    source's)."""
    from core.validation import Validator

    end = date(2026, 9, 30)
    with Session(get_engine()) as session:
        balances = {
            b.id: b.balance for b in Validator(session, entity_id, end).ledger_balances(end)
        }
        rows = session.execute(
            select(A.Ledger.id, A.Party.name)
            .join(A.Party, A.Party.id == A.Ledger.party_id)
            .where(A.Ledger.entity_id == entity_id, A.Ledger.is_deleted.is_(False))
        ).all()
    found: dict[str, Decimal] = {}
    for ledger, name in rows:
        if name in names:
            found[name] = found.get(name, Decimal(0)) + balances.get(ledger, Decimal(0))
    return found


def test_the_customers_and_vendors_lists(client: TestClient, synced: int) -> None:
    customers = _get(client, "/api/v1/parties/customers", month=MONTHS)["parties"]
    vendors = _get(client, "/api/v1/parties/vendors", month=MONTHS)["parties"]
    assert customers and vendors

    # Balances: the validator's ledger balances (customers owe: debit; vendors are owed).
    names = {c["name"] for c in customers}
    validated = _party_balances(synced, names)
    assert {c["name"]: Decimal(c["balance"]) for c in customers} == {
        n: validated.get(n, Decimal(0)) for n in names
    }
    vendor_names = {v["name"] for v in vendors}
    validated = _party_balances(synced, vendor_names)
    assert {v["name"]: Decimal(v["balance"]) for v in vendors} == {
        n: -validated.get(n, Decimal(0)) for n in vendor_names
    }

    # Sales: each customer's as the Sales dashboard filtered to them has it.
    busiest = sorted(customers, key=lambda c: Decimal(c["net"]), reverse=True)[:3]
    for c in busiest:
        one = _get(client, "/api/v1/sales/dashboard", month=MONTHS, customer=c["name"])
        assert Decimal(c["net"]) == Decimal(one["key_figures"]["net_sales"]["value"])
        assert Decimal(c["invoices"]) == Decimal(one["key_figures"]["invoices"]["value"])


def test_a_customer_page_adds_up(client: TestClient, synced: int) -> None:
    customers = _get(client, "/api/v1/parties/customers", month=MONTHS)["parties"]
    top = max(customers, key=lambda c: Decimal(c["net"]))
    page = _get(client, f"/api/v1/parties/customers/{top['party_id']}", month=MONTHS)
    assert page["name"] == top["name"] and page["companies"] == [synced]
    assert page["group_path"] and Decimal(page["balance"]) == Decimal(top["balance"])

    # The ledger statement runs from the opening to the balance due.
    entries = page["statement"]
    assert entries and page["statement_truncated"] is False
    running = Decimal(page["statement_opening"])
    for e in entries:
        running += Decimal(e["debit"] or 0) - Decimal(e["credit"] or 0)
        assert Decimal(e["balance"]) == running
    assert running == Decimal(page["balance"])

    # Sales and invoices: the Sales dashboard and the Sales register filtered to the customer.
    assert Decimal(page["net"]["value"]) == Decimal(top["net"])
    register = _get(client, "/api/v1/registers/sales", month=MONTHS, party=top["name"])["rows"]
    assert [i["voucher_id"] for i in page["invoices_list"]] == [r["voucher_id"] for r in register]
    assert {i["status"] for i in page["invoices_list"]} <= {"paid", "due", "overdue", "no_bill"}
    assert sum(Decimal(m["net"]) for m in page["monthly"]) == Decimal(page["net"]["value"])

    # Receipts are receipt vouchers; the monthly trend has them all.
    received = sum(Decimal(s["amount"]) for s in page["settlements"])
    assert received == Decimal(page["settled"])
    assert sum(Decimal(m["settled"]) for m in page["monthly"]) == received

    # Bills: every bill allocation (not on account) on the customer's ledgers up to 30-Sep.
    with Session(get_engine("report")) as session:
        stored = session.scalar(
            select(func.coalesce(func.sum(A.BillAllocation.amount), 0))
            .join(A.VoucherLine, A.VoucherLine.id == A.BillAllocation.voucher_line_id)
            .join(A.Ledger, A.Ledger.id == A.VoucherLine.ledger_id)
            .join(A.Party, A.Party.id == A.Ledger.party_id)
            .join(A.Voucher, A.Voucher.id == A.VoucherLine.voucher_id)
            .where(
                A.Party.name == top["name"],
                A.Ledger.entity_id == synced,
                A.VoucherLine.is_effective.is_(True),
                A.Voucher.is_deleted.is_(False),
                A.BillAllocation.bill_type != "on_account",
                A.VoucherLine.voucher_date <= date(2026, 9, 30),
            )
        )
    assert Decimal(page["bills_cover"]) == Decimal(str(stored))
    assert sum(Decimal(b["amount"]) for b in page["bills"]) == Decimal(page["bills_cover"])
    overdue = sum(
        Decimal(b["amount"])
        for b in page["bills"]
        if b["overdue_days"] > 0 and Decimal(b["amount"]) > 0
    )
    assert Decimal(page["overdue"]) == overdue


def test_a_vendor_page_and_unknown_parties(client: TestClient, synced: int) -> None:
    vendors = _get(client, "/api/v1/parties/vendors", month=MONTHS)["parties"]
    top = max(vendors, key=lambda v: Decimal(v["net"]))
    page = _get(client, f"/api/v1/parties/vendors/{top['party_id']}", month=MONTHS)
    assert Decimal(page["balance"]) == Decimal(top["balance"])
    assert Decimal(page["net"]["value"]) == Decimal(top["net"])
    assert -(Decimal(page["statement"][-1]["balance"])) == Decimal(page["balance"])
    missing = client.get("/api/v1/parties/customers/999999999", params={"month": MONTHS})
    assert missing.status_code == 404
    assert client.get("/api/v1/parties/banks", params={"month": MONTHS}).status_code == 422
