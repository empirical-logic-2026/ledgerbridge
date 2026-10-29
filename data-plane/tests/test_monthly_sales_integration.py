"""The monthly sales views on MySQL (RPT-013, migration 0021): the recorded test-company
fixtures synced, then `v_daily_sales` against the same definition computed here, the
classification (gross sales, returns, other adjustments), a ledger in a sub-group, and the
monthly and by-voucher-type views adding up to the same net (./dev.ps1 up, or only the test
MySQL with migrations applied)."""

import re
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from connectors.tally.connector import TallyConnector
from connectors.tally.fixtures import DEFAULT_DIR, FixtureTransport
from core import monthly_sales
from core.db import get_engine
from core.models import accounting as A  # noqa: N812
from tests.test_migrations_integration import _config
from tests.test_sync_integration import CONNECTION, _cleanup
from workers.extract import get_or_create_connection
from workers.sync import run_sync

pytestmark = pytest.mark.integration
SQL_FILE = Path(__file__).resolve().parents[2] / "docs" / "sql" / "monthly-sales.sql"


def _run_sql_file(session: Session, entity_id: int, fy: int) -> list[list[tuple]]:
    """docs/sql/monthly-sales.sql as an accountant runs it, with @entity and @fy set: the
    rows of each statement that returns some (the report, by voucher type, the days)."""
    script = SQL_FILE.read_text(encoding="utf-8")
    script = re.sub(r"(?m)^SET @entity = \d+;", f"SET @entity = {entity_id};", script)
    script = re.sub(r"(?m)^SET @fy = \d+;", f"SET @fy = {fy};", script)
    lines = (re.sub(r"\s+--\s.*$", "", x) for x in script.splitlines())
    body = "\n".join(x for x in lines if x.strip() and not x.lstrip().startswith("--"))
    results = []
    # The driver's own cursor without arguments, as Workbench sends it ("%b" isn't a
    # parameter then).
    cursor = session.connection().connection.cursor()
    for statement in (s.strip() for s in body.split(";\n")):
        if statement:
            cursor.execute(statement.rstrip(";"))
            if cursor.description:
                results.append([tuple(r) for r in cursor.fetchall()])
    return results


def _monthly(session: Session, entity_id: int) -> dict[object, tuple[Decimal, ...]]:
    rows = session.execute(
        text(
            "SELECT month_start, gross_sales, sales_returns, other_adjustments, net_sales "
            "FROM ledgerbridge_reporting.v_monthly_sales WHERE entity_id = :e"
        ),
        {"e": entity_id},
    )
    return {r[0]: tuple(Decimal(str(x)) for x in r[1:]) for r in rows}


def _by_type(session: Session, entity_id: int) -> dict[object, Decimal]:
    rows = session.execute(
        text(
            "SELECT month_start, SUM(net_sales) "
            "FROM ledgerbridge_reporting.v_monthly_sales_by_voucher_type "
            "WHERE entity_id = :e GROUP BY month_start"
        ),
        {"e": entity_id},
    )
    return {r[0]: Decimal(str(r[1])) for r in rows}


def _year(session: Session, entity_id: int, month: object) -> int:
    return session.scalar(
        text(
            "SELECT financial_year FROM ledgerbridge_reporting.v_monthly_sales "
            "WHERE entity_id = :e AND month_start = :m"
        ),
        {"e": entity_id, "m": month},
    )


def test_the_sales_views_on_mysql(monkeypatch: pytest.MonkeyPatch) -> None:
    if not (DEFAULT_DIR / "manifest.json").exists():
        pytest.skip("no recorded fixtures")
    command.upgrade(_config(), "head")
    monkeypatch.setattr(
        "connectors.registry.default_config", lambda code: {"url": "http://tally.test:9000"}
    )
    connector = TallyConnector.from_config(
        {"url": "http://tally.test:9000"}, transport=FixtureTransport(DEFAULT_DIR)
    )
    with Session(get_engine()) as session:
        _cleanup(session)
        try:
            connection = get_or_create_connection(session, CONNECTION, "tally")
            session.commit()
            assert run_sync(session, connection, connector).status == "succeeded"
            entity_id = session.scalar(
                select(A.EntitySource.entity_id).where(
                    A.EntitySource.connection_id == connection.id
                )
            )
            group = monthly_sales.sales_group(session, entity_id)
            assert group.found and group.ledgers  # by the source's own predefined group

            # The view equals the definition computed here, day by day.
            view = monthly_sales.daily_from_view(session, entity_id)
            assert view and view == monthly_sales.daily_from_books(session, entity_id)
            monthly = _monthly(session, entity_id)
            for gross, returns, other, net in monthly.values():
                assert gross + returns + other == net
            assert _by_type(session, entity_id) == {m: v[3] for m, v in monthly.items()}
            assert sum(v[3] for v in monthly.values()) == sum(view.values())

            # docs/sql/monthly-sales.sql: the rows, a column per month, and the totals.
            fy = session.scalar(
                text(
                    "SELECT MIN(financial_year) FROM ledgerbridge_reporting.v_monthly_sales "
                    "WHERE entity_id = :e"
                ),
                {"e": entity_id},
            )
            report, by_type, days = _run_sql_file(session, entity_id, fy)
            assert [r[0] for r in report] == [
                "Gross Sales", "Sales Returns", "Other Adjustments", "Net Sales",
            ]  # fmt: skip
            assert all(len(r) == 14 for r in report)  # line, 12 months, Total
            in_year = [v for (m, v) in monthly.items() if _year(session, entity_id, m) == fy]
            assert Decimal(report[3][13]) == sum(v[3] for v in in_year)
            assert sum(Decimal(r[-1]) for r in by_type) == Decimal(report[3][13])
            assert len(days) == 1

            # A sales voucher made a journal: its entries move from gross sales to other
            # adjustments; net sales stay the same.
            journal = session.scalars(
                select(A.VoucherType).where(
                    A.VoucherType.entity_id == entity_id, A.VoucherType.base_type == "journal"
                )
            ).first()
            sale = session.scalars(
                select(A.Voucher)
                .join(A.VoucherType, A.VoucherType.id == A.Voucher.voucher_type_id)
                .join(A.VoucherLine, A.VoucherLine.voucher_id == A.Voucher.id)
                .where(
                    A.Voucher.entity_id == entity_id,
                    A.VoucherType.base_type == "sales",
                    A.VoucherLine.ledger_id.in_(group.ledgers),
                    A.VoucherLine.is_effective.is_(True),
                )
            ).first()
            month = sale.voucher_date.replace(day=1)
            before = monthly[month]
            sale.voucher_type_id = journal.id
            session.commit()
            after = _monthly(session, entity_id)[month]
            moved = before[0] - after[0]
            assert moved and after[2] - before[2] == moved and after[3] == before[3]

            # A ledger moved into a new sub-group of Sales Accounts still counts.
            top = session.scalars(
                select(A.AccountGroup).where(
                    A.AccountGroup.entity_id == entity_id,
                    A.AccountGroup.predefined_role == monthly_sales.SALES_ROLE,
                )
            ).one()
            sub = A.AccountGroup(
                entity_id=entity_id, parent_id=top.id, name="Online Sales IT",
                connection_id=connection.id, source_key="it-sub-group", origin="live",
            )  # fmt: skip
            session.add(sub)
            session.flush()
            session.get(A.Ledger, min(group.ledgers)).group_id = sub.id
            session.commit()
            assert monthly_sales.daily_from_view(session, entity_id) == view
        finally:
            _cleanup(session)
