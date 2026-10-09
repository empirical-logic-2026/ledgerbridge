from sqlalchemy import func, select
from sqlalchemy.orm import Session

from connectors.base import SourceRecord
from core.models import Connection, RawRecord, Source
from core.raw_store import RawStore, payload_hash


def _connection(session: Session) -> Connection:
    source = Source(code="fake", name="Fake", connector_version="0")
    session.add(source)
    session.flush()
    connection = Connection(source_id=source.id, name="fake-1", config={})
    session.add(connection)
    session.flush()
    return connection


def _record(key: str, payload: str, alter_id: int = 1) -> SourceRecord:
    return SourceRecord("entity-1", "ledger", key, alter_id, "xml", payload)


def test_stores_records_unchanged(session: Session) -> None:
    connection = _connection(session)
    result = RawStore(session).add(
        [_record("a", "<L>1</L>"), _record("b", "<L>2</L>")], connection.id
    )
    assert (result.received, result.stored, result.skipped) == (2, 2, 0)
    row = session.scalars(select(RawRecord).where(RawRecord.source_key == "a")).one()
    assert row.payload == "<L>1</L>"
    assert row.payload_hash == payload_hash("<L>1</L>")
    assert row.process_status == "pending"
    assert row.source_entity_key == "entity-1"
    assert row.source_alter_id == 1


def test_skips_unchanged_and_stores_changed_payloads(session: Session) -> None:
    connection = _connection(session)
    store = RawStore(session, batch_size=1)
    store.add([_record("a", "<L>1</L>")], connection.id)
    again = store.add([_record("a", "<L>1</L>"), _record("a2", "<L>9</L>")], connection.id)
    changed = store.add([_record("a", "<L>1 changed</L>", alter_id=2)], connection.id)
    assert (again.stored, again.skipped) == (1, 1)
    assert (changed.stored, changed.skipped) == (1, 0)
    count = session.scalar(
        select(func.count()).select_from(RawRecord).where(RawRecord.source_key == "a")
    )
    assert count == 2
