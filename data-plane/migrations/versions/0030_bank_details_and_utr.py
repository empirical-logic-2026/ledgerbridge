"""Bank details and the UTR on voucher lines (data completion, part 1).

- `voucher_lines.tally_bank_entry_id`: the source's own id for a bank entry (Tally's
  UNIQUEREFERENCENUMBER, a code it generates), which `transaction_reference` held until now;
  moved there and never shown as a UTR.
- `voucher_lines.transaction_reference` renamed `utr`: only a value that looks like a bank's
  transaction reference (core/utr.py), emptied here (the next transform or full re-fetch
  fills it); `utr_source`: bank_field, udf or narration.
- `transaction_type`, `instrument_date`, `bank_cleared_date` (Tally's BANKERSDATE),
  `bank_recon_status`.

Revision ID: 0030
Revises: 0029
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCOUNTING = "ledgerbridge_accounting"
TEXT = sa.String(255)
NEW = (
    ("tally_bank_entry_id", TEXT),
    ("utr_source", sa.String(16)),
    ("transaction_type", sa.String(64)),
    ("instrument_date", sa.Date()),
    ("bank_cleared_date", sa.Date()),
    ("bank_recon_status", sa.String(64)),
)


def upgrade() -> None:
    for name, kind in NEW:
        op.add_column("voucher_lines", sa.Column(name, kind, nullable=True), schema=ACCOUNTING)
    op.execute(
        f"UPDATE {ACCOUNTING}.voucher_lines SET tally_bank_entry_id = transaction_reference, "
        "transaction_reference = NULL WHERE transaction_reference IS NOT NULL"
    )
    op.alter_column(
        "voucher_lines",
        "transaction_reference",
        new_column_name="utr",
        existing_type=TEXT,
        existing_nullable=True,
        schema=ACCOUNTING,
    )


def downgrade() -> None:
    op.alter_column(
        "voucher_lines",
        "utr",
        new_column_name="transaction_reference",
        existing_type=TEXT,
        existing_nullable=True,
        schema=ACCOUNTING,
    )
    op.execute(
        f"UPDATE {ACCOUNTING}.voucher_lines SET transaction_reference = tally_bank_entry_id "
        "WHERE tally_bank_entry_id IS NOT NULL"
    )
    for name, _ in reversed(NEW):
        op.drop_column("voucher_lines", name, schema=ACCOUNTING)
