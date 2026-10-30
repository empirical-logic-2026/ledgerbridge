"""Entities on hold (SYN-007): skipped unless named, outside the report's verdict, audited.

Pilot 2026-10-30: one of seven companies is on hold and isn't loaded in Tally. Every command
over all companies stopped on it ("1 of 7 configured entities are not available"), and its
failed validation kept the report's overall verdict at FAILED.
"""

from decimal import Decimal

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from connectors.tally.connector import TallyConnector
from core.models import accounting as A  # noqa: N812
from core.models import system as S  # noqa: N812
from tests.conftest import COMPANY
from workers import cli
from workers.entities import EntityLookupError, on_hold_line, select_not_on_hold
from workers.on_hold import list_entities, set_on_hold
from workers.report import FAILED, ON_HOLD, build, render_markdown, render_text
from workers.validate import run_validation

HELD_KEY = "held-company-guid"


def _test_company(db: Session) -> A.Entity:
    return db.scalars(select(A.Entity).order_by(A.Entity.id)).first()


def _add_company_not_loaded(db: Session, connection: S.Connection) -> A.Entity:
    """A configured company the source doesn't have loaded (like the pilot's company on
    hold), with its entity; the test company configured too."""
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
    loaded = db.scalars(select(A.EntitySource.source_entity_key)).first()
    connection.config = {
        **connection.config,
        "entities": [{"key": loaded, "name": COMPANY}, {"key": HELD_KEY, "name": "Held Co"}],
    }
    db.commit()
    return entity


def test_set_and_clear_are_audited(db: Session, synced: S.Connection) -> None:
    entity = _test_company(db)
    said: list[str] = []
    assert set_on_hold(db, entity.id, True, said.append) == 0
    assert db.get_one(A.Entity, entity.id).is_on_hold
    assert set_on_hold(db, entity.id, True, said.append) == 0  # already: nothing changes
    assert set_on_hold(db, entity.id, False, said.append) == 0
    assert not db.get_one(A.Entity, entity.id).is_on_hold
    assert said == [
        f"entity {entity.id} (company 1): on hold",
        f"entity {entity.id} (company 1): already on hold; nothing changed",
        f"entity {entity.id} (company 1): not on hold",
    ]
    actions = db.scalars(select(S.AuditLog.action).order_by(S.AuditLog.id)).all()
    assert actions == ["entity_on_hold_set", "entity_on_hold_cleared"]
    assert all(COMPANY not in line for line in said)
    assert set_on_hold(db, 999, True, said.append) == 2


def test_list_shows_entities_on_hold_first(db: Session, synced: S.Connection) -> None:
    held = _add_company_not_loaded(db, synced)
    set_on_hold(db, held.id, True, lambda _: None)
    said: list[str] = []
    list_entities(db, said.append)
    assert said[0].endswith(": on hold") and said[0].startswith(f"entity {held.id} ")
    assert said[1].endswith(": not on hold")


def test_commands_skip_entities_on_hold_unless_named(
    db: Session, synced: S.Connection, connector: TallyConnector
) -> None:
    held = _add_company_not_loaded(db, synced)
    with pytest.raises(EntityLookupError):  # before: every command stopped on it
        select_not_on_hold(db, connector, synced)
    set_on_hold(db, held.id, True, lambda _: None)
    found, skipped = select_not_on_hold(db, connector, synced)
    assert [e.name for e in found] == [COMPANY] and skipped == 1
    assert on_hold_line(skipped) == (
        "1 company on hold, skipped (name it with -Company to include it; "
        "./dev.ps1 on-hold lists them)"
    )

    entity = _test_company(db)
    set_on_hold(db, entity.id, True, lambda _: None)
    assert select_not_on_hold(db, connector, synced) == ([], 2)
    assert run_validation(db, synced, connector) == []  # nothing validated
    named, skipped = select_not_on_hold(db, connector, synced, [COMPANY])
    assert [e.name for e in named] == [COMPANY] and skipped == 0
    assert len(run_validation(db, synced, connector, [COMPANY])) == 1


def test_the_report_lists_entities_on_hold_outside_the_verdict(
    db: Session, synced: S.Connection, connector: TallyConnector
) -> None:
    entity = _test_company(db)
    line = db.scalars(select(A.VoucherLine)).first()
    line.amount += Decimal("1")  # an unbalanced voucher: the validation fails
    db.commit()
    run_validation(db, synced, connector, [COMPANY])
    assert build(db, "test").verdict == FAILED

    set_on_hold(db, entity.id, True, lambda _: None)
    report = build(db, "test")
    assert report.verdict != FAILED
    text = render_text(report)
    assert f"== {ON_HOLD}: not part of the overall verdict ==" in text
    assert f"entity {entity.id} (company 1): on hold; latest validation FAILED as of " in text
    assert "Vouchers that don't balance" not in text
    assert f"## {ON_HOLD}: not part of the overall verdict" in render_markdown(report)
    assert build(db, "test", [COMPANY]).verdict == FAILED  # named: reported as before


def test_the_cli_command(
    db: Session,
    synced: S.Connection,
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    entity = _test_company(db)
    monkeypatch.setattr(cli, "get_engine", lambda: engine)
    monkeypatch.setattr(cli, "_terminate_raises_system_exit", lambda: None)
    assert cli.main(["on-hold", "set", "--entity-id", str(entity.id)]) == 0
    db.expire_all()
    assert db.get_one(A.Entity, entity.id).is_on_hold
    assert cli.main(["on-hold", "set"]) == 2
    assert cli.main(["on-hold"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[-1] == f"entity {entity.id} (company 1): on hold"
    assert COMPANY not in out
