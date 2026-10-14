"""Pilot 2026-10-13: transform retry, safe failure breakdowns, one way to name companies,
root causes in validation, values that don't fit their column, and the flexible accounting
layer (extra, field catalogue, promoted fields). ADR-025."""

import re
from datetime import date, timedelta
from decimal import Decimal

import pymysql
import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import DataError
from sqlalchemy.orm import Session

from connectors.tally.connector import TallyConnector
from core import transform as T  # noqa: N812
from core.errors import short_error
from core.fit import PLACEHOLDER, UNFIT, UnfitValueError, fitter
from core.models import accounting as A  # noqa: N812
from core.models import system as S  # noqa: N812
from core.models.source import RawRecord
from tests.sim_tally import BAD_VOUCHER, LONG, SimTally
from workers import cli
from workers.extract import get_or_create_connection
from workers.failures import failure_breakdown, normalise
from workers.fields import PromoteError, promote_field
from workers.sync import run_sync, run_transform


@pytest.fixture
def sim(db: Session, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    monkeypatch.setattr(
        "connectors.registry.default_config", lambda code: {"url": "http://tally.test:9000"}
    )
    connection = get_or_create_connection(db, "tally-sim", "tally")
    connection.config = {**connection.config, "timeout_sec": 120}
    db.commit()

    def connector(transport: SimTally) -> TallyConnector:
        return TallyConnector.from_config(
            {"url": "http://tally.test:9000", "timeout_sec": 120}, transport=transport
        )

    return connection, connector


def _sync(db: Session, connection, connector, transport: SimTally):  # noqa: ANN001, ANN202
    lines: list[str] = []
    result = run_sync(
        db, connection, connector(transport), full=True, progress=lines.append, sleep=lambda s: None
    )
    return result, lines


def _count(db: Session, model: type, *where: object) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*where)) or 0


# --- 6: fitting values to columns -----------------------------------------------------------


def test_too_long_text_is_kept_in_full_never_truncated() -> None:
    fitted = fitter(A.Voucher).fit({"voucher_number": "N" * LONG, "reference_number": "R" * LONG})
    assert fitted.row["voucher_number"] == PLACEHOLDER  # required: a placeholder
    assert fitted.row["reference_number"] is None  # optional: empty
    assert fitted.unfit == {"voucher_number": "N" * LONG, "reference_number": "R" * LONG}
    assert fitted.warnings == [
        f"too long (length {LONG}, column allows 255): vouchers.voucher_number",
        f"too long (length {LONG}, column allows 255): vouchers.reference_number",
    ]


def test_numbers_dates_and_characters_that_dont_fit() -> None:
    party = fitter(A.Party).fit({"credit_days": 10**12, "credit_limit": Decimal("1e17")})
    assert party.row == {"credit_days": None, "credit_limit": None}
    assert party.unfit == {"credit_days": 10**12, "credit_limit": "1E+17"}
    assert all("out of range" in w for w in party.warnings)
    voucher = fitter(A.Voucher).fit(
        {"reference_date": date(1, 1, 1), "narration": "a" + chr(0xD800) + "b"}
    )
    assert voucher.row["reference_date"] is None
    assert voucher.row["narration"] == "a" + chr(0xFFFD) + "b"
    assert "invalid date (year 1)" in voucher.warnings[0]
    assert "invalid characters" in voucher.warnings[1]
    line = fitter(A.InventoryLine).fit({"rate": Decimal("1.1234567")})
    assert line.row["rate"] == Decimal("1.123457")  # rounded; the full value is in extra
    assert line.unfit == {"rate": "1.1234567"}
    # A required amount, quantity or date that can't be stored fails its own record.
    for row in ({"amount": Decimal("1e17")}, {"quantity": Decimal("1e15")}):
        with pytest.raises(UnfitValueError, match="out of range"):
            fitter(A.InventoryLine).fit(row)
    with pytest.raises(UnfitValueError, match="invalid date"):
        fitter(A.Voucher).fit({"voucher_date": date(1, 1, 1)})


def test_mysql_data_errors_are_described_without_values() -> None:
    error = DataError(
        "INSERT INTO ledgerbridge_accounting.parties (name, phone) VALUES (%s, %s)",
        [{"name": "Secret Party", "phone": "9" * 300}],
        pymysql.err.DataError(1406, "Data too long for column 'phone' at row 1"),
    )
    text = short_error(error)
    assert text == "DataError: MySQL 1406 too long: parties.phone (values up to 300 characters)"
    assert "Secret" not in text and "999" not in text
    ranged = DataError(
        "UPDATE ledgerbridge_accounting.vouchers SET x=%s",
        {"exchange_rate": Decimal("123456789012345.5")},
        pymysql.err.DataError(1264, "Out of range value for column 'exchange_rate' at row 1"),
    )
    assert short_error(ranged) == (
        "DataError: MySQL 1264 out of range: vouchers.exchange_rate "
        "(values up to 15 digits before the decimal point)"
    )
    dated = DataError(
        "INSERT INTO vouchers (reference_date) VALUES (%s)",
        {},
        pymysql.err.DataError(
            1292, "Incorrect date value: '0001-01-01' for column 'reference_date'"
        ),
    )
    assert (
        short_error(dated) == "DataError: MySQL 1292 invalid date or value: vouchers.reference_date"
    )


def test_sync_with_bad_values_keeps_everything_and_fails_only_the_bad_voucher(
    db: Session, sim
) -> None:  # noqa: ANN001
    connection, connector = sim
    transport = SimTally(per_day=2, udf=True, bad_values=True)
    result, lines = _sync(db, connection, connector, transport)
    assert result.status == "succeeded", result.error
    # Only the voucher whose amounts can't be stored failed, alone.
    assert result.failed == 1 and result.failed_by_object_type == {"voucher": 1}
    failed = db.scalars(select(RawRecord).where(RawRecord.process_status == "failed")).one()
    assert failed.source_key == f"sim0-{BAD_VOUCHER:%Y%m%d}-0000"
    assert failed.process_error.startswith("UnfitValueError: out of range")
    assert "voucher_lines.amount" in failed.process_error and "999" not in failed.process_error
    assert _count(db, A.Voucher) == transport.total_vouchers - 1
    # Over-long values: placeholder or empty, the full value in extra, a warning per record.
    voucher = db.scalar(select(A.Voucher).where(A.Voucher.source_key == "sim0-20260501-0000"))
    assert voucher.voucher_number == PLACEHOLDER and voucher.reference_number is None
    assert voucher.reference_date is None
    assert voucher.extra[UNFIT]["voucher_number"] == "N" * LONG
    assert voucher.extra[UNFIT]["reference_number"] == "R" * LONG
    assert voucher.extra[UNFIT]["reference_date"] == "0001-01-01"
    assert voucher.extra["UDF:REFNO.LIST/UDF:REFNO"] == "R0"  # custom field, per record
    rated = db.scalar(select(A.Voucher).where(A.Voucher.source_key == "sim0-20260502-0000"))
    assert rated.extra[UNFIT]["inventory_lines[1].rate"] == "1" * 20
    ledger = db.scalar(select(A.Ledger).where(A.Ledger.name == "Rent"))
    assert ledger.gstin is None and ledger.extra[UNFIT]["gstin"] == "G" * 40
    warned = db.scalar(
        select(RawRecord.process_warning).where(RawRecord.source_key == "sim0-20260501-0000")
    )
    assert "too long" in warned and "N" * 10 not in warned
    assert result.data_warnings  # counted for the output


def test_one_bad_record_in_a_batch_leaves_the_rest_converted(
    db: Session, sim, monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: ANN001
    """A batch the database rejects is written record by record: only the record at fault
    fails (here a database error the fitting can't foresee)."""
    connection, connector = sim
    original = T._Upserter.__call__  # noqa: SLF001
    bad = "sim0-20260410-0001"

    def upsert(self, model, rows, catalogue_as=None):  # noqa: ANN001, ANN202
        if model is A.Voucher and any(row["source_key"] == bad for row in rows):
            raise DataError(
                "INSERT INTO ledgerbridge_accounting.vouchers (narration) VALUES (%s)",
                [{"narration": "x" * 70_000}],
                pymysql.err.DataError(1406, "Data too long for column 'narration' at row 1"),
            )
        return original(self, model, rows, catalogue_as)

    monkeypatch.setattr(T._Upserter, "__call__", upsert)  # noqa: SLF001
    transport = SimTally(per_day=3)
    result, _ = _sync(db, connection, connector, transport)
    assert result.status == "succeeded"
    assert result.failed == 1
    assert _count(db, A.Voucher) == transport.total_vouchers - 1
    error = db.scalar(select(RawRecord.process_error).where(RawRecord.source_key == bad))
    assert error == (
        "DataError: MySQL 1406 too long: vouchers.narration (values up to 70000 characters)"
    )


# --- 1: transform retry -----------------------------------------------------------------------


def test_transform_retry_converts_failed_records_without_contacting_the_source(
    db: Session, sim, monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: ANN001
    connection, connector = sim
    transport = SimTally(per_day=2)
    original = T.Transformer._vouchers  # noqa: SLF001

    def broken(self, items, result):  # noqa: ANN001, ANN202
        raise RuntimeError("old code")

    monkeypatch.setattr(T.Transformer, "_vouchers", broken)
    result, _ = _sync(db, connection, connector, transport)
    assert result.failed == transport.total_vouchers
    monkeypatch.setattr(T.Transformer, "_vouchers", original)

    requests = len(transport.requests)
    lines: list[str] = []
    retried = run_transform(db, connection, connector(transport), progress=lines.append)
    assert len(transport.requests) == requests  # the source wasn't contacted
    assert retried.status == "succeeded" and retried.run_type == "transform"
    assert retried.retried == transport.total_vouchers and retried.failed == 0
    assert _count(db, A.Voucher) == transport.total_vouchers
    assert _count(db, RawRecord, RawRecord.process_status != "processed") == 0
    assert any("transforming voucher: " in line for line in lines)
    assert any(
        line.startswith("entity 1 (company 1): ") and "failed records retried" in line
        for line in lines
    )
    run = db.scalar(select(S.SyncRun).order_by(S.SyncRun.id.desc()))
    assert (run.run_type, run.status) == ("transform", "succeeded")


def test_transform_progress_in_batches(db: Session, sim, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    connection, connector = sim
    monkeypatch.setattr(T, "PROGRESS_EVERY", 100)
    monkeypatch.setattr(T, "BATCH", 50)
    result, lines = _sync(db, connection, connector, SimTally(per_day=2))
    assert result.status == "succeeded"
    progress = [line for line in lines if "transforming voucher: " in line and " of " in line]
    assert progress and progress[0].endswith("(0 failed)")


# --- 2, 3, 4: output ------------------------------------------------------------------------


@pytest.fixture
def run_cli(engine: Engine, monkeypatch: pytest.MonkeyPatch, capsys):  # noqa: ANN001, ANN201
    transport = SimTally(per_day=1, udf=True, bad_values=True)
    connector = TallyConnector.from_config(
        {"url": "http://tally.test:9000", "timeout_sec": 120}, transport=transport
    )
    monkeypatch.setattr(cli, "get_engine", lambda: engine)
    monkeypatch.setattr(cli, "_terminate_raises_system_exit", lambda: None)
    monkeypatch.setattr(cli, "connector_for", lambda session, connection: connector)
    monkeypatch.setattr(cli.registry, "create_connector", lambda code, config: connector)
    monkeypatch.setattr(
        "connectors.registry.default_config", lambda code: {"url": "http://tally.test:9000"}
    )

    def run(*argv: str, env: str = "pilot") -> tuple[int, str]:
        from core.config import Settings

        settings = Settings(app_env=env, ai_provider="ollama")
        monkeypatch.setattr(cli, "get_settings", lambda: settings)
        code = cli.main(list(argv))
        captured = capsys.readouterr()
        return code, captured.out + captured.err

    run.transport = transport  # type: ignore[attr-defined]
    return run


def test_pilot_output_names_companies_one_way_and_breaks_failures_down(
    db: Session, run_cli
) -> None:  # noqa: ANN001
    run_cli("connect", "--connection", "tally-pilot", "--source", "tally", "--origin", "backup",
            "--all")  # fmt: skip
    code, out = run_cli("sync", "--connection", "tally-pilot", "--full", "--no-validate")
    assert "1 companies in this run: company 1 (no entity yet)" in out
    assert "company 1 (no entity yet) is now entity 1 (company 1)" in out
    assert "entity 1 (company 1): SUCCEEDED" in out
    assert "failed by type: {'voucher': 1}" in out
    assert "converted with a note: Values kept aside (didn't fit their column) " in out
    assert "Overall: FAILED" in out  # a record failed to convert

    code, out = run_cli("summary")
    assert code == 0
    assert "  entity 1 (company 1):" in out
    assert "why records failed to convert [LB-TRF-001] (object type, count, error):" in out
    assert "voucher x1: UnfitValueError: out of range: voucher_lines.amount" in out
    assert (
        "Values kept aside (didn't fit their column) [values_kept_in_extra, LB-TRF-003] "
        "(object type, count, note; no values):"
    ) in out
    assert "voucher x6: too long: vouchers.voucher_number (length 300, column allows 255)" in out
    assert "fields with no column, kept in extra:" in out and "UDF " in out
    for secret in ("Sim Co", "N" * 20, "G" * 20, "999999", "UDF:REFNO"):
        assert secret not in out, secret

    code, out = run_cli("fields")
    assert "prefix UDF" in out and "UDF:REFNO" not in out  # names in test only
    code, out = run_cli("fields", env="test")
    assert "UDF:REFNO.LIST/UDF:REFNO" in out

    code, out = run_cli("status")
    assert "Validation of entity 1 (company 1): NOT VALIDATED yet" in out

    # The health report: the same names and codes, no names or values in any environment.
    for argv in (("report",), ("report", "--details"), ("report", "--format", "markdown")):
        code, out = run_cli(*argv)
        assert code == 1  # a record failed to convert
        assert "Overall: FAILED" in out or "**Overall: FAILED**" in out
        assert "Records that failed to convert [records_failed, LB-TRF-001]" in out
        assert "Not validated yet [never_validated, LB-VAL-019]" in out
        assert r".\dev.ps1 transform explain -Env pilot" in out
        for secret in ("Sim Co", "N" * 20, "G" * 20, "999999", "UDF:REFNO"):
            assert secret not in out, (argv, secret)


def test_transform_retry_command(db: Session, run_cli, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    run_cli("connect", "--connection", "tally-pilot", "--source", "tally", "--origin", "backup",
            "--all")  # fmt: skip
    run_cli("sync", "--connection", "tally-pilot", "--full", "--no-validate")
    requests = len(run_cli.transport.requests)
    code, out = run_cli("transform-retry", "--connection", "tally-pilot", "--no-validate")
    assert len(run_cli.transport.requests) == requests
    assert "1 companies to transform: entity 1 (company 1)" in out
    assert "entity 1 (company 1): 1 failed records retried; transformed 0, 1 failed" in out
    assert "Result: transform succeeded; validation skipped" in out
    code, out = run_cli("transform-retry", "--connection", "tally-pilot", "--entity", "Nobody")
    assert code == 2 and "aren't known" in out


def test_validation_names_the_root_cause(db: Session, run_cli) -> None:  # noqa: ANN001
    run_cli("connect", "--connection", "tally-pilot", "--source", "tally", "--origin", "backup",
            "--all")  # fmt: skip
    run_cli("sync", "--connection", "tally-pilot", "--full", "--no-validate")
    # A ledger record that failed: its ledger is missing, vouchers posting to it fail.
    rent = db.scalar(select(A.Ledger).where(A.Ledger.name == "Rent"))
    db.execute(
        RawRecord.__table__.update()
        .where(RawRecord.source_key == rent.source_key)
        .values(process_status="failed", process_error="DataError: MySQL 1406 too long: x")
    )
    db.execute(
        RawRecord.__table__.update()
        .where(RawRecord.object_type == "voucher", RawRecord.process_status == "processed")
        .values(
            process_status="failed",
            process_error="TransformError: voucher refers to an unknown ledger",
        )
    )
    for model in (A.LineDimension, A.BillAllocation, A.LineCostAllocation, A.TaxLine,
                  A.InventoryLine, A.VoucherLine, A.Voucher):  # fmt: skip
        db.execute(model.__table__.delete())
    db.execute(A.Ledger.__table__.delete().where(A.Ledger.id == rent.id))
    db.commit()
    code, out = run_cli("validate", "--connection", "tally-pilot")
    assert "Validation of entity 1 (company 1) as of" in out
    assert "ROOT CAUSE: 1 ledgers in the source are missing here (1 ledger records failed" in out
    assert "vouchers failed to transform because they refer to a ledger that is missing" in out
    assert "are likely consequences: fix the records that failed to transform first" in out


# --- 7: extra, catalogue, promotion ------------------------------------------------------------


def test_field_catalogue_counts_records_once(db: Session, sim) -> None:  # noqa: ANN001
    connection, connector = sim
    transport = SimTally(per_day=1, udf=True)
    _sync(db, connection, connector, transport)
    field = db.scalar(
        select(A.SourceField).where(A.SourceField.field_path == "UDF:REFNO.LIST/UDF:REFNO")
    )
    assert (field.object_type, field.prefix, field.inferred_type) == ("voucher", "UDF", "text")
    assert field.record_count == transport.total_vouchers
    flag = db.scalar(
        select(A.SourceField).where(A.SourceField.field_path == "TDL:FLAG.LIST/TDL:FLAG")
    )
    assert flag.inferred_type == "flag"
    ledger_udf = db.scalar(
        select(A.SourceField).where(
            A.SourceField.object_type == "ledger",
            A.SourceField.field_path == "UDF:CUSTOMCODE.LIST/UDF:CUSTOMCODE",
        )
    )
    assert ledger_udf.record_count == _count(db, A.Ledger, A.Ledger.name != "Primary") - 0
    # A second full sync re-transforms everything: counts stay the number of records.
    _sync(db, connection, connector, transport)
    db.refresh(field)
    assert field.record_count == transport.total_vouchers
    company = db.scalar(select(A.Entity))
    assert "CURRENCYNAME" in company.extra  # fields the mapping doesn't use, on the entity too


def test_promote_a_custom_field_to_a_dimension(db: Session, sim) -> None:  # noqa: ANN001
    connection, connector = sim
    transport = SimTally(per_day=1, udf=True)
    _sync(db, connection, connector, transport)
    field = db.scalar(
        select(A.SourceField).where(A.SourceField.field_path == "UDF:REFNO.LIST/UDF:REFNO")
    )
    promoted = promote_field(db, field.id, "REFNO", "Reference no")
    lines = _count(db, A.VoucherLine)
    assert promoted.vouchers == transport.total_vouchers
    assert promoted.values == 1  # every simulated voucher has R0
    assert promoted.lines == lines == _count(db, A.LineDimension)
    dimension = db.scalar(select(A.Dimension).where(A.Dimension.code == "REFNO"))
    assert (dimension.source_object_type, dimension.source_field) == (
        "voucher",
        "UDF:REFNO.LIST/UDF:REFNO",
    )
    # The transform keeps it up to date: vouchers written again keep their dimension.
    _sync(db, connection, connector, transport)
    assert _count(db, A.LineDimension) == _count(db, A.VoucherLine) == lines
    # Running it again starts over from extra; masters can't be promoted yet.
    assert promote_field(db, field.id, "REFNO", "Reference no").lines == lines
    ledger_field = db.scalar(select(A.SourceField).where(A.SourceField.object_type == "ledger"))
    with pytest.raises(PromoteError, match="only fields of voucher records"):
        promote_field(db, ledger_field.id, "X", "X")


def test_failure_breakdown_groups_sizes(db: Session, sim) -> None:  # noqa: ANN001
    connection, _ = sim
    assert normalise(
        "DataError: MySQL 1406 too long: parties.phone (values up to 40 characters)"
    ) == (
        "DataError: MySQL 1406 too long: parties.phone",
        ["values up to 40 characters"],
    )
    assert normalise("KeyError: 'Secret Ledger'")[0] == "KeyError: '…'"
    now = date.today()
    for size in (40, 300):
        db.add(
            RawRecord(
                connection_id=connection.id, source_entity_key="k", object_type="ledger",
                source_key=f"l{size}", payload_format="xml", payload="<x/>", payload_hash="h" * 64,
                received_at=now, process_status="failed",
                process_error="DataError: MySQL 1406 too long: parties.phone "
                f"(values up to {size} characters)",
            )
        )  # fmt: skip
    db.commit()
    (group,) = failure_breakdown(db, connection.id)
    assert (group.object_type, group.count, group.largest) == (
        "ledger",
        2,
        "values up to 300 characters",
    )


# --- 5: validation against the source's controls -----------------------------------------------


def test_thorough_validation_passes_on_the_test_company(
    db: Session, engine: Engine, monkeypatch, capsys
) -> None:  # noqa: ANN001
    from connectors.tally.fixtures import FixtureTransport

    connector = TallyConnector.from_config(
        {"url": "http://tally.test:9000"}, transport=FixtureTransport()
    )
    monkeypatch.setattr(cli, "get_engine", lambda: engine)
    monkeypatch.setattr(cli, "_terminate_raises_system_exit", lambda: None)
    monkeypatch.setattr(cli, "connector_for", lambda session, connection: connector)
    monkeypatch.setattr(cli.registry, "create_connector", lambda code, config: connector)
    monkeypatch.setattr(
        "connectors.registry.default_config", lambda code: {"url": "http://tally.test:9000"}
    )
    assert cli.main(["sync", "--connection", "tally-test", "--source", "tally", "--full"]) == 0
    out = capsys.readouterr().out
    assert "(thorough: counts, stock, bills, year ends)" in out
    assert "PASSED" in out
    issues = {i.check_code for i in db.scalars(select(S.ValidationIssue))}
    assert "stock_values_not_compared" in issues  # a note, not a failure
    assert not issues & {"voucher_count_mismatch", "stock_quantity_mismatch", "bills_mismatch"}


def _validator(db: Session, sim, as_of: date):  # noqa: ANN001, ANN202
    from core.validation import Validator

    connection, connector = sim
    _sync(db, connection, connector, SimTally(per_day=1))
    entity = db.scalar(select(A.Entity))
    return Validator(db, entity.id, as_of, Decimal(0), connection.id), entity


def test_voucher_counts_stock_and_bills_mismatches(db: Session, sim) -> None:  # noqa: ANN001
    from connectors.base import SourceControls

    validator, entity = _validator(db, sim, date.today())
    voucher_type = db.scalar(select(A.VoucherType.name).join(A.Voucher).limit(1))
    widget = db.scalar(select(A.Item))
    counts = {(date(2026, 4, 1), voucher_type): 30, (date(2026, 5, 1), voucher_type): 30}
    report = validator.run(
        None,
        controls=SourceControls(
            voucher_counts=counts,  # May has 31 here
            stock_quantities={widget.source_key: Decimal(5)},  # 0 here
            bill_outstanding={"Customer Alpha Traders": Decimal(100)},
            opening_bills={},
        ),
    )
    codes = report.failed_by_code
    assert codes["voucher_count_mismatch"] >= 1
    may = next(f for f in report.findings if f.object_id == f"2026-05:{_type_id(db)}")
    assert (may.expected, may.actual) == (Decimal(30), Decimal(31))
    assert codes["stock_quantity_mismatch"] == 1
    assert codes["bills_mismatch"] == 1


def _type_id(db: Session) -> int:
    return db.scalar(select(A.Voucher.voucher_type_id).limit(1))


def test_year_end_balances_and_unavailable_controls(db: Session, sim) -> None:  # noqa: ANN001
    from connectors.base import SourceBalances, SourceControls

    validator, entity = _validator(db, sim, date.today())
    year_end = date(2026, 6, 30)
    ledgers = dict(db.execute(select(A.Ledger.source_key, A.Ledger.opening_balance)).all())
    report = validator.run(
        None,
        controls=SourceControls(
            voucher_counts=TimeoutError("listing too slow"),
            year_ends={year_end: SourceBalances(year_end, {k: v + 1 for k, v in ledgers.items()})},
        ),
    )
    codes = report.failed_by_code
    assert codes["voucher_counts_unavailable"] == 1
    assert codes["year_end_mismatch"] >= 1
    finding = next(f for f in report.findings if f.check_code == "year_end_mismatch")
    assert finding.object_id.endswith("@2026-06-30")
    notes = {f.check_code for f in report.findings if f.severity == "info"}
    assert {"stock_quantities_not_supported", "bill_outstanding_not_supported"} <= notes


def test_bills_compared_only_as_of_today(db: Session, sim) -> None:  # noqa: ANN001
    from connectors.base import SourceControls

    validator, _ = _validator(db, sim, date.today() - timedelta(days=30))
    report = validator.run(None, controls=SourceControls(bill_outstanding={}, opening_bills={}))
    assert any(f.check_code == "bills_not_compared" for f in report.findings)


# --- transform rebuild -----------------------------------------------------------------------


def test_rebuild_transforms_every_record_again_without_the_source(
    db: Session, sim, monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: ANN001
    connection, connector = sim
    transport = SimTally(per_day=1, udf=True)
    # "Old code": no extra fields were kept.
    monkeypatch.setattr("connectors.tally.mapping.unmapped_fields", lambda element, kind: None)
    _sync(db, connection, connector, transport)
    monkeypatch.undo()
    assert db.scalar(select(A.Voucher.extra).limit(1)) is None
    assert _count(db, A.SourceField) == 0
    vouchers, lines = _count(db, A.Voucher), _count(db, A.VoucherLine)

    requests = len(transport.requests)
    out: list[str] = []
    result = run_transform(db, connection, connector(transport), progress=out.append, rebuild=True)
    assert len(transport.requests) == requests  # the source wasn't contacted
    assert result.status == "succeeded" and result.failed == 0
    raw = _count(db, RawRecord)
    assert result.retried == raw  # every object, from its latest (here only) raw record
    assert any("records rebuilt; transformed" in line for line in out)
    # Idempotent: same rows, children replaced, extra and catalogue filled.
    assert (_count(db, A.Voucher), _count(db, A.VoucherLine)) == (vouchers, lines)
    db.expire_all()
    assert db.scalar(select(A.Voucher.extra).limit(1))["UDF:REFNO.LIST/UDF:REFNO"] == "R0"
    field = db.scalar(
        select(A.SourceField).where(A.SourceField.field_path == "UDF:REFNO.LIST/UDF:REFNO")
    )
    assert field.record_count == transport.total_vouchers
    # Twice is the same as once.
    run_transform(db, connection, connector(transport), rebuild=True)
    db.refresh(field)
    assert field.record_count == transport.total_vouchers
    assert (_count(db, A.Voucher), _count(db, A.VoucherLine)) == (vouchers, lines)


def _newer_version(db: Session, key: str, narration: str) -> RawRecord:
    """A second raw record of the same voucher (it changed in the source)."""
    old = db.scalar(select(RawRecord).where(RawRecord.source_key == key))
    payload = re.sub(r"(<NARRATION[^>]*>)[^<]*", r"\g<1>" + narration, old.payload)
    assert payload != old.payload
    new = RawRecord(
        connection_id=old.connection_id, source_entity_key=old.source_entity_key,
        object_type=old.object_type, source_key=key, source_alter_id=(old.source_alter_id or 0) + 1,
        payload_format="xml", payload=payload, payload_hash="n" * 64, received_at=old.received_at,
        process_status="pending",
    )  # fmt: skip
    db.add(new)
    db.commit()
    return new


def test_older_versions_never_overwrite_newer_ones(db: Session, sim) -> None:  # noqa: ANN001
    connection, connector = sim
    transport = SimTally(per_day=1)
    _sync(db, connection, connector, transport)
    key = "sim0-20260410-0000"
    newer = _newer_version(db, key, "changed")
    run_transform(db, connection, connector(transport), retry_failed=False)
    voucher = db.scalar(select(A.Voucher).where(A.Voucher.source_key == key))
    assert voucher.narration == "changed"
    # The older version had failed before: retrying must not apply it over the newer one.
    db.execute(
        RawRecord.__table__.update()
        .where(RawRecord.source_key == key, RawRecord.id != newer.id)
        .values(process_status="failed", process_error="TransformError: old")
    )
    db.commit()
    result = run_transform(db, connection, connector(transport))
    assert result.retried == 0
    statuses = dict(
        db.execute(
            select(RawRecord.id, RawRecord.process_status).where(RawRecord.source_key == key)
        ).all()
    )
    assert statuses[newer.id] == "processed"
    assert sorted(statuses.values()) == ["processed", "skipped"]
    run_transform(db, connection, connector(transport), rebuild=True)  # latest version only
    db.refresh(voucher)
    assert voucher.narration == "changed"


def test_rebuild_keeps_objects_deleted_in_the_source_deleted(db: Session, sim) -> None:  # noqa: ANN001
    from core.transform import mark_deleted

    connection, connector = sim
    transport = SimTally(per_day=1)
    _sync(db, connection, connector, transport)
    gone = "sim0-20260411-0000"
    entity_id = db.scalar(select(A.Entity.id))
    existing = {"voucher": set(db.scalars(select(A.Voucher.source_key))) - {gone}}
    mark_deleted(db, connection.id, entity_id, existing)
    run_transform(db, connection, connector(transport), rebuild=True)
    voucher = db.scalar(select(A.Voucher).where(A.Voucher.source_key == gone))
    db.refresh(voucher)
    assert voucher.is_deleted
    effective = db.scalars(
        select(A.VoucherLine.is_effective).where(A.VoucherLine.voucher_id == voucher.id)
    ).all()
    assert effective and not any(effective)


def test_transform_rebuild_command(db: Session, run_cli) -> None:  # noqa: ANN001
    run_cli("connect", "--connection", "tally-pilot", "--source", "tally", "--origin", "backup",
            "--all")  # fmt: skip
    run_cli("sync", "--connection", "tally-pilot", "--full", "--no-validate")
    requests = len(run_cli.transport.requests)
    code, out = run_cli("transform-rebuild", "--connection", "tally-pilot", "--no-validate")
    assert len(run_cli.transport.requests) == requests
    assert "entity 1 (company 1): transforming every stored record again" in out
    assert "records rebuilt; transformed" in out and ", 1 failed" in out  # the bad voucher
    assert "Result: rebuild succeeded; validation skipped" in out
    assert "Sim Co" not in out
