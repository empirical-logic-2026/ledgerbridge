"""M3 and M4 on MySQL: full and incremental sync of the recorded fixtures, then validation
(./dev.ps1 up)."""

from decimal import Decimal

import pytest
from alembic import command
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from connectors.tally.connector import TallyConnector
from connectors.tally.fixtures import DEFAULT_DIR, FixtureTransport
from core.db import get_engine
from core.models import accounting as A  # noqa: N812
from core.models import system as S  # noqa: N812
from core.transform import trial_balance
from tests.test_migrations_integration import _config
from workers.extract import get_or_create_connection
from workers.sync import run_sync
from workers.validate import run_validation

pytestmark = pytest.mark.integration

CONNECTION = "tally-fixture-it"


def _cleanup(session: Session) -> None:
    """Removes this test's own connection and everything built from it."""
    connection = session.scalar(select(S.Connection).where(S.Connection.name == CONNECTION))
    if connection is None:
        return
    from core.models.source import RawRecord

    entity_ids = list(
        session.scalars(
            select(A.EntitySource.entity_id).where(A.EntitySource.connection_id == connection.id)
        )
    )
    vouchers = select(A.Voucher.id).where(A.Voucher.connection_id == connection.id)
    lines = select(A.VoucherLine.id).where(A.VoucherLine.voucher_id.in_(vouchers))
    for model in (A.BillAllocation, A.LineCostAllocation, A.LineDimension):
        session.execute(delete(model).where(model.voucher_line_id.in_(lines)))
    for model in (A.TaxLine, A.InventoryLine, A.VoucherLine):
        session.execute(delete(model).where(model.voucher_id.in_(vouchers)))
    session.execute(delete(A.Voucher).where(A.Voucher.connection_id == connection.id))
    session.execute(delete(A.Item).where(A.Item.connection_id == connection.id))
    # Self-referencing tables: clear parent links before deleting the rows.
    for model in (A.ItemGroup, A.Godown, A.CostCentre, A.AccountGroup):
        session.execute(
            model.__table__.update()
            .where(model.connection_id == connection.id)
            .values(parent_id=None)
        )
    session.execute(delete(A.Ledger).where(A.Ledger.connection_id == connection.id))
    for model in (
        A.Party,
        A.Unit,
        A.VoucherType,
        A.ItemGroup,
        A.Godown,
        A.CostCentre,
        A.AccountGroup,
    ):
        session.execute(delete(model).where(model.connection_id == connection.id))
    runs = select(S.ValidationRun.id).where(S.ValidationRun.entity_id.in_(entity_ids))
    session.execute(delete(S.Alert).where(S.Alert.connection_id == connection.id))
    session.execute(delete(S.ValidationIssue).where(S.ValidationIssue.validation_run_id.in_(runs)))
    session.execute(delete(S.ValidationRun).where(S.ValidationRun.entity_id.in_(entity_ids)))
    values = select(A.DimensionValue.id).where(A.DimensionValue.entity_id.in_(entity_ids))
    session.execute(delete(A.LineDimension).where(A.LineDimension.dimension_value_id.in_(values)))
    session.execute(delete(A.DimensionValue).where(A.DimensionValue.entity_id.in_(entity_ids)))
    session.execute(delete(A.SourceField).where(A.SourceField.entity_id.in_(entity_ids)))
    session.execute(delete(A.EntitySource).where(A.EntitySource.connection_id == connection.id))
    session.execute(delete(A.Entity).where(A.Entity.id.in_(entity_ids)))
    session.execute(delete(RawRecord).where(RawRecord.connection_id == connection.id))
    session.execute(delete(S.SyncMarker).where(S.SyncMarker.connection_id == connection.id))
    session.execute(delete(S.SyncRun).where(S.SyncRun.connection_id == connection.id))
    session.execute(delete(S.Connection).where(S.Connection.id == connection.id))
    session.commit()


def test_full_then_incremental_sync_on_mysql(monkeypatch: pytest.MonkeyPatch) -> None:
    if not (DEFAULT_DIR / "manifest.json").exists():
        pytest.skip("no recorded fixtures")
    command.upgrade(_config(), "head")
    monkeypatch.setattr(
        "connectors.registry.default_config", lambda code: {"url": "http://tally.test:9000"}
    )
    connector = TallyConnector.from_config(
        {"url": "http://tally.test:9000"}, transport=FixtureTransport(DEFAULT_DIR)
    )
    with Session(get_engine()) as session:
        _cleanup(session)
        try:
            connection = get_or_create_connection(session, CONNECTION, "tally")
            session.commit()
            first = run_sync(session, connection, connector)
            assert (first.status, first.run_type, first.failed) == ("succeeded", "full", 0)
            entity_id = session.scalar(
                select(A.EntitySource.entity_id).where(
                    A.EntitySource.connection_id == connection.id
                )
            )
            balances = dict(trial_balance(session, entity_id))
            assert balances["Rent"] == Decimal("1000")
            assert balances["Cash"] == Decimal("27500")
            assert balances["Capital"] == Decimal("-50000")
            vouchers = session.scalar(
                select(func.count())
                .select_from(A.Voucher)
                .where(A.Voucher.connection_id == connection.id)
            )
            assert vouchers == 18

            (report,) = run_validation(session, connection, connector)
            assert (report.status, report.checks_failed) == ("passed", 0), report.findings

            second = run_sync(session, connection, connector)
            assert (second.status, second.run_type) == ("succeeded", "incremental")
            assert sum(n for t, n in second.fetched.items() if t != "company") == 0
            assert dict(trial_balance(session, entity_id)) == balances
        finally:
            _cleanup(session)
