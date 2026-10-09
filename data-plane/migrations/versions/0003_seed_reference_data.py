"""M2: reference data. The INR currency and the default standard chart of accounts.

The standard chart (schema.md Section 4.2) is the common structure that every entity's
source ledgers are mapped to for consolidated reporting (RPT-006, CON-011). It follows the
Schedule III layout used in India and is editable per client.

cash_flow_class (indirect method): balance-sheet accounts say where their movement belongs.
Profit and loss accounts are `none`, because profit is the starting point of the indirect
method. Accumulated depreciation is `operating`, so its movement adds depreciation back.

Notes on specific accounts are kept next to them below and in schema.md Section 4.2
(suspense, inter-company and branch accounts, changes in inventories).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-09
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCOUNTING = "ledgerbridge_accounting"

BS, PL = "balance_sheet", "profit_loss"

# (code, parent_code, name, nature, statement, statement_line, cash_flow_class)
STANDARD_ACCOUNTS: list[tuple[str, str | None, str, str, str, str, str]] = [
    # --- Assets ---------------------------------------------------------------------
    ("1000", None, "Assets", "asset", BS, "assets", "none"),
    ("1100", "1000", "Non-current assets", "asset", BS, "non_current_assets", "investing"),
    ("1110", "1100", "Property, plant and equipment", "asset", BS, "non_current_assets", "investing"),
    ("1120", "1100", "Accumulated depreciation", "asset", BS, "non_current_assets", "operating"),
    ("1130", "1100", "Intangible assets", "asset", BS, "non_current_assets", "investing"),
    ("1140", "1100", "Capital work in progress", "asset", BS, "non_current_assets", "investing"),
    ("1150", "1100", "Non-current investments", "asset", BS, "non_current_assets", "investing"),
    ("1160", "1100", "Long-term loans and advances", "asset", BS, "non_current_assets", "investing"),
    ("1170", "1100", "Deferred tax assets", "asset", BS, "non_current_assets", "operating"),
    ("1200", "1000", "Current assets", "asset", BS, "current_assets", "operating"),
    ("1210", "1200", "Inventories", "asset", BS, "current_assets", "operating"),
    ("1220", "1200", "Trade receivables", "asset", BS, "current_assets", "operating"),
    ("1230", "1200", "Cash and cash equivalents", "asset", BS, "cash_and_equivalents", "cash"),
    ("1231", "1230", "Cash in hand", "asset", BS, "cash_and_equivalents", "cash"),
    ("1232", "1230", "Balances with banks", "asset", BS, "cash_and_equivalents", "cash"),
    ("1240", "1200", "Short-term loans and advances", "asset", BS, "current_assets", "operating"),
    ("1250", "1200", "GST input tax credit", "asset", BS, "current_assets", "operating"),
    ("1260", "1200", "TDS receivable and advance tax", "asset", BS, "current_assets", "operating"),
    ("1270", "1200", "Other current assets", "asset", BS, "current_assets", "operating"),
    # Eliminated in consolidated reporting (M6). Tally's Branch / Divisions group maps here
    # (debit balances) and to 3275 (credit balances).
    ("1275", "1200", "Inter-company and branch receivables", "asset", BS, "current_assets", "operating"),
    ("1280", "1200", "Current investments", "asset", BS, "current_assets", "investing"),
    # --- Equity ---------------------------------------------------------------------
    ("2000", None, "Equity", "equity", BS, "equity", "none"),
    ("2100", "2000", "Share capital / Capital account", "equity", BS, "equity", "financing"),
    ("2200", "2000", "Reserves and surplus", "equity", BS, "equity", "none"),
    ("2300", "2000", "Drawings", "equity", BS, "equity", "financing"),
    # --- Liabilities ----------------------------------------------------------------
    ("3000", None, "Liabilities", "liability", BS, "liabilities", "none"),
    ("3100", "3000", "Non-current liabilities", "liability", BS, "non_current_liabilities", "financing"),
    ("3110", "3100", "Long-term borrowings", "liability", BS, "non_current_liabilities", "financing"),
    ("3120", "3100", "Deferred tax liabilities", "liability", BS, "non_current_liabilities", "operating"),
    ("3130", "3100", "Long-term provisions", "liability", BS, "non_current_liabilities", "operating"),
    ("3200", "3000", "Current liabilities", "liability", BS, "current_liabilities", "operating"),
    ("3210", "3200", "Short-term borrowings", "liability", BS, "current_liabilities", "financing"),
    ("3220", "3200", "Trade payables", "liability", BS, "current_liabilities", "operating"),
    ("3230", "3200", "GST payable", "liability", BS, "current_liabilities", "operating"),
    ("3240", "3200", "TDS and TCS payable", "liability", BS, "current_liabilities", "operating"),
    ("3250", "3200", "Other statutory dues (PF, ESI, professional tax)", "liability", BS, "current_liabilities", "operating"),
    ("3260", "3200", "Salaries and employee benefits payable", "liability", BS, "current_liabilities", "operating"),
    ("3270", "3200", "Other current liabilities", "liability", BS, "current_liabilities", "operating"),
    # Eliminated in consolidated reporting (M6); see 1275.
    ("3275", "3200", "Inter-company and branch payables", "liability", BS, "current_liabilities", "operating"),
    ("3280", "3200", "Short-term provisions (incl. income tax)", "liability", BS, "current_liabilities", "operating"),
    # Balance can be debit or credit. Tally's built-in Suspense A/c group maps here.
    ("3290", "3200", "Suspense / unclassified", "liability", BS, "current_liabilities", "operating"),
    # --- Income ---------------------------------------------------------------------
    ("4000", None, "Income", "income", PL, "income", "none"),
    ("4100", "4000", "Revenue from operations", "income", PL, "revenue", "none"),
    ("4110", "4100", "Sale of goods", "income", PL, "revenue", "none"),
    ("4120", "4100", "Sale of services", "income", PL, "revenue", "none"),
    ("4130", "4100", "Other operating revenue", "income", PL, "revenue", "none"),
    ("4200", "4000", "Other income", "income", PL, "other_income", "none"),
    ("4210", "4200", "Interest income", "income", PL, "other_income", "none"),
    ("4220", "4200", "Other non-operating income", "income", PL, "other_income", "none"),
    # --- Expenses -------------------------------------------------------------------
    ("5000", None, "Expenses", "expense", PL, "expenses", "none"),
    ("5100", "5000", "Cost of materials and goods sold", "expense", PL, "cogs", "none"),
    ("5110", "5100", "Purchases (materials and stock-in-trade)", "expense", PL, "cogs", "none"),
    # Not mapped from ledgers: derived in the reporting layer (M6) from opening and closing
    # stock valuation.
    ("5120", "5100", "Changes in inventories", "expense", PL, "cogs", "none"),
    ("5130", "5100", "Direct expenses", "expense", PL, "cogs", "none"),
    ("5200", "5000", "Employee benefit expenses", "expense", PL, "employee_costs", "none"),
    ("5210", "5200", "Salaries and wages", "expense", PL, "employee_costs", "none"),
    ("5220", "5200", "Contribution to PF, ESI and other funds", "expense", PL, "employee_costs", "none"),
    ("5230", "5200", "Staff welfare", "expense", PL, "employee_costs", "none"),
    ("5300", "5000", "Finance costs", "expense", PL, "finance_costs", "none"),
    ("5310", "5300", "Interest expense", "expense", PL, "finance_costs", "none"),
    ("5320", "5300", "Bank charges", "expense", PL, "finance_costs", "none"),
    ("5400", "5000", "Depreciation and amortisation", "expense", PL, "depreciation", "none"),
    ("5500", "5000", "Other expenses", "expense", PL, "other_expenses", "none"),
    ("5510", "5500", "Rent", "expense", PL, "other_expenses", "none"),
    ("5520", "5500", "Power and fuel", "expense", PL, "other_expenses", "none"),
    ("5530", "5500", "Repairs and maintenance", "expense", PL, "other_expenses", "none"),
    ("5540", "5500", "Travelling and conveyance", "expense", PL, "other_expenses", "none"),
    ("5550", "5500", "Communication", "expense", PL, "other_expenses", "none"),
    ("5560", "5500", "Legal and professional fees", "expense", PL, "other_expenses", "none"),
    ("5570", "5500", "Office and administrative expenses", "expense", PL, "other_expenses", "none"),
    ("5580", "5500", "Advertising and marketing", "expense", PL, "other_expenses", "none"),
    ("5590", "5500", "Miscellaneous expenses", "expense", PL, "other_expenses", "none"),
    ("5600", "5000", "Tax expense", "expense", PL, "tax_expense", "none"),
    ("5610", "5600", "Current tax", "expense", PL, "tax_expense", "none"),
    ("5620", "5600", "Deferred tax", "expense", PL, "tax_expense", "none"),
]  # fmt: skip


def upgrade() -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    bind = op.get_bind()
    bind.execute(
        sa.text(
            f"INSERT INTO {ACCOUNTING}.currencies (code, name, decimal_places, created_at, updated_at) "
            "VALUES ('INR', 'Indian Rupee', 2, :now, :now)"
        ),
        {"now": now},
    )
    ids: dict[str, int] = {}
    for sort_order, (code, parent, name, nature, statement, line, cash_flow) in enumerate(
        STANDARD_ACCOUNTS, start=1
    ):
        result = bind.execute(
            sa.text(
                f"INSERT INTO {ACCOUNTING}.standard_accounts (parent_id, code, name, nature, "
                "statement, statement_line, cash_flow_class, sort_order, created_at, updated_at) "
                "VALUES (:parent_id, :code, :name, :nature, :statement, :line, :cash_flow, "
                ":sort_order, :now, :now)"
            ),
            {
                "parent_id": ids[parent] if parent else None,
                "code": code,
                "name": name,
                "nature": nature,
                "statement": statement,
                "line": line,
                "cash_flow": cash_flow,
                "sort_order": sort_order * 10,
                "now": now,
            },
        )
        ids[code] = result.lastrowid


def downgrade() -> None:
    bind = op.get_bind()
    # Children before parents.
    for code, *_ in reversed(STANDARD_ACCOUNTS):
        bind.execute(
            sa.text(f"DELETE FROM {ACCOUNTING}.standard_accounts WHERE code = :code"),
            {"code": code},
        )
    bind.execute(sa.text(f"DELETE FROM {ACCOUNTING}.currencies WHERE code = 'INR'"))
