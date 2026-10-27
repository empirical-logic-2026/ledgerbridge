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
TODAY = f"{fx_rules.AT_BOOK}, {fx_rules.TODAY}"  # part 3: rupee ledgers at book value
OTHERS_BY = f'rupee ledgers with foreign amounts by "{ON_OR_BEFORE}"'  # part 2
HOTEL = "Customer Hotel USD"  # kept in rupees with a dollar opening (tests/test_fx_core.py)


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


def _by(results: list[fx_rules.Result]) -> dict[tuple[str, str], fx_rules.Result]:
    return {(r.rule, r.variant): r for r in results}


def test_the_calibration_is_the_statements_own_layout(
    db: Session,
    foreign_books: S.Connection,  # noqa: F811 - the fixture
) -> None:  # noqa: F811
    """Laid out as `statements` does with the source's own revalued balances, the groups and
    the forex line equal the source's at every date (as `statements` found them)."""
    entity_id, netted = _stored(db, foreign_books)
    found = fx_rules.find(db, entity_id, list(DATES), netted)
    calibration = found.calibration()
    assert (found.dates, calibration.groups_exact, calibration.forex_exact) == (6, 6, 6)
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
    """With the source revaluing its foreign ledgers by the last standard rate on or before
    each date, that rule matches every ledger-date (part 1) and every date (part 3); the
    exact-date rule and book value don't."""
    entity_id, netted = _stored(db, foreign_books)
    rates = fx_rules.Rates(db, entity_id)
    for on in DATES:
        _as_if_revalued(db, entity_id, on, rates, netted)
    finding = fx_rules.find(db, entity_id, list(DATES), netted)
    per_ledger = {p.rule: p for p in finding.per_ledger}
    assert per_ledger[ON_OR_BEFORE].exact == per_ledger[ON_OR_BEFORE].compared == 12
    assert per_ledger["book value"].exact < 12
    found = _by(finding.results)
    full = found[(ON_OR_BEFORE, TODAY)]
    assert (full.groups_exact, full.forex_exact) == (6, 6)
    assert found[("list standard, exact date", TODAY)].forex_exact < 6
    assert found[("book value", TODAY)].forex_exact < 6
    out = finder.lines("entity 1", finding)
    assert out[-3].startswith("entity 1: per ledger, rules matching every ledger-date: ")
    assert f'"{ON_OR_BEFORE}"' in out[-3]
    assert out[-1].startswith("entity 1: rules matching every date exactly: ")
    assert f'"{ON_OR_BEFORE}" ({TODAY})' in out[-1]


def test_rupee_ledgers_revalued_in_the_group_are_found(
    db: Session,
    foreign_books: S.Connection,  # noqa: F811 - the fixture
) -> None:  # noqa: F811
    """The source's group total also revalues the ledger it keeps in rupees, though its
    ledger-balance export doesn't: the calibration's groups then differ, and part 2 finds
    the rupee ledger revalued by the rule (the pilot's 60 of 78 dates, 2026-10-26)."""
    entity_id, netted = _stored(db, foreign_books)
    rates = fx_rules.Rates(db, entity_id)
    for on in DATES:
        _as_if_revalued(db, entity_id, on, rates, netted, rupee_ledgers=True)
    finding = fx_rules.find(db, entity_id, list(DATES), netted)
    assert finding.calibration().groups_exact < 6
    layout = _by(finding.layouts)[(OTHERS_BY, fx_rules.TODAY)]
    assert (layout.groups_exact, layout.forex_exact) == (6, 6)
    computed = _by(finding.results)[
        (ON_OR_BEFORE, f"rupee ledgers with foreign amounts too, {fx_rules.TODAY}")
    ]
    assert (computed.groups_exact, computed.forex_exact) == (6, 6)


def test_a_forex_line_of_the_opposite_sign_is_found(
    db: Session,
    foreign_books: S.Connection,  # noqa: F811 - the fixture
) -> None:  # noqa: F811
    """The source writes its forex line with the opposite sign: no layout of today's sign
    matches it, the opposite-sign form does (the pilot's forex line at 0 of 78 dates)."""
    entity_id, netted = _stored(db, foreign_books)
    rates = fx_rules.Rates(db, entity_id)
    for on in DATES:
        _as_if_revalued(db, entity_id, on, rates, netted, sign=-1)
    finding = fx_rules.find(db, entity_id, list(DATES), netted)
    assert finding.calibration().forex_exact < 6
    opposite = f"{fx_rules.TODAY}, opposite sign"
    assert _by(finding.layouts)[(fx_rules.AT_BOOK, opposite)].forex_exact == 6
    assert _by(finding.results)[(ON_OR_BEFORE, f"{fx_rules.AT_BOOK}, {opposite}")].forex_exact == 6


def test_the_forex_line_forms() -> None:
    """Ledger by ledger (losses the debit, gains the credit) against netted first."""
    d = fx_rules._Date(
        on=date(2026, 3, 31), f=None, source=None, groups=set(), theirs=({}, {}),
        balances={
            "a": fx.ForeignBalance(1, "$", Decimal(1)),
            "b": fx.ForeignBalance(2, "€", Decimal(1)),
            "c": fx.ForeignBalance(3, "$", Decimal(1)),
        },
        book={}, tops={"a": 10, "b": 10, "c": 20},
    )  # fmt: skip
    diffs = [("a", Decimal(30)), ("b", Decimal(-10)), ("c", Decimal(-5))]

    def parts(form: str, sign: int = 1) -> tuple[Decimal, Decimal, Decimal]:
        p = fx_rules._forex(form, sign, diffs, d)
        return tuple(p[k] for k in sorted(p))  # BS amount, TB credit, TB debit

    assert parts(fx_rules.LEDGER_BY_LEDGER) == (15, 15, 30)
    assert parts("netted in total") == (15, 0, 15)
    assert parts("netted per currency") == (15, 10, 25)  # $ 25, € -10
    assert parts("netted per group") == (15, 5, 20)  # group 10: 20, group 20: -5
    assert parts(fx_rules.LEDGER_BY_LEDGER, -1) == (-15, 30, 15)
    assert fx_rules._forex("netted in total", 1, [("a", Decimal(0))], d) == {}


def _as_if_revalued(
    db: Session,
    entity_id: int,
    on: date,
    rates: fx_rules.Rates,
    netted: frozenset[str],
    rupee_ledgers: bool = False,
    sign: int = 1,
) -> None:
    """Rewrites the stored source figures at a date as the source would show them if it
    revalued its foreign ledgers by the last standard rate on or before the date: its
    ledger-balance export (the snapshots) for those, its group lines also for the rupee
    ledger with a dollar opening when `rupee_ledgers`, its forex line with `sign`."""
    source = fx_rules.stored_source(db, entity_id, on, netted)
    f = statements.figures(db, entity_id, source)
    by_id = fx.foreign_balances(db, entity_id, on)
    rate = rates.on_or_before("$", "standard", on) or Decimal(0)
    revalued, shown = {}, {}
    for x in f.ledgers:
        balance = by_id.get(x.id)
        value = ((balance.balance_fc if balance else Decimal(0)) * rate).quantize(fx_rules.CENT)
        if x.key in source.revalued:
            revalued[x.key] = shown[x.key] = value
        elif rupee_ledgers and x.name == HOTEL:
            shown[x.key] = value
    laid = replace(f, source=replace(source, revalued=shown, lines=()))
    lines = []
    for _, line in statements.lines_for(laid):
        if line.label == statements.COMPUTED_FOREX:
            line = replace(line, label=statements.UNADJUSTED_FOREX, level="main")
            if sign < 0:
                line = replace(line, amount=-line.amount, debit=line.credit, credit=line.debit)
            lines.append(line)
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
    assert out[1].startswith("entity 1 (company 1): as `statements` lays them out today")
    assert "groups 6 of 6 exact" in out[1] and "forex line 6 of 6 exact" in out[1]
    for part in ("  1. Per ledger", "  2. Layout", "  3. Computed"):
        assert any(x.startswith(part) for x in out), part
    assert sum(x.startswith("    ") for x in out) <= len(finder_rules(db, entity_id)) + 1 + 2 * (
        finder.SHOWN + 1
    )


def finder_rules(db: Session, entity_id: int) -> list[fx_rules.Rule]:
    return [fx_rules.BOOK, *fx_rules.rules(fx_rules.Rates(db, entity_id))]


def test_a_company_without_foreign_ledgers_has_nothing_to_find() -> None:
    out = finder.lines("entity 2", fx_rules.Finding(dates=42))
    assert out[-1] == "entity 2: no foreign-currency ledgers: nothing to find"
    assert len(out) == 2


def test_the_command_needs_stored_statements(db: Session, run_cli) -> None:  # noqa: ANN001, F811
    run_cli("connect", "--connection", "tally-pilot", "--source", "tally", "--origin", "backup",
            "--all")  # fmt: skip
    run_cli("sync", "--connection", "tally-pilot", "--full", "--no-validate")
    code, out = run_cli("fx-rules", "--connection", "tally-pilot")
    assert code == 2
    assert "no statements stored yet; run ./dev.ps1 statements first" in out
    assert "Result: fx-rules finished" in out
