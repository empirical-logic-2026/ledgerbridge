from collections.abc import Iterator

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from connectors import registry
from connectors.base import ConnectionStatus, Period, SourceEntity, SourceRecord
from core.models import RawRecord, SyncRun
from workers import cli
from workers.extract import find_entity, get_or_create_connection, run_extract

ENTITY = SourceEntity(key="e-1", name="Fake Co")


class FakeConnector:
    source_code = "fake"

    def __init__(self, fail_on_transactions: bool = False) -> None:
        self.fail = fail_on_transactions

    def test_connection(self) -> ConnectionStatus:
        return ConnectionStatus(ok=True)

    def list_entities(self) -> list[SourceEntity]:
        return [ENTITY]

    def fetch_masters(
        self, entity: SourceEntity, since_marker: str | None = None
    ) -> Iterator[SourceRecord]:
        yield SourceRecord(entity.key, "ledger", "l-1", 1, "xml", "<LEDGER/>")

    def fetch_transactions(
        self, entity: SourceEntity, since_marker: str | None = None, period: Period | None = None
    ) -> Iterator[SourceRecord]:
        yield SourceRecord(entity.key, "voucher", "v-1", 2, "xml", "<VOUCHER/>")
        if self.fail:
            raise RuntimeError("source went away")

    def to_canonical(self, record: SourceRecord) -> object:
        raise NotImplementedError


@pytest.fixture
def fake_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(registry.SOURCE_INFO, "fake", ("Fake", "0"))
    monkeypatch.setitem(registry._FACTORIES, "fake", lambda _config: FakeConnector())
    monkeypatch.setattr(registry, "default_config", lambda code: {"url": "fake://"})


def test_connection_requires_source_when_new(session: Session) -> None:
    with pytest.raises(ValueError, match="pass --source"):
        get_or_create_connection(session, "missing", None)


def test_successful_run_is_logged(session: Session, fake_source: None) -> None:
    connection = get_or_create_connection(session, "fake-conn", "fake")
    assert get_or_create_connection(session, "fake-conn", None).id == connection.id

    result = run_extract(session, connection, FakeConnector(), ENTITY)

    assert result.status == "succeeded"
    assert dict(result.by_object_type) == {"ledger": 1, "voucher": 1}
    run = session.get_one(SyncRun, result.sync_run_id)
    assert (run.status, run.run_type, run.records_received) == ("succeeded", "full", 2)
    assert run.finished_at is not None
    assert session.scalar(select(func.count()).select_from(RawRecord)) == 2

    second = run_extract(session, connection, FakeConnector(), ENTITY)
    assert (second.stored, second.skipped) == (0, 2)


def test_failed_run_rolls_back_and_records_error(session: Session, fake_source: None) -> None:
    connection = get_or_create_connection(session, "fake-conn", "fake")
    session.commit()
    result = run_extract(session, connection, FakeConnector(fail_on_transactions=True), ENTITY)
    assert result.status == "failed"
    run = session.get_one(SyncRun, result.sync_run_id)
    assert run.status == "failed"
    assert run.error_summary == "RuntimeError: source went away"
    assert session.scalar(select(func.count()).select_from(RawRecord)) == 0


def test_find_entity_by_name() -> None:
    assert find_entity(FakeConnector(), "Fake Co") == ENTITY
    with pytest.raises(LookupError, match="1 listed"):
        find_entity(FakeConnector(), "Other Co")


def test_cli_extract(
    session: Session, fake_source: None, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(cli, "get_engine", lambda: session.get_bind())
    code = cli.main(["extract", "--connection", "c", "--source", "fake", "--entity", "Fake Co"])
    out = capsys.readouterr().out
    assert code == 0
    assert "succeeded" in out and "voucher: 1" in out and "ledger: 1" in out
