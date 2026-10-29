"""Monthly sales: the source's predefined group identity and the sales views (RPT-013).

`account_groups.predefined_role` keeps which of the source's own predefined groups a group
is, renamed or not (e.g. "sales_accounts"). The views count every effective entry on the
ledgers under the Sales Accounts group and its sub-groups, by voucher date, signed as an
accountant reads them (sales positive, returns negative), so that net sales equals the
source's own Sales Accounts figure:

- `v_sales_ledgers`: each ledger under an entity's Sales Accounts group (any depth);
- `v_daily_sales`: per entity, date and voucher type: gross sales (sales vouchers), sales
  returns (credit notes), other adjustments (every other voucher type) and net sales;
- `v_monthly_sales`: per entity and month, summed from the daily view, with the financial
  year (its starting calendar year, from the entity's financial-year start month);
- `v_monthly_sales_by_voucher_type`: per entity, month and voucher type, the same net.

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCOUNTING = "ledgerbridge_accounting"

# Complete statements (no SQL built from strings).
CREATE_SALES_LEDGERS = """CREATE VIEW ledgerbridge_reporting.v_sales_ledgers AS
    WITH RECURSIVE sales_groups (entity_id, group_id, sales_group_id, depth) AS (
        SELECT g.entity_id, g.id, g.id, 0
        FROM ledgerbridge_accounting.account_groups AS g
        WHERE g.predefined_role = 'sales_accounts'
        UNION ALL
        SELECT c.entity_id, c.id, s.sales_group_id, s.depth + 1
        FROM ledgerbridge_accounting.account_groups AS c
        JOIN sales_groups AS s ON c.parent_id = s.group_id
        WHERE s.depth < 64
    )
    SELECT l.entity_id, l.id AS ledger_id, l.group_id, s.sales_group_id
    FROM ledgerbridge_accounting.ledgers AS l
    JOIN sales_groups AS s ON s.group_id = l.group_id"""

CREATE_DAILY = """CREATE VIEW ledgerbridge_reporting.v_daily_sales AS
    SELECT v.entity_id, v.voucher_date AS on_date, v.voucher_type_id,
           vt.name AS voucher_type, vt.base_type,
           SUM(CASE WHEN vt.base_type = 'sales' THEN -vl.amount ELSE 0 END) AS gross_sales,
           SUM(CASE WHEN vt.base_type = 'credit_note' THEN -vl.amount ELSE 0 END)
               AS sales_returns,
           SUM(CASE WHEN vt.base_type IN ('sales', 'credit_note') THEN 0 ELSE -vl.amount END)
               AS other_adjustments,
           -SUM(vl.amount) AS net_sales,
           COUNT(DISTINCT v.id) AS vouchers
    FROM ledgerbridge_accounting.voucher_lines AS vl
    JOIN ledgerbridge_accounting.vouchers AS v ON v.id = vl.voucher_id
    JOIN ledgerbridge_reporting.v_sales_ledgers AS s ON s.ledger_id = vl.ledger_id
    JOIN ledgerbridge_accounting.voucher_types AS vt ON vt.id = v.voucher_type_id
    WHERE vl.is_effective = 1 AND v.is_deleted = 0
    GROUP BY v.entity_id, v.voucher_date, v.voucher_type_id, vt.name, vt.base_type"""

CREATE_MONTHLY = """CREATE VIEW ledgerbridge_reporting.v_monthly_sales AS
    SELECT d.entity_id,
           YEAR(d.on_date) - (MONTH(d.on_date) < e.fy_start_month) AS financial_year,
           MOD(MONTH(d.on_date) - e.fy_start_month + 12, 12) + 1 AS month_of_year,
           CAST(DATE_FORMAT(d.on_date, '%Y-%m-01') AS DATE) AS month_start,
           DATE_FORMAT(d.on_date, '%b-%y') AS month_label,
           SUM(d.gross_sales) AS gross_sales,
           SUM(d.sales_returns) AS sales_returns,
           SUM(d.other_adjustments) AS other_adjustments,
           SUM(d.net_sales) AS net_sales,
           SUM(d.vouchers) AS vouchers
    FROM ledgerbridge_reporting.v_daily_sales AS d
    JOIN ledgerbridge_accounting.entities AS e ON e.id = d.entity_id
    GROUP BY d.entity_id, financial_year, month_of_year, month_start, month_label"""

CREATE_BY_VOUCHER_TYPE = """CREATE VIEW ledgerbridge_reporting.v_monthly_sales_by_voucher_type AS
    SELECT d.entity_id,
           YEAR(d.on_date) - (MONTH(d.on_date) < e.fy_start_month) AS financial_year,
           MOD(MONTH(d.on_date) - e.fy_start_month + 12, 12) + 1 AS month_of_year,
           CAST(DATE_FORMAT(d.on_date, '%Y-%m-01') AS DATE) AS month_start,
           DATE_FORMAT(d.on_date, '%b-%y') AS month_label,
           d.voucher_type_id, d.voucher_type, d.base_type,
           SUM(d.net_sales) AS net_sales,
           SUM(d.vouchers) AS vouchers
    FROM ledgerbridge_reporting.v_daily_sales AS d
    JOIN ledgerbridge_accounting.entities AS e ON e.id = d.entity_id
    GROUP BY d.entity_id, financial_year, month_of_year, month_start, month_label,
             d.voucher_type_id, d.voucher_type, d.base_type"""

VIEWS = (CREATE_SALES_LEDGERS, CREATE_DAILY, CREATE_MONTHLY, CREATE_BY_VOUCHER_TYPE)
DROP_VIEWS = (  # the dependent views first
    "DROP VIEW IF EXISTS ledgerbridge_reporting.v_monthly_sales_by_voucher_type",
    "DROP VIEW IF EXISTS ledgerbridge_reporting.v_monthly_sales",
    "DROP VIEW IF EXISTS ledgerbridge_reporting.v_daily_sales",
    "DROP VIEW IF EXISTS ledgerbridge_reporting.v_sales_ledgers",
)


def upgrade() -> None:
    op.add_column(
        "account_groups",
        sa.Column("predefined_role", sa.String(64), nullable=True),
        schema=ACCOUNTING,
    )
    for create in VIEWS:
        op.execute(create)


def downgrade() -> None:
    for drop in DROP_VIEWS:
        op.execute(drop)
    op.drop_column("account_groups", "predefined_role", schema=ACCOUNTING)
