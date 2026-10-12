from sqlalchemy import event, func, select
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


def test_never_waits_on_the_source_with_uncommitted_writes(session: Session) -> None:
    """Every write is committed before the next record is requested from the source, so a
    slow source can't keep the connection row locked (MySQL error 1205, pilot run)."""
    connection = _connection(session)
    session.commit()
    events: list[str] = []
    engine = session.get_bind()

    @event.listens_for(engine, "before_cursor_execute")
    def _sql(conn, cursor, statement, *args) -> None:  # noqa: ANN001
        verb = statement.lstrip().split()[0].upper()
        if verb in ("INSERT", "UPDATE"):
            events.append("write")

    @event.listens_for(engine, "commit")
    def _commit(conn) -> None:  # noqa: ANN001
        events.append("commit")

    def slow_source():  # noqa: ANN202
        for number in range(7):
            events.append("wait for source")
            yield _record(f"k{number}", f"<L>{number}</L>")

    try:
        result = RawStore(session, batch_size=3).add(slow_source(), connection.id)
    finally:
        event.remove(engine, "before_cursor_execute", _sql)
        event.remove(engine, "commit", _commit)
    assert result.stored == 7
    uncommitted = False
    for name in events:
        if name == "write":
            uncommitted = True
        elif name == "commit":
            uncommitted = False
        else:
            assert not uncommitted, events
    assert events.count("write") == 3  # batches of 3, 3 and 1
