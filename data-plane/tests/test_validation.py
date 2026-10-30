"""M4: validation (VAL-001, VAL-002), alerts (SYN-006) and the validation API, on the
test company's recorded fixtures (SQLite stand-in)."""

from collections.abc import Iterator
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_session
from api.main import app
from connectors.tally.connector import TallyConnector
from core.models import accounting as A  # noqa: N812
from core.models import system as S  # noqa: N812
from core.validation import Validator, financial_year_ends
from tests.conftest import COMPANY
from workers.sync import SyncResult
from workers.validate import after_run, run_validation

TODAY = date.today()


def _ledger(db: Session, name: str) -> A.Ledger:
    return db.scalars(select(A.Ledger).where(A.Ledger.name == name)).one()


def _validate(db: Session, connection: S.Connection, connector: TallyConnector):  # noqa: ANN202
    (report,) = run_validation(db, connection, connector, [COMPANY])
    return report


def _codes(report) -> set[str]:  # noqa: ANN001
    return {f.check_code for f in report.findings}


def _open_alerts(db: Session, kind: str) -> list[S.Alert]:
    return list(
        db.scalars(select(S.Alert).where(S.Alert.kind == kind, S.Alert.resolved_at.is_(None)))
    )


# --- clean books ----------------------------------------------------------------------


def test_clean_books_pass_every_check(
    db: Session, synced: S.Connection, connector: TallyConnector
) -> None:
    report = _validate(db, synced, connector)
    assert report.status == "passed", report.findings
    assert report.findings == [] and report.checks_failed == 0
    # 18 vouchers with lines (the cancelled one has none) + opening + TB + 21 ledgers
    assert report.checks_passed == 17 + 1 + 1 + 21
    assert report.opening_difference == 0
    run = db.get(S.ValidationRun, report.validation_run_id)
    assert (run.status, run.as_of, run.entity_id) == ("passed", TODAY, report.entity_id)
    assert _open_alerts(db, "validation_failed") == []


def test_profit_carrier_is_reconciled_not_compared(
    db: Session, synced: S.Connection, connector: TallyConnector
) -> None:
    """Tally reports Profit & Loss A/c as 13,500 Dr (the period's loss), which no voucher
    posts: income 20,000, expenses 33,500, no change in stock value."""
    entity = connector.list_entities()[0]
    source = connector.closing_balances(entity, TODAY)
    carrier = _ledger(db, "Profit & Loss A/c")
    assert source.profit_carriers == {carrier.source_key}
    assert source.ledgers[carrier.source_key] == Decimal("13500")
    assert (source.opening_stock, source.closing_stock) == (0, 0)
    assert "profit_carrier_mismatch" not in _codes(_validate(db, synced, connector))


def test_balances_as_of_a_date_leave_out_later_vouchers(db: Session, synced: S.Connection) -> None:
    """Our balances as of 31 Aug equal what Tally itself reported for that date: Cash
    29,000, Bank 19,360, Electricity 3,000 (ALTER-1 on 1 Sep and ALTER-2 on 2 Sep excluded)."""
    entity_id = db.scalars(select(A.Entity)).one().id
    balances = {
        b.name: b.balance
        for b in Validator(db, entity_id, date(2026, 8, 31))._ledger_balances(date(2026, 8, 31))
    }
    assert balances["Cash"] == Decimal("29000")
    assert balances["Test Bank Current A/c"] == Decimal("19360")
    assert balances["Electricity"] == Decimal("3000")


def test_financial_year_ends_between_books_from_and_as_of() -> None:
    assert financial_year_ends(date(2024, 4, 1), 4, date(2026, 10, 12)) == [
        date(2025, 3, 31),
        date(2026, 3, 31),
    ]
    assert financial_year_ends(date(2026, 4, 1), 4, date(2026, 10, 12)) == []
    assert financial_year_ends(None, 4, date(2026, 10, 12)) == []


# --- each check fails when it should --------------------------------------------------


def test_unbalanced_voucher_fails_raises_alert_and_resolves(
    db: Session, synced: S.Connection, connector: TallyConnector
) -> None:
    rent = _ledger(db, "Rent")
    line = db.scalars(select(A.VoucherLine).where(A.VoucherLine.ledger_id == rent.id)).first()
    line.amount += Decimal("1")
    db.commit()

    first = _validate(db, synced, connector)
    assert first.status == "failed"
    assert {"voucher_unbalanced", "tb_unbalanced", "closing_mismatch"} <= _codes(first)
    (alert,) = _open_alerts(db, "validation_failed")
    assert "voucher_unbalanced 1" in alert.message and "1000" not in alert.message

    second = _validate(db, synced, connector)  # still failing: same alert, no new one
    assert second.status == "failed"
    assert [a.id for a in _open_alerts(db, "validation_failed")] == [alert.id]

    line.amount -= Decimal("1")
    db.commit()
    third = _validate(db, synced, connector)
    assert third.status == "passed"
    assert _open_alerts(db, "validation_failed") == []
    unresolved = db.scalars(
        select(S.ValidationIssue).where(S.ValidationIssue.resolved_at.is_(None))
    ).all()
    assert unresolved == []


def _source_difference(connector: TallyConnector, monkeypatch, amount: Decimal) -> None:  # noqa: ANN001
    """The source's own openings at the books' beginning don't total zero by `amount`."""
    read = connector.closing_balances

    def closing_balances(entity, as_of):  # noqa: ANN001, ANN202
        balances = read(entity, as_of)
        return replace(balances, opening_difference=(balances.opening_difference or 0) + amount)

    monkeypatch.setattr(connector, "closing_balances", closing_balances)


def test_opening_difference_warns_only_when_the_source_shows_one(
    db: Session, synced: S.Connection, connector: TallyConnector, monkeypatch
) -> None:  # noqa: ANN001
    """Pilot 2026-10-15: the warning compared our openings with zero. It now fires only
    when the source's own openings (ledgers and opening stock at the books' beginning)
    don't total zero."""
    report = _validate(db, synced, connector)
    assert "opening_difference" not in _codes(report)
    _source_difference(connector, monkeypatch, Decimal("250"))
    report = _validate(db, synced, connector)
    opening = next(f for f in report.findings if f.check_code == "opening_difference")
    assert (opening.severity, opening.actual) == ("warning", Decimal("250"))
    assert "The source shows a difference" in opening.message


def test_our_opening_differing_is_a_closing_mismatch_not_an_opening_warning(
    db: Session, synced: S.Connection, connector: TallyConnector
) -> None:
    cash = _ledger(db, "Cash")  # a balance-sheet ledger, so the profit is unchanged
    cash.opening_balance += Decimal("100")
    db.commit()
    report = _validate(db, synced, connector)
    assert "opening_difference" not in _codes(report)  # the source shows none
    assert report.opening_difference == Decimal("100")
    # The trial balance totals exactly the opening difference, so it passes; Cash itself
    # no longer matches Tally.
    assert "tb_unbalanced" not in _codes(report)
    assert [f.object_id for f in report.findings if f.check_code == "closing_mismatch"] == [
        str(cash.id)
    ]


def test_missing_ledgers_on_either_side(
    db: Session, synced: S.Connection, connector: TallyConnector, monkeypatch: pytest.MonkeyPatch
) -> None:
    salary = _ledger(db, "Salary")
    real = connector.closing_balances

    def extra_and_missing(entity, as_of):  # noqa: ANN001, ANN202
        source = real(entity, as_of)
        ledgers = {k: v for k, v in source.ledgers.items() if k != salary.source_key}
        return replace(source, ledgers={**ledgers, "guid-only-in-tally": Decimal("5")})

    monkeypatch.setattr(connector, "closing_balances", extra_and_missing)
    report = _validate(db, synced, connector)
    missing = {
        (f.object_type, f.object_id) for f in report.findings if f.check_code == "ledger_missing"
    }
    assert missing == {("ledger", str(salary.id)), ("source_ledger", "guid-only-in-tally")}


def test_profit_carrier_mismatch(
    db: Session, synced: S.Connection, connector: TallyConnector, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = connector.closing_balances

    def stock_changed(entity, as_of):  # noqa: ANN001, ANN202
        return replace(real(entity, as_of), closing_stock=Decimal("500"))

    monkeypatch.setattr(connector, "closing_balances", stock_changed)
    report = _validate(db, synced, connector)
    (finding,) = [f for f in report.findings if f.check_code == "profit_carrier_mismatch"]
    assert (finding.expected, finding.actual) == (Decimal("13500"), Decimal("13000"))


def test_unreadable_source_is_an_error_and_missing_support_is_a_note(
    db: Session, synced: S.Connection, connector: TallyConnector, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unreachable(entity, as_of):  # noqa: ANN001, ANN202
        raise ConnectionError("Tally is not running")

    monkeypatch.setattr(connector, "closing_balances", unreachable)
    report = _validate(db, synced, connector)
    assert report.status == "failed" and "closing_unavailable" in _codes(report)

    entity_id = db.scalars(select(A.Entity)).one().id
    without = Validator(db, entity_id, TODAY, connection_id=synced.id).run(None)
    assert without.status == "passed"
    assert [(f.check_code, f.severity) for f in without.findings] == [
        ("closing_not_supported", "info")
    ]


def test_tolerance_is_exact_by_default_and_configurable(
    db: Session, synced: S.Connection, connector: TallyConnector
) -> None:
    cash = _ledger(db, "Cash")
    cash.opening_balance += Decimal("0.01")
    _ledger(db, "Capital").opening_balance -= Decimal("0.01")  # openings still total zero
    db.commit()
    assert "closing_mismatch" in _codes(_validate(db, synced, connector))
    synced.config = {**synced.config, "validation_tolerance": "0.01"}
    db.commit()
    assert _validate(db, synced, connector).status == "passed"


# --- alerts for sync runs -------------------------------------------------------------


def test_failed_sync_raises_one_alert_until_a_run_succeeds(
    db: Session, synced: S.Connection, connector: TallyConnector
) -> None:
    failed = SyncResult(sync_run_id=1, status="failed", run_type="incremental")
    assert after_run(db, synced, connector, failed).reports == []
    after_run(db, synced, connector, failed)
    (alert,) = _open_alerts(db, "sync_failed")
    assert "1000" not in alert.message

    key = connector.list_entities()[0].key
    ok = SyncResult(sync_run_id=1, status="succeeded", run_type="incremental", entity_keys=[key])
    after = after_run(db, synced, connector, ok)
    assert after.validation_status == "passed"
    (report,) = after.reports
    assert report.status == "passed"
    assert _open_alerts(db, "sync_failed") == []
    assert db.get(S.Alert, alert.id).resolved_at is not None


def test_failed_deletion_check_has_its_own_alert(
    db: Session, synced: S.Connection, connector: TallyConnector
) -> None:
    failed = SyncResult(sync_run_id=1, status="failed", run_type="deletion_check")
    after_run(db, synced, connector, failed)
    assert len(_open_alerts(db, "deletion_check_failed")) == 1
    assert _open_alerts(db, "sync_failed") == []


# --- API ------------------------------------------------------------------------------


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_session] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_api_status_runs_and_alerts(
    db: Session, synced: S.Connection, connector: TallyConnector, client: TestClient, monkeypatch
) -> None:  # noqa: ANN001
    _ledger(db, "Cash").opening_balance += Decimal("100")
    db.commit()
    _source_difference(connector, monkeypatch, Decimal("100"))
    report = _validate(db, synced, connector)

    (status,) = client.get("/api/validation/status").json()
    assert status["entity_name"] == COMPANY
    assert Decimal(status["opening_difference"]) == Decimal("100")
    assert status["last_run"]["id"] == report.validation_run_id
    assert status["last_run"]["status"] == "failed"
    assert (status["open_errors"], status["open_warnings"], status["open_alerts"]) == (1, 1, 1)

    runs = client.get("/api/validation/runs", params={"entity_id": report.entity_id}).json()
    assert [r["id"] for r in runs] == [report.validation_run_id]
    detail = client.get(f"/api/validation/runs/{report.validation_run_id}").json()
    assert {i["check_code"] for i in detail["issues"]} == {"opening_difference", "closing_mismatch"}
    assert client.get("/api/validation/runs/999999").status_code == 404

    (alert,) = client.get("/api/alerts").json()
    assert alert["kind"] == "validation_failed" and alert["resolved_at"] is None


def test_api_has_no_write_endpoints_before_m5() -> None:
    """Unauthenticated until M5 (ADR-019), so only reads are exposed."""
    for route in app.routes:
        if getattr(route, "path", "").startswith("/api/"):
            assert route.methods <= {"GET", "HEAD"}, route.path


def test_api_binds_to_localhost_only() -> None:
    """The unauthenticated validation endpoints are acceptable only on 127.0.0.1 (ADR-019).
    Checks every published port in deploy/compose.yaml, the API's included."""
    compose = Path(__file__).resolve().parents[2] / "deploy" / "compose.yaml"
    published, in_ports = [], False
    for line in compose.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped == "ports:":
            in_ports = True
        elif in_ports and stripped.startswith("- "):
            published.append(stripped[2:].strip("\"'"))
        else:
            in_ports = False
    assert any(p.endswith(":8000") for p in published)
    assert all(p.startswith("127.0.0.1:") for p in published), published


def test_a_check_that_didnt_run_leaves_its_earlier_issues_open(
    db: Session, synced: S.Connection, connector: TallyConnector
) -> None:
    """A quick validation (no source controls) doesn't compare voucher counts: a voucher
    count mismatch found before stays open (quick runs used to mark it resolved), until a
    thorough validation compares the counts again and no longer finds it."""
    from connectors.base import SourceControls

    as_of = date(2026, 10, 2)
    entity_id = db.scalars(select(A.Entity)).one().id
    entity = connector.list_entities()[0]
    source = connector.closing_balances(entity, as_of)
    tallys = connector.voucher_counts(entity, entity.books_from, as_of)
    wrong = dict(tallys)
    first = sorted(wrong)[0]
    wrong[first] += 1

    def validate(controls: SourceControls | None) -> None:
        Validator(db, entity_id, as_of, connection_id=synced.id).run(source, controls=controls)

    def open_count_issues() -> int:
        found = db.scalars(
            select(S.ValidationIssue).where(
                S.ValidationIssue.check_code == "voucher_count_mismatch",
                S.ValidationIssue.resolved_at.is_(None),
            )
        )
        return len(found.all())

    validate(SourceControls(voucher_counts=wrong))
    assert open_count_issues() == 1
    validate(None)  # quick: counts not compared
    assert open_count_issues() == 1
    validate(SourceControls(voucher_counts=RuntimeError("unreadable")))  # not compared either
    assert open_count_issues() == 1
    validate(SourceControls(voucher_counts=tallys))  # compared, and they match
    assert open_count_issues() == 0


def test_a_count_finding_names_the_live_voucher_type(
    db: Session, synced: S.Connection, connector: TallyConnector
) -> None:
    """A voucher type deleted and created again keeps its name: a voucher count mismatch
    names the live type (it could name the deleted one)."""
    from connectors.base import SourceControls

    as_of = date(2026, 10, 2)
    sales = db.scalars(select(A.VoucherType).where(A.VoucherType.name == "Sales")).one()
    copy = {
        c.name: getattr(sales, c.key)
        for c in A.VoucherType.__table__.columns
        if c.name not in ("id",)
    }
    db.add(A.VoucherType(**{**copy, "source_key": "deleted-sales", "is_deleted": True}))
    db.commit()
    entity = connector.list_entities()[0]
    counts = dict(connector.voucher_counts(entity, entity.books_from, as_of))
    month = next(key for key in sorted(counts) if key[1] == "Sales")
    counts[month] += 1
    report = Validator(db, sales.entity_id, as_of, connection_id=synced.id).run(
        connector.closing_balances(entity, as_of), controls=SourceControls(voucher_counts=counts)
    )
    (finding,) = [f for f in report.findings if f.check_code == "voucher_count_mismatch"]
    assert finding.object_id == f"{month[0]:%Y-%m}:{sales.id}"


def test_a_voucher_type_name_written_differently_in_the_counts_still_matches(
    db: Session, synced: S.Connection, connector: TallyConnector
) -> None:
    """Pilot 2026-10-30: a type named with two spaces in a row was written with one in the
    source's voucher counts, so every voucher of the type was counted as another's. The
    counts are matched by the transform's name rules, and the difference noted (kinds only)."""
    from connectors.base import SourceControls

    as_of = date(2026, 10, 2)
    sales = db.scalars(select(A.VoucherType).where(A.VoucherType.name == "Sales")).one()
    sales.name = "Sales  Invoice"
    db.commit()
    entity = connector.list_entities()[0]
    counts = {
        (month, "Sales Invoice" if kind == "Sales" else kind): n
        for (month, kind), n in connector.voucher_counts(entity, entity.books_from, as_of).items()
    }
    report = Validator(db, sales.entity_id, as_of, connection_id=synced.id).run(
        connector.closing_balances(entity, as_of), controls=SourceControls(voucher_counts=counts)
    )
    codes = [f.check_code for f in report.findings]
    assert "voucher_count_mismatch" not in codes
    (note,) = [f for f in report.findings if f.check_code == "voucher_type_names_differ"]
    assert note.severity == "info"
    assert "1 compared with the type each matches" in note.message
    assert "double or unusual spaces 1" in note.message
    assert "Sales" not in note.message


def test_a_voucher_type_name_the_rules_dont_match_is_still_a_mismatch(
    db: Session, synced: S.Connection, connector: TallyConnector
) -> None:
    """A name that differs by more than spaces or capitals isn't matched: its counts differ,
    and the note says how it differs from the closest of ours (kinds only)."""
    from connectors.base import SourceControls

    as_of = date(2026, 10, 2)
    entity_id = db.scalars(select(A.Entity)).one().id
    entity = connector.list_entities()[0]
    counts = {
        (month, "Sales 2" if kind == "Sales" else kind): n
        for (month, kind), n in connector.voucher_counts(entity, entity.books_from, as_of).items()
    }
    report = Validator(db, entity_id, as_of, connection_id=synced.id).run(
        connector.closing_balances(entity, as_of), controls=SourceControls(voucher_counts=counts)
    )
    assert "voucher_count_mismatch" in [f.check_code for f in report.findings]
    (note,) = [f for f in report.findings if f.check_code == "voucher_type_names_differ"]
    assert "1 not matched: close to one of ours but differing by more (other 1)" in note.message
    assert "Sales" not in note.message
