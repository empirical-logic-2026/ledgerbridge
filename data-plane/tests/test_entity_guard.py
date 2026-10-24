"""The expected company must be loaded (LB-SYNC-011): sync, the deletion check, validation,
analyse and statements stop before comparing or storing anything when the source doesn't
have the entity's company (by its GUID) loaded, or has another company of the same name
loaded too. Pilot 2026-10-23: a run with another company loaded reported 3,742 ledgers
missing."""

from dataclasses import replace
from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from connectors.base import SourceEntity
from connectors.tally.connector import TallyConnector
from core.models import accounting as A  # noqa: N812
from core.models import system as S  # noqa: N812
from tests.conftest import COMPANY
from workers.entities import EntityLookupError, ExpectedEntityNotLoadedError, ensure_loaded
from workers.sync import run_deletion_check, run_sync
from workers.validate import alert_for_run, run_validation

AS_OF = date(2026, 10, 2)


def _switch(connector: TallyConnector, monkeypatch: pytest.MonkeyPatch, how: str) -> None:
    """From now on the source lists another company instead (`gone`), or a namesake beside
    the expected one (`namesake`)."""
    loaded = connector.list_entities()
    other = replace(loaded[0], key="another-company-guid")
    listed = [other] if how == "gone" else [*loaded, other]
    monkeypatch.setattr(connector, "list_entities", lambda: listed)


def test_the_guard_needs_the_company_by_key_and_no_namesake() -> None:
    class Source:
        def __init__(self, *entities: SourceEntity) -> None:
            self.entities = list(entities)

        def list_entities(self) -> list[SourceEntity]:
            return self.entities

    mine = SourceEntity("guid-1", "Company")
    ensure_loaded(Source(mine), mine)  # type: ignore[arg-type]
    with pytest.raises(ExpectedEntityNotLoadedError, match="expected company not loaded"):
        ensure_loaded(Source(SourceEntity("guid-2", "Company")), mine)  # type: ignore[arg-type]
    with pytest.raises(ExpectedEntityNotLoadedError, match="same name"):
        ensure_loaded(Source(mine, SourceEntity("guid-2", "Company")), mine)  # type: ignore[arg-type]


@pytest.mark.parametrize("how", ["gone", "namesake"])
def test_validation_stops_and_records_nothing(
    db: Session, synced: S.Connection, connector: TallyConnector, monkeypatch: pytest.MonkeyPatch,
    how: str,
) -> None:  # fmt: skip
    runs = db.scalar(select(func.count()).select_from(S.ValidationRun))
    keys = [e.key for e in connector.list_entities()]
    _switch(connector, monkeypatch, how)
    # Gone from the start: the entity lookup stops it first (LB-SYNC-006); a namesake: the
    # guard (LB-SYNC-011).
    with pytest.raises((ExpectedEntityNotLoadedError, EntityLookupError)):
        run_validation(db, synced, connector, entity_keys=keys, as_of=AS_OF, thorough=True)
    assert db.scalar(select(func.count()).select_from(S.ValidationRun)) == runs
    assert db.scalar(select(func.count()).select_from(S.ValidationIssue)) == 0
    assert db.scalar(select(func.count()).select_from(S.Alert)) == 0


def test_a_company_switched_while_reading_is_not_compared(
    db: Session, synced: S.Connection, connector: TallyConnector, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The source switched company after the guard's first look: the second look, after
    reading, stops the run before anything is compared."""
    keys = [e.key for e in connector.list_entities()]
    read = connector.closing_balances

    def switch_then_read(entity, as_of):  # noqa: ANN001, ANN202
        _switch(connector, monkeypatch, "gone")
        return read(entity, as_of)

    monkeypatch.setattr(connector, "closing_balances", switch_then_read)
    with pytest.raises(ExpectedEntityNotLoadedError):
        run_validation(db, synced, connector, entity_keys=keys, as_of=AS_OF)
    assert db.scalar(select(func.count()).select_from(S.ValidationIssue)) == 0


def test_sync_stops_as_interrupted_without_an_alert(
    db: Session, synced: S.Connection, connector: TallyConnector, monkeypatch: pytest.MonkeyPatch
) -> None:
    _switch(connector, monkeypatch, "namesake")
    result = run_sync(db, synced, connector, [COMPANY])
    assert result.status == "interrupted"
    assert (result.error or "").startswith("ExpectedEntityNotLoadedError")
    assert alert_for_run(db, synced, result) is False
    assert db.scalar(select(func.count()).select_from(S.Alert)) == 0


def test_the_deletion_check_marks_nothing_when_the_company_switched(
    db: Session, synced: S.Connection, connector: TallyConnector, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Listing another company's keys would mark every ledger deleted: the second look,
    after listing, stops it."""
    keys = [e.key for e in connector.list_entities()]
    listed = connector.list_keys

    def switch_then_list(entity):  # noqa: ANN001, ANN202
        found = {object_type: set() for object_type in listed(entity)}  # another company's
        _switch(connector, monkeypatch, "gone")
        return found

    monkeypatch.setattr(connector, "list_keys", switch_then_list)
    result = run_deletion_check(db, synced, connector, entity_keys=keys)
    assert result.status == "interrupted" and not result.deleted
    deleted = db.scalar(select(func.count()).select_from(A.Ledger).where(A.Ledger.is_deleted))
    assert deleted == 0


def test_statements_stop_too(
    db: Session, synced: S.Connection, connector: TallyConnector, monkeypatch: pytest.MonkeyPatch
) -> None:
    from workers.statements import fill

    entity = connector.list_entities()[0]
    entity_id = db.scalars(select(A.Entity)).one().id
    _switch(connector, monkeypatch, "gone")
    with pytest.raises(ExpectedEntityNotLoadedError):
        fill(db, synced, connector, entity, entity_id, [AS_OF], lambda _: None)


def test_alerts_close_with_their_reason(
    db: Session, synced: S.Connection, connector: TallyConnector
) -> None:
    """Every alert closes with its reason (migration 0019): the company's own alert when its
    validation passes; one without a company (from before alerts were kept per company: pilot
    2026-10-24, alert 4) once every company passed; one about a company no longer on the
    connection, since no run of it will ever pass."""
    from core.alerts import raise_alert

    entity_id = db.scalars(select(A.Entity)).one().id
    gone = A.Entity(code="GONE", name="A company no longer connected")
    db.add(gone)
    db.commit()
    own = raise_alert(db, "validation_failed", synced.id, "failed", entity_id=entity_id)
    old = raise_alert(db, "validation_failed", synced.id, "from before alerts per entity")
    other = raise_alert(db, "validation_failed", synced.id, "failed", entity_id=gone.id)
    keys = [e.key for e in connector.list_entities()]
    (report,) = run_validation(db, synced, connector, entity_keys=keys, as_of=AS_OF)
    assert report.status == "passed"
    for alert in (own, old, other):
        db.refresh(alert)
        assert alert.resolved_at is not None
    assert own.resolution == f"validation run {report.validation_run_id} passed"
    assert old.resolution == "every company on the connection last validated as passed"
    assert other.resolution == "the company is no longer on the connection"


def test_an_alert_without_a_company_stays_open_while_a_company_fails(
    db: Session, synced: S.Connection
) -> None:
    from core.alerts import open_alert, raise_alert
    from core.models.base import utcnow
    from workers.validate import _resolve_alerts_beyond_entities

    entity_id = db.scalars(select(A.Entity)).one().id
    raise_alert(db, "validation_failed", synced.id, "from before alerts per entity")
    db.add(S.ValidationRun(entity_id=entity_id, as_of=AS_OF, started_at=utcnow(), status="failed"))
    db.commit()
    _resolve_alerts_beyond_entities(db, synced)
    assert open_alert(db, "validation_failed", synced.id) is not None


def test_the_summary_heads_open_differences_apart(capsys: pytest.CaptureFixture[str]) -> None:
    from workers.cli import _print_statement_summary

    taken = "Balance sheet: Current Assets: taken from the source, ours computed differs at 1"
    _print_statement_summary([taken])
    out = capsys.readouterr().out
    assert "[statement_taken_from_source, LB-VAL-026]" in out and "LB-VAL-024" not in out
    _print_statement_summary(["Profit & loss: Cost of Sales: different amount at 1", taken])
    out = capsys.readouterr().out
    assert out.index("LB-VAL-024") < out.index("LB-VAL-026")
