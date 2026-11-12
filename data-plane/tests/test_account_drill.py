"""The Balance Sheet's drill-down and the Ledger statement (ADR-055), on the test company's
recordings: each line's rows add up to the stored Balance Sheet line at every level and each
ledger equals Tally's ledger balance; the Ledger statement equals Tally's Ledger Vouchers
report (the dollar customer's, with Tally's calculated revaluation row) and the ledger's
balance in Tally at the period's start and end."""

import json
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_report_session
from api.main import create_app
from connectors.tally import envelopes, parser
from connectors.tally.connector import TallyConnector, _canonical, report_rows
from core.balance_sheet_drill import drill
from core.ledger_statement import ledger_statement
from core.models import accounting as A  # noqa: N812
from core.models import system as S  # noqa: N812
from core.models.reporting import StatementLine as LineRow
from core.report_periods import Period
from core.statements import match_key
from tests.conftest import FIXTURES
from tests.stock_replay import LAYOUT, YEAR_END, replay
from tests.test_forex import FOREX_FIXTURES
from tests.test_statements import AS_OF, YEAR_END_DATES, _synced
from tests.test_trial_balance import _refresh

LAYOUT_DATES = (date(2026, 8, 31), AS_OF)


@pytest.fixture
def layout_books(db: Session, monkeypatch: pytest.MonkeyPatch) -> S.Connection:
    """After the statement layout seed (2026-10-23): the dollar customer."""
    return _synced(db, monkeypatch, LAYOUT / "books")


@pytest.fixture
def year_end_books(db: Session, monkeypatch: pytest.MonkeyPatch) -> S.Connection:
    """After the year-end seed: books from 1 April 2025 (2026-10-24)."""
    return _synced(db, monkeypatch, YEAR_END / "books")


def _tally_ledgers(case: str, period: tuple[date, date]) -> dict[str, Decimal]:
    connector = TallyConnector.from_config(
        {"url": "http://tally.test:9000", "educational": "yes"}, transport=replay(case, YEAR_END)
    )
    entity = connector.list_entities()[0]
    return {
        match_key(x.get("NAME") or ""): _canonical(x.findtext("CLOSINGBALANCE"))
        for x in connector._export_objects(
            entity, envelopes.LEDGER_BALANCES, balances_period=period
        )
    }


@pytest.mark.parametrize("as_of", YEAR_END_DATES)
def test_every_balance_sheet_line_drills_down_to_its_ledgers(
    db: Session,
    year_end_books: S.Connection,
    as_of: date,
) -> None:
    """Every main line of the stored Balance Sheet: its rows add up to it at every level,
    and each ledger row is Tally's ledger balance at the date (from the books' beginning)."""
    _refresh(db, year_end_books, "integrated", YEAR_END, YEAR_END_DATES)
    entity_id = db.scalars(select(A.Entity)).one().id
    tally = _tally_ledgers("integrated", (date(2025, 4, 1), as_of))
    drilled = 0
    for label, section, amount in db.execute(
        select(LineRow.label, LineRow.section, LineRow.amount).where(
            LineRow.as_of == as_of, LineRow.statement == "balance_sheet",
            LineRow.figures == "ours", LineRow.level == "main",
        )
    ):  # fmt: skip
        if "forex" in label.casefold() or not amount:  # no rows under a line without amount
            continue
        key = f"{section}:{match_key(label)}"
        found = drill(db, [entity_id], as_of, key)
        assert found.reason is None, key
        root = found.rows[0]
        shown = amount if section == "assets" else -amount  # as the Balance Sheet shows it
        assert root.amount == shown, label  # equals the stored line
        children: dict[str, Decimal] = {}
        for row in found.rows[1:]:
            children[row.parent] = children.get(row.parent, Decimal(0)) + row.amount
            if row.kind == "ledger":
                sign = 1 if found.section == "assets" else -1
                assert row.amount == tally[match_key(row.label)] * sign, row.label
        for row in found.rows:
            if row.key in children:
                assert children[row.key] == row.amount, row.label  # each level adds up
        drilled += 1
    assert drilled >= 5


def test_profit_loss_account_drills_to_its_two_parts(
    db: Session,
    year_end_books: S.Connection,
) -> None:
    _refresh(db, year_end_books, "integrated", YEAR_END, YEAR_END_DATES)
    entity_id = db.scalars(select(A.Entity)).one().id
    found = drill(db, [entity_id], AS_OF, "liabilities:profit & loss a/c")
    assert [r.label for r in found.rows] == [
        "Profit & Loss A/c",
        "Opening Balance",
        "Current Period",
    ]
    assert found.rows[0].amount == found.rows[1].amount + found.rows[2].amount


def test_the_ledger_statement_equals_tallys_ledger_vouchers_report(
    db: Session,
    layout_books: S.Connection,
) -> None:
    """The dollar customer (the layout seed): its sale on 1 August 2026, then Tally's own
    calculated "Unadjusted Forex Gain/Loss" row on the report's To date (2 October 2026),
    so the closing is the revalued balance."""
    _refresh(db, layout_books, "integrated", LAYOUT, LAYOUT_DATES)
    ledger = db.scalars(select(A.Ledger).where(A.Ledger.name == "Customer Delta USD")).one()
    found = ledger_statement(db, ledger.id, Period(date(2026, 4, 1), AS_OF))
    assert found is not None
    tally = report_rows((FOREX_FIXTURES / "ledger_vouchers_report.xml").read_bytes())
    ours = [(e.on, e.particulars, e.amount) for e in found.entries]
    theirs = [(datetime.strptime(r.on, "%d-%b-%y").date(), r.account, r.amount) for r in tally]
    assert ours == theirs
    assert found.entries[0].voucher_id is not None and found.entries[-1].voucher_id is None
    assert found.closing == found.opening + sum((e.amount for e in found.entries), Decimal(0))
    assert found.entries[-1].running == found.closing


LEDGER_REPORTS = FIXTURES / "tally" / "rules" / "ledger_report"


def _ledger_report_manifest() -> dict:
    path = LEDGER_REPORTS / "manifest.json"
    if not path.exists():
        pytest.skip(
            "no recording yet: python -m connectors.tally.tools capture-ledger-report "
            "(LedgerBridge Test Co only loaded in TallyPrime)"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def test_each_recorded_ledger_equals_tallys_ledger_vouchers(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The recorded ledgers (a bank, a customer, a sales ledger; capture-ledger-report): the
    statement's vouchers are Tally's own list for the ledger, voucher by voucher (date,
    number, amount); its opening and closing are Tally's balances for the period; and where
    Tally's Ledger Vouchers report could be read (months ending on the 31st, Educational
    mode), each row's date, Particulars and amount are the report's."""
    manifest = _ledger_report_manifest()
    _synced(db, monkeypatch, LEDGER_REPORTS / "books")
    period = Period(date.fromisoformat(manifest["start"]), date.fromisoformat(manifest["end"]))
    balances = {
        match_key(x.get("NAME") or ""): (
            _canonical(x.findtext("OPENINGBALANCE")), _canonical(x.findtext("CLOSINGBALANCE"))
        )
        for x in parser.objects(
            parser.parse_response((LEDGER_REPORTS / manifest["balances"]).read_bytes()),
            envelopes.LEDGER_BALANCES.object_tag,
        )
    }  # fmt: skip
    for name, files in manifest["ledgers"].items():
        ledger = db.scalars(select(A.Ledger).where(A.Ledger.name == name)).one()
        found = ledger_statement(db, ledger.id, period)
        assert found is not None
        assert (found.opening, found.closing) == balances[match_key(name)], name
        theirs = sorted(
            (v.findtext("DATE"), v.findtext("VOUCHERNUMBER"))
            for f in files if "_vouchers_" in f
            for v in parser.objects(
                parser.parse_response((LEDGER_REPORTS / f).read_bytes()), "VOUCHER"
            )
            if (v.findtext("ISCANCELLED") or "No") == "No"
            and (v.findtext("ISOPTIONAL") or "No") == "No"
        )  # fmt: skip
        ours = sorted((f"{e.on:%Y%m%d}", e.number) for e in found.entries if e.voucher_id)
        assert ours == theirs, name
        for f in files:
            if "_report_" not in f:
                continue
            month = f.rsplit("_", 1)[1].removesuffix(".xml")[:7]
            rows = report_rows((LEDGER_REPORTS / f).read_bytes())
            shown = [
                (datetime.strptime(r.on, "%d-%b-%y").date(), r.account, r.amount) for r in rows
            ]
            mine = [
                (e.on, e.particulars, e.amount) for e in found.entries if f"{e.on:%Y-%m}" == month
            ]
            assert mine == shown, (name, month)


@pytest.fixture
def api(db: Session) -> Iterator[TestClient]:
    """The dashboard API on the test database, the caller seeing every company."""
    app = create_app()
    app.dependency_overrides[get_report_session] = lambda: db
    yield TestClient(app, base_url="http://localhost")


def test_the_api_serves_the_trial_balance_drill_and_ledger_statement(
    db: Session,
    year_end_books: S.Connection,
    api: TestClient,
) -> None:
    """The pages' three endpoints: the period's statement date, the rows and totals, the
    drill-down under a line, a ledger's statement; a ledger outside access is 404."""
    _refresh(db, year_end_books, "integrated", YEAR_END, YEAR_END_DATES)
    period = {"date_from": "2026-04-01", "date_to": "2026-05-02"}
    tb = api.get("/api/v1/reports/trial-balance", params=period).json()
    assert (tb["as_of"], tb["year_start"], tb["reason"]) == ("2026-05-02", "2026-04-01", None)
    assert Decimal(tb["total_debit"]) == Decimal(tb["total_credit"]) == Decimal(175680)
    sales = next(r for r in tb["rows"] if r["label"] == "Sales Accounts")
    assert (Decimal(sales["debit"]), Decimal(sales["credit"])) == (0, 12000)
    ledger_row = next(
        r for r in tb["rows"] if r["kind"] == "ledger" and r["parent"] == sales["key"]
    )
    found = api.get("/api/v1/reports/balance-sheet/drill",
                    params={**period, "line": "assets:current assets"}).json()  # fmt: skip
    assert found["as_of"] == "2026-05-02" and found["rows"][0]["depth"] == 0
    assert any(r["kind"] == "stock" for r in found["rows"])
    statement = api.get(f"/api/v1/ledgers/{ledger_row['ledger_id']}/statement", params=period)
    body = statement.json()
    assert Decimal(body["opening"]) == 0  # an income ledger starts the year at nil
    assert Decimal(body["closing"]) == Decimal(ledger_row["debit"]) - Decimal(ledger_row["credit"])
    listed = api.get("/api/v1/ledgers", params={"q": ledger_row["label"][:4]}).json()
    assert any(x["ledger_id"] == ledger_row["ledger_id"] for x in listed)
    assert api.get("/api/v1/ledgers/999999/statement", params=period).status_code == 404


@pytest.mark.parametrize("as_of", [date(2026, 5, 2), date(2026, 8, 31), AS_OF])
def test_each_ledger_opens_and_closes_as_in_tally_for_the_year(
    db: Session,
    year_end_books: S.Connection,
    as_of: date,
) -> None:
    """After the year end: every ledger's statement for the financial year to the date ends
    at Tally's closing for that period; an income or expense ledger starts the year at nil
    (Tally carries earlier years to Profit & Loss A/c)."""
    _refresh(db, year_end_books, "integrated", YEAR_END, YEAR_END_DATES)
    tally = _tally_ledgers("integrated", (date(2026, 4, 1), as_of))
    period = Period(date(2026, 4, 1), as_of)
    checked = 0
    for ledger in db.scalars(select(A.Ledger).where(A.Ledger.carries_profit.is_(False))):
        key = match_key(ledger.name)
        if key not in tally or ledger.ledger_kind == "stock":
            continue
        found = ledger_statement(db, ledger.id, period)
        assert found is not None
        if found.nature in ("income", "expense"):
            assert found.opening == 0, ledger.name
        assert found.closing == tally[key], ledger.name
        checked += 1
    assert checked > 15
