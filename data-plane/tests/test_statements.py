"""Statements built from our books against the source's own (ADR-040; RPT-012, VAL-015), on
the test company's recordings with accounts integrated with inventory and without
(tests/fixtures/tally/rules/stock_values/, 2026-10-22)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from connectors.base import SourceEntity
from connectors.tally.connector import TallyConnector
from core import statements
from core.models import accounting as A  # noqa: N812
from core.models import system as S  # noqa: N812
from core.models.reporting import StatementLine
from tests.stock_replay import replay

AS_OF = date(2026, 10, 2)


def _source(case: str, as_of: date = AS_OF):  # noqa: ANN202
    connector = TallyConnector.from_config(
        {"url": "http://tally.test:9000", "educational": "yes"}, transport=replay(case)
    )
    entity = connector.list_entities()[0]
    return connector.source_statements(entity, as_of)


@pytest.mark.parametrize("case", ["integrated", "not_integrated"])
def test_our_statements_match_the_sources_line_by_line(
    db: Session, synced: S.Connection, case: str
) -> None:
    entity_id = db.scalars(select(A.Entity)).one().id
    source = _source(case)
    result = statements.refresh(db, entity_id, synced.id, "live", source)
    listed = [(d.statement, d.label, str(d.ours), str(d.source)) for d in result.differences]
    assert listed == []
    assert result.compared > 20
