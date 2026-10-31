"""Whether the source had each company loaded when last asked (migration 0025): recorded by
a sync and by entity-check, for the dashboard's company chips (it never asks the source)."""

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from connectors.tally.connector import TallyConnector
from core.models import accounting as A  # noqa: N812
from core.models import system as S  # noqa: N812
from tests.conftest import COMPANY
from workers import cli
from workers.on_hold import set_on_hold
from workers.sync import run_sync

HELD_KEY = "held-company-guid"


def _links(db: Session) -> dict[str, A.EntitySource]:
    db.expire_all()
    return {link.source_entity_key: link for link in db.scalars(select(A.EntitySource))}


def _add_company_not_loaded(db: Session, connection: S.Connection) -> A.Entity:
    entity = A.Entity(code="HELD_CO", name="Held Co")
    db.add(entity)
    db.flush()
    db.add(
        A.EntitySource(
            entity_id=entity.id,
            connection_id=connection.id,
            source_entity_key=HELD_KEY,
            source_entity_name="Held Co",
        )
    )
    db.commit()
    return entity


def test_a_sync_records_which_companies_are_loaded(
    db: Session, synced: S.Connection, connector: TallyConnector
) -> None:
    (loaded,) = _links(db).values()
    assert loaded.source_loaded is True and loaded.source_checked_by == "sync"
    first = loaded.source_checked_at
    assert first is not None

    held = _add_company_not_loaded(db, synced)
    set_on_hold(db, held.id, True, lambda _: None)
    assert run_sync(db, synced, connector, [COMPANY]).status == "succeeded"
    links = _links(db)
    assert links[HELD_KEY].source_loaded is False  # asked: the source doesn't have it
    assert links[HELD_KEY].source_checked_by == "sync"
    assert links[loaded.source_entity_key].source_loaded is True
    assert links[loaded.source_entity_key].source_checked_at >= first


def test_entity_check_records_them_too(
    db: Session,
    synced: S.Connection,
    connector: TallyConnector,
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _add_company_not_loaded(db, synced)
    monkeypatch.setattr(cli, "get_engine", lambda: engine)
    monkeypatch.setattr(cli, "_terminate_raises_system_exit", lambda: None)
    monkeypatch.setattr(cli, "connector_for", lambda session, connection: connector)
    cli.main(["entity-check", "--connection", synced.name, "--no-probe"])
    links = _links(db)
    assert {k: (v.source_loaded, v.source_checked_by) for k, v in links.items()} == {
        next(k for k in links if k != HELD_KEY): (True, "entity_check"),
        HELD_KEY: (False, "entity_check"),
    }


def test_never_asked_is_empty(db: Session) -> None:
    entity = A.Entity(code="NEW_CO", name="New Co")
    db.add(entity)
    db.flush()
    link = A.EntitySource(entity_id=entity.id, connection_id=1, source_entity_key="k",
                          source_entity_name="New Co")  # fmt: skip
    assert link.source_loaded is None and link.source_checked_at is None
