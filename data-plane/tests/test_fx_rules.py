"""The fx-rules finder (ADR-043, core/fx_rules.py): which revaluation rule the source's
statements follow, counted over the dates `statements` stored. Synthetic foreign figures on
the test company's year-end books (tests/test_fx_core.py): a $100 sale at Rs 82 on
2026-08-01 to the dollar customer, a standard rate list of Rs 80 (2025-04-01) and Rs 83
(2026-03-31), a selling rate of Rs 84 (2026-03-31)."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from connectors.tally.connector import TallyConnector
from connectors.tally.fixtures import FixtureTransport
from core import fx, fx_rules, statements
from core.models import accounting as A  # noqa: N812
from core.models import system as S  # noqa: N812
from core.models.base import utcnow
from core.models.reporting import StatementLine as LineRow
from core.transform import Transformer
from tests.stock_replay import YEAR_END, replay
from tests.test_cli import run_cli  # noqa: F401 - the fixture
from tests.test_fx_core import BOOKS, foreign_books  # noqa: F401 - the fixture
from workers import fx_rules as finder

DATES = (date(2025, 9, 2), date(2026, 3, 2), date(2026, 3, 31), date(2026, 5, 2),
         date(2026, 8, 31), date(2026, 10, 2))  # fmt: skip
ON_OR_BEFORE = "list standard, on or before"
PER_LEDGER = f"{fx_rules.THEIRS_ONLY}, rounded per ledger"


def _stored(db: Session, connection: S.Connection) -> tuple[int, frozenset[str]]:
    """The books rebuilt with the foreign figures, and the source's statements stored at
    the recorded dates (as `statements` does); with the groups the source nets."""
    connector = TallyConnector.from_config(
        {"url": "http://tally.test:9000"}, transport=FixtureTransport(BOOKS)
    )
    Transformer(db, connection.id, connector).run(rebuild=True)
    source_connector = TallyConnector.from_config(
        {"url": "http://tally.test:9000", "educational": "yes"},
        transport=replay("integrated", YEAR_END),
    )
    entity = source_connector.list_entities()[0]
    entity_id = db.scalars(select(A.Entity.id)).one()
    for on in DATES:
        statements.refresh(
            db, entity_id, connection.id, "live", source_connector.source_statements(entity, on)
        )
    return entity_id, source_connector.netted_groups(entity)


def _by(found: fx_rules.Finding) -> dict[tuple[str, str], fx_rules.Result]:
    return {(r.rule, r.variant): r for r in found.results}


def test_as_exported_reproduces_the_stored_statements(
    db: Session,
    foreign_books: S.Connection,  # noqa: F811 - the fixture
) -> None:  # noqa: F811
    """The calibration: laid out with the source's own revalued balances, the groups and
    the forex line equal the source's at every date (as `statements` found them)."""
    entity_id, netted = _stored(db, foreign_books)
    found = fx_rules.find(db, entity_id, list(DATES), netted)
    exported = _by(found)[("as exported (calibration)", fx_rules.THEIRS_ONLY)]
    assert (found.dates, exported.groups_exact, exported.forex_exact) == (6, 6, 6)
    # The dollar customer (Current Assets) and the dollar vendor (Current Liabilities); Customer
    # Hotel USD is kept in rupees with a dollar opening.
    assert (found.foreign_ledgers, found.other_ledgers_with_foreign_figures, found.groups) == (
        2,
        1,
        2,
    )
    assert found.rate_kinds == {"standard": 2, "selling": 1, "vouchers": 1}


def test_the_finder_names_the_rule_the_source_follows(
    db: Session,
    foreign_books: S.Connection,  # noqa: F811 - the fixture
) -> None:  # noqa: F811
    """With the source's lines as the source would show them revaluing by the last
    standard rate on or before each date, that rule matches every date; the exact-date
    rule and book value don't."""
    entity_id, netted = _stored(db, foreign_books)
    rates = fx_rules.Rates(db, entity_id)
    for on in DATES:
        _as_if_revalued(db, entity_id, on, rates, netted)
    finding = fx_rules.find(db, entity_id, list(DATES), netted)
    found = _by(finding)
    full = found[(ON_OR_BEFORE, PER_LEDGER)]
    assert (full.groups_exact, full.forex_exact) == (6, 6)
    exact = found[("list standard, exact date", PER_LEDGER)]
    assert exact.forex_exact < 6  # the sale's dollars, revalued only where a rate is dated
    book = found[("book value", fx_rules.THEIRS_ONLY)]
    assert book.forex_exact < 6
    conclusion = finder.lines("entity 1", finding)[-1]
    assert conclusion.startswith("entity 1: rules matching every date exactly: ")
    assert f'"{ON_OR_BEFORE}" ({PER_LEDGER})' in conclusion
    assert "calibration" not in conclusion  # it always matches; never offered as the rule


def _as_if_revalued(
    db: Session, entity_id: int, on: date, rates: fx_rules.Rates, netted: frozenset[str]
) -> None:
    """Rewrites the stored source figures at a date as the source would show them if it
    revalued the dollar customer by the last standard rate on or before the date."""
    source = fx_rules.stored_source(db, entity_id, on, netted)
    f = statements.figures(db, entity_id, source)
    by_id = fx.foreign_balances(db, entity_id, on)
    revalued = {}
    for x in f.ledgers:
        if x.key in source.revalued:
            balance = by_id.get(x.id)
            amount = balance.balance_fc if balance else Decimal(0)
            rate = rates.on_or_before("$", "standard", on) or Decimal(0)
            revalued[x.key] = (amount * rate).quantize(fx_rules.CENT)
    laid = replace(f, source=replace(source, revalued=revalued, lines=()))
    lines = []
    for _, line in statements.lines_for(laid):
        if line.label == statements.COMPUTED_FOREX:
            lines.append(replace(line, label=statements.UNADJUSTED_FOREX, level="main"))
        elif line.level != "detail" and line.statement in (fx_rules.TB, fx_rules.BS):
            lines.append(line)
    db.execute(delete(LineRow).where(LineRow.entity_id == entity_id, LineRow.as_of == on,
                                     LineRow.figures == "source"))  # fmt: skip
    db.add_all(
        LineRow(
            entity_id=entity_id,
            as_of=on,
            statement=x.statement,
            figures="source",
            line_no=n,
            section=None,
            label=x.label,
            match_key=statements.match_key(x.label),
            level=x.level,
            amount=x.amount,
            debit=x.debit,
            credit=x.credit,
            refreshed_at=utcnow(),
        )  # fmt: skip
        for n, x in enumerate(lines, start=1)
    )
    for snapshot in db.scalars(
        select(A.FxRevaluationSnapshot).where(
            A.FxRevaluationSnapshot.entity_id == entity_id, A.FxRevaluationSnapshot.as_of == on
        )
    ):
        key = db.get(A.Ledger, snapshot.ledger_id).source_key
        snapshot.revalued_value = revalued.get(key, snapshot.revalued_value)
    db.commit()


def test_the_output_is_counts_and_rule_names_only(db: Session, foreign_books: S.Connection) -> None:  # noqa: F811
    entity_id, netted = _stored(db, foreign_books)
    out = finder.lines("entity 1 (company 1)", fx_rules.find(db, entity_id, list(DATES), netted))
    text = "\n".join(out)
    names = set(db.scalars(select(A.Ledger.name))) | set(db.scalars(select(A.AccountGroup.name)))
    assert not [n for n in names if n in text and n not in ("Primary",)]
    assert out[0].startswith("entity 1 (company 1): 6 dates; 2 foreign-currency ledgers")
    assert 'rule "as exported (calibration)"' in text
    assert "entity 1 (company 1): calibration reproduces the source at every date" in out


def test_a_calibration_that_fails_is_said() -> None:
    finding = fx_rules.Finding(dates=2, foreign_ledgers=1)
    finding.results.append(fx_rules.Result(fx_rules.CALIBRATION, fx_rules.THEIRS_ONLY))
    out = finder.lines("entity 1", finding)
    assert "entity 1: calibration doesn't reproduce the source at every date" in out[-2]
    assert out[-1] == "entity 1: no rule matches every date exactly"


def test_the_command_needs_stored_statements(db: Session, run_cli) -> None:  # noqa: ANN001, F811
    run_cli("connect", "--connection", "tally-pilot", "--source", "tally", "--origin", "backup",
            "--all")  # fmt: skip
    run_cli("sync", "--connection", "tally-pilot", "--full", "--no-validate")
    code, out = run_cli("fx-rules", "--connection", "tally-pilot")
    assert code == 2
    assert "no statements stored yet; run ./dev.ps1 statements first" in out
    assert "Result: fx-rules finished" in out
