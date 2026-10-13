"""Values that don't fit their column, on MySQL (ADR-025; ./dev.ps1 up): kept in full in
`extra`, and a value MySQL rejects fails only its own record, with a safe description."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from connectors.tally.connector import TallyConnector
from core import transform as T  # noqa: N812
from core.db import get_engine
from core.fit import UNFIT, Fitted
from core.models import accounting as A  # noqa: N812
from core.models.source import RawRecord
from tests.sim_tally import LONG, SimTally
from tests.test_sync_integration import CONNECTION, _cleanup
from workers.extract import get_or_create_connection
from workers.sync import run_sync

pytestmark = pytest.mark.integration


def _sync(session: Session, monkeypatch: pytest.MonkeyPatch, transport: SimTally):  # noqa: ANN202
    monkeypatch.setattr(
        "connectors.registry.default_config", lambda code: {"url": "http://tally.test:9000"}
    )
    connection = get_or_create_connection(session, CONNECTION, "tally")
    connection.config = {**connection.config, "timeout_sec": 120}
    session.commit()
    connector = TallyConnector.from_config(
        {"url": "http://tally.test:9000", "timeout_sec": 120}, transport=transport
    )
    return run_sync(session, connection, connector, full=True, sleep=lambda s: None), connection


def test_values_that_dont_fit_are_kept_in_extra_on_mysql(monkeypatch: pytest.MonkeyPatch) -> None:
    with Session(get_engine()) as session:
        _cleanup(session)
        try:
            transport = SimTally(per_day=1, udf=True, bad_values=True)
            result, connection = _sync(session, monkeypatch, transport)
            assert result.status == "succeeded", result.error
            assert result.failed == 1  # only the voucher whose amounts can't be stored
            voucher = session.scalar(
                select(A.Voucher).where(
                    A.Voucher.connection_id == connection.id,
                    A.Voucher.source_key == "sim0-20260501-0000",
                )
            )
            assert voucher.extra[UNFIT]["voucher_number"] == "N" * LONG
            assert voucher.extra["UDF:REFNO.LIST/UDF:REFNO"] == "R0"
            fields = session.scalar(select(func.count()).select_from(A.SourceField))
            assert fields
        finally:
            _cleanup(session)


def test_a_value_mysql_rejects_fails_only_its_record(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without the fitting, MySQL itself rejects the over-long voucher numbers: the batch is
    written again record by record and only those vouchers fail, with code, table, column
    and length, never the value."""
    real = T.fitter

    class PassThrough:
        def fit(self, row: dict) -> Fitted:
            return Fitted(dict(row))

    monkeypatch.setattr(
        T, "fitter", lambda model: PassThrough() if model is A.Voucher else real(model)
    )
    with Session(get_engine()) as session:
        _cleanup(session)
        try:
            transport = SimTally(per_day=1, bad_values=True)
            result, connection = _sync(session, monkeypatch, transport)
            assert result.status == "succeeded", result.error
            failed = session.scalars(
                select(RawRecord.process_error).where(
                    RawRecord.connection_id == connection.id, RawRecord.process_status == "failed"
                )
            ).all()
            months = 6  # the first voucher of each month has the over-long values
            assert len(failed) == months + 1  # plus the one with amounts out of range
            too_long = [
                e for e in failed if e.startswith("DataError: MySQL 1406 too long: vouchers.")
            ]
            assert len(too_long) == months
            assert all("(values up to 300 characters)" in e and "NNN" not in e for e in too_long)
            converted = session.scalar(
                select(func.count())
                .select_from(A.Voucher)
                .where(A.Voucher.connection_id == connection.id)
            )
            assert converted == transport.total_vouchers - months - 1
        finally:
            _cleanup(session)
