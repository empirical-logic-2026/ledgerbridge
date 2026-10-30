"""`validate currencies` (workers/currencies.py): each company's ledgers by their own
currency, counts and ISO codes only. On the test company's year-end books made foreign
(tests/test_fx_core.py) with Tally's statements stored (tests/test_fx_rules.py)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import fx
from core.models import accounting as A  # noqa: N812
from core.models import system as S  # noqa: N812
from tests.test_fx_core import foreign_books  # noqa: F401 - the fixture
from tests.test_fx_rules import _stored
from workers import currencies


def test_the_ledgers_by_their_own_currency(
    db: Session,
    foreign_books: S.Connection,  # noqa: F811 - the fixture
) -> None:
    entity_id, _ = _stored(db, foreign_books)
    out = currencies.lines(db, entity_id, "entity 1 (company 1)")
    assert out[0] == (
        "entity 1 (company 1): 1 currency masters (1 with an ISO code: USD; 0 without); "
        "base currency INR found as most ledgers' currency"
    )
    assert out[1].endswith("kept in another currency than the base one: 2 (USD 2)")
    # Hotel is kept in rupees but holds dollars (its opening); the two dollar ledgers too.
    assert out[2] == (
        "  ledgers holding foreign amounts: 2 (1 kept in another currency, "
        "1 kept in the base currency)"
    )
    assert out[3].startswith("  ledgers the source revalues (as of 2026-10-02): 2, 2 of them")
    assert out[3].endswith("(OK)")
    text = "\n".join(out)
    names = set(db.scalars(select(A.Ledger.name)))
    assert not [n for n in names if n in text]


def test_ledgers_the_source_revalues_but_not_marked_foreign_are_warned_about(
    db: Session,
    foreign_books: S.Connection,  # noqa: F811 - the fixture
) -> None:
    entity_id, _ = _stored(db, foreign_books)
    for master in db.scalars(select(A.CurrencySource)):
        master.currency_code = None
    for ledger in db.scalars(select(A.Ledger).where(A.Ledger.is_foreign_currency)):
        ledger.currency_name = "?"  # as if its currency weren't recorded
    db.commit()
    fx.refresh_ledger_currencies(db, entity_id)
    out = currencies.lines(db, entity_id, "entity 1 (company 1)")
    assert "0 with an ISO code" in out[0]
    assert out[-1].endswith(
        "[Ledgers the source revalues not marked foreign [revalued_ledger_not_foreign, "
        "LB-VAL-035]: 2]"
    )
