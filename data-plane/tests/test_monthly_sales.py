"""Monthly sales proven against the source (RPT-013, core/monthly_sales.py,
workers/monthly_sales.py). The proof on the test company's year-end books with Tally's own
recorded Profit and Loss at six dates (as tests/test_fx_rules.py stores them); the windows,
the source's predefined group, the cross-checks and the refusal. The views themselves run on
MySQL: tests/test_monthly_sales_integration.py."""

import xml.etree.ElementTree as ET  # noqa: N817
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from connectors.tally import mapping
from core import monthly_sales
from core.models import accounting as A  # noqa: N812
from core.models import system as S  # noqa: N812
from core.models.base import utcnow
from core.monthly_sales import Window, windows
from tests.test_fx_core import foreign_books  # noqa: F401 - the fixture
from tests.test_fx_rules import DATES, _stored
from workers import monthly_sales as worker

BOOKS_FROM = date(2025, 4, 1)


def _run(db: Session, entity_id: int) -> tuple[int, list[str]]:
    out: list[str] = []
    code = worker.run(
        db, [(entity_id, "entity 1 (company 1)")], out.append, monthly_sales.daily_from_books
    )
    return code, out


def test_the_source_predefined_group_is_kept_renamed_or_not() -> None:
    def role(xml: str) -> str | None:
        return mapping.group(ET.fromstring(xml), "k").predefined_role

    assert role('<GROUP NAME="Sales Accounts" RESERVEDNAME="Sales Accounts">'
                "<PARENT></PARENT></GROUP>") == "sales_accounts"  # fmt: skip
    assert role('<GROUP NAME="Revenue" RESERVEDNAME="Sales Accounts">'
                "<PARENT></PARENT></GROUP>") == "sales_accounts"  # renamed  # fmt: skip
    assert role('<GROUP NAME="Loans &amp; Advances (Asset)" '
                'RESERVEDNAME="Loans &amp; Advances (Asset)"><PARENT>Current Assets</PARENT>'
                "</GROUP>") == "loans_advances_asset"  # fmt: skip
    assert role('<GROUP NAME="Online Sales"><PARENT>Sales Accounts</PARENT></GROUP>') is None


def test_windows_cover_every_day_once() -> None:
    """Educational mode: a 30-day month ends on the 2nd of the next month, so July's window
    starts on the 3rd; August then is an exact calendar month."""
    dates = [date(2026, 5, 31), date(2026, 7, 2), date(2026, 7, 31), date(2026, 8, 31)]
    found = windows(date(2026, 5, 1), dates)
    assert found == [
        Window(date(2026, 5, 1), date(2026, 5, 31)),
        Window(date(2026, 6, 1), date(2026, 7, 2)),
        Window(date(2026, 7, 3), date(2026, 7, 31)),
        Window(date(2026, 8, 1), date(2026, 8, 31)),
    ]
    assert [w.exact_month for w in found] == [True, False, False, True]
    days = sum((w.end - w.start).days + 1 for w in found)
    assert days == (date(2026, 8, 31) - date(2026, 5, 1)).days + 1
    assert windows(date(2026, 3, 1), [date(2026, 2, 28), date(2026, 3, 31)]) == [
        Window(date(2026, 3, 1), date(2026, 3, 31))  # a date before the books is skipped
    ]
    assert Window(date(2026, 2, 1), date(2026, 2, 28)).exact_month
    assert not Window(date(2026, 2, 1), date(2026, 3, 2)).exact_month


def test_net_sales_equal_the_source_between_every_stored_date(
    db: Session,
    foreign_books: S.Connection,  # noqa: F811 - the fixture
) -> None:
    """The proof on the test company: every window from the books' beginning to the last
    stored date equals Tally's own Sales Accounts figure; a changed entry is found."""
    entity_id, _ = _stored(db, foreign_books)
    group = monthly_sales.sales_group(db, entity_id)
    assert group.found and group.ledgers and group.outside == 0
    code, out = _run(db, entity_id)
    assert code == 0, out
    assert out[-1] == (
        f"entity 1 (company 1): {len(DATES)} periods compared from {BOOKS_FROM} to "
        f"{max(DATES)} (0 of them exact calendar months; {len(DATES)} stored dates), 0 differ (OK)"
    )
    assert "cross-check: no ledger mapped to sale of goods (4110) outside it (OK)" in out[1]

    line = db.scalars(
        select(A.VoucherLine)
        .join(A.Voucher, A.Voucher.id == A.VoucherLine.voucher_id)
        .where(A.VoucherLine.ledger_id.in_(group.ledgers), A.VoucherLine.is_effective)
        .order_by(A.Voucher.voucher_date)
    ).first()
    line.amount -= Decimal(1)
    db.commit()
    code, out = _run(db, entity_id)
    assert code == 1
    assert (
        "1 differ [Monthly sales differ from the source [monthly_sales_mismatch, LB-VAL-029]]"
        in out[-2]
    )
    assert out[-1].startswith("  differs: ")


def test_the_output_names_no_ledger_or_group(
    db: Session,
    foreign_books: S.Connection,  # noqa: F811 - the fixture
) -> None:
    entity_id, _ = _stored(db, foreign_books)
    _, out = _run(db, entity_id)
    text = "\n".join(out)
    names = set(db.scalars(select(A.Ledger.name))) | set(db.scalars(select(A.AccountGroup.name)))
    assert not [n for n in names if n in text and n not in ("Primary", "Sales Accounts")]


def test_a_missing_group_and_sales_ledgers_outside_it_are_warned_about(
    db: Session,
    foreign_books: S.Connection,  # noqa: F811 - the fixture
) -> None:
    """Never silently left out: a sales ledger moved under another group (still mapped to
    sale of goods) is counted as outside; without the predefined group nothing is compared."""
    entity_id, _ = _stored(db, foreign_books)
    group = monthly_sales.sales_group(db, entity_id)
    moved = db.get(A.Ledger, min(group.ledgers))
    other = db.scalars(
        select(A.AccountGroup).where(
            A.AccountGroup.entity_id == entity_id,
            A.AccountGroup.predefined_role == "direct_incomes",
        )
    ).one()
    moved.group_id = other.id
    db.commit()
    _, out = _run(db, entity_id)
    assert any(
        "1 ledgers mapped to sale of goods (4110) with entries sit outside it" in x for x in out
    )

    for g in db.scalars(
        select(A.AccountGroup).where(A.AccountGroup.predefined_role == "sales_accounts")
    ):
        g.predefined_role = None
    db.commit()
    code, out = _run(db, entity_id)
    assert code == 1
    assert "Sales Accounts group wasn't found" in out[0] and "LB-VAL-030" in out[0]


def test_statements_older_than_the_last_sync_are_refused(
    db: Session,
    foreign_books: S.Connection,  # noqa: F811 - the fixture
) -> None:
    entity_id, _ = _stored(db, foreign_books)
    later = utcnow() + timedelta(minutes=5)
    db.add(S.SyncRun(connection_id=foreign_books.id, run_type="incremental", status="succeeded",
                     started_at=later, finished_at=later))  # fmt: skip
    db.commit()
    code, out = _run(db, entity_id)
    assert code == 2
    assert "refused: the stored statements" in out[0]
    assert (
        "[Stored statements older than the data [statements_older_than_data, LB-VAL-032]]" in out[0]
    )
    assert out[0].endswith("run ./dev.ps1 statements first")


def test_no_statements_stored_is_said(db: Session, foreign_books: S.Connection) -> None:  # noqa: F811
    from tests.test_fx_rules import BOOKS, FixtureTransport, TallyConnector, Transformer

    connector = TallyConnector.from_config(
        {"url": "http://tally.test:9000"}, transport=FixtureTransport(BOOKS)
    )
    Transformer(db, foreign_books.id, connector).run(rebuild=True)
    entity_id = db.scalars(select(A.Entity.id)).one()
    code, out = _run(db, entity_id)
    assert code == 2
    assert (
        out[-1] == "entity 1 (company 1): no statements stored yet; run ./dev.ps1 statements first"
    )
