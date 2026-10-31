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
    # voucher type (the channels), and the only company's share.
    view = {f"{m:%Y-%m-%d}": Decimal(str(n)) for m, n in _view(synced, "v_monthly_sales")}
    by_type = sum(Decimal(str(n)) for _, n in _view(synced, "v_monthly_sales_by_voucher_type"))
    monthly = {m["month"]: Decimal(m["sales"]) for m in found["monthly"] if Decimal(m["sales"])}
    assert monthly and monthly == {m: v for m, v in view.items() if v}
    assert sum(Decimal(c["net_sales"]) for c in found["channels"]) == by_type
    (share,) = found["by_company"]
    assert Decimal(share["net_sales"]) == sum(view.values())
    assert Decimal(share["share_pct"]) == 100

    # Profit & Loss card: the stored statements, 30-Sep less 31-Mar.
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

    # Balance Sheet card: the stored statement at 30-Sep.
    bs = found["balance_sheet"]
    assert bs["available"] and bs["as_of"] == "2026-09-30"
    assert Decimal(bs["total_assets"]) >= Decimal(bs["current_assets"]) > 0

    # Balances: the validator's ledger balances (checked against the source's).
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


def test_profit_needs_stored_statements_and_compares_with_last_year(
    client: TestClient, synced: int, statements_stored: None
) -> None:
    # A range not ending on a stored date: sales yes, profit "—" with the reason.
    mid = _get(client, "/api/v1/home", date_from="2026-04-01", date_to="2026-09-15")
    assert mid["profit_loss"]["available"] is False
    assert "no statement is stored for 15-Sep-2026" in mid["profit_loss"]["reason"]
    assert mid["profit_loss"]["net_profit"]["value"] is None
    assert mid["balance_sheet"]["available"] is False
    assert sum(Decimal(m["sales"]) for m in mid["monthly"]) > 0
    # A range on stored dates: the same as the months.
    exact = _get(client, "/api/v1/home", date_from="2026-04-01", date_to="2026-09-30")
    months = _get(client, "/api/v1/home", month=MONTHS)
    assert exact["profit_loss"]["net_profit"] == months["profit_loss"]["net_profit"]
    # Last year: no statements for 2025's month ends, so no comparison, with the reason.
    compared = _get(client, "/api/v1/home", month=MONTHS, compare="true")["profit_loss"]
    assert compared["net_profit"]["last_year"] is None
    assert compared["net_profit"]["change_pct"] is None
    assert "no statement is stored" in compared["last_year_reason"]


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
    assert compared["columns"][-1]["key"] == "last_year"
    assert all(line["values"]["last_year"] is None for line in compared["lines"])
    assert "no statement is stored" in compared["last_year_reason"]

    # A range not ending on a stored date: no figures, with the reason.
    mid = _get(client, PL, date_from="2026-04-01", date_to="2026-09-15")
    assert mid["lines"] == [] and "15-Sep-2026" in mid["reason"]
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
