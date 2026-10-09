"""`ledgerbridge_accounting`: the canonical, source-independent accounting model
(schema.md Section 4; types per Section 9).

Sign convention: debit positive, credit negative (schema.md Section 1).
Voucher child tables cascade on delete: a changed voucher's children are replaced as a
whole in one transaction (schema.md Section 8, rule 7).
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import CHAR, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import (
    Base,
    FxRate,
    Id,
    Money,
    Rate,
    SmallInt,
    SourceTrackingMixin,
    TimestampMixin,
    TinyInt,
    flag,
    name_column,
    src_table_args,
)
from core.models.schemas import ACCOUNTING, SYSTEM

NATURES = ("asset", "liability", "equity", "income", "expense")
_A = {"schema": ACCOUNTING}


def _fk(table: str, ondelete: str | None = None) -> ForeignKey:
    return ForeignKey(f"{ACCOUNTING}.{table}.id", ondelete=ondelete)


# --- 4.1 Organization ------------------------------------------------------------------


class Entity(TimestampMixin, Base):
    __tablename__ = "entities"
    __table_args__ = _A

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = name_column()
    legal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    country_code: Mapped[str] = mapped_column(CHAR(2), default="IN", server_default="IN")
    state_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    gstin: Mapped[str | None] = mapped_column(String(15), nullable=True)
    pan: Mapped[str | None] = mapped_column(String(10), nullable=True)
    base_currency_code: Mapped[str] = mapped_column(
        CHAR(3), ForeignKey(f"{ACCOUNTING}.currencies.code"), default="INR", server_default="INR"
    )
    fy_start_month: Mapped[int] = mapped_column(TinyInt, default=4, server_default="4")
    books_from: Mapped[date | None] = mapped_column(nullable=True)
    is_active: Mapped[bool] = flag(True)


class EntitySource(TimestampMixin, Base):
    """Links a source company (e.g. a Tally company) to an entity."""

    __tablename__ = "entity_sources"
    __table_args__ = (
        UniqueConstraint("connection_id", "source_entity_key", name="uq_entity_sources_source"),
        _A,
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    connection_id: Mapped[int] = mapped_column(Id, ForeignKey(f"{SYSTEM}.connections.id"))
    source_entity_key: Mapped[str] = mapped_column(String(191))
    source_entity_name: Mapped[str] = name_column()
    precedence: Mapped[int] = mapped_column(SmallInt, default=0, server_default="0")
    active_from: Mapped[date | None] = mapped_column(nullable=True)
    active_to: Mapped[date | None] = mapped_column(nullable=True)


class Branch(TimestampMixin, Base):
    __tablename__ = "branches"
    __table_args__ = (UniqueConstraint("entity_id", "code", name="uq_branches_code"), _A)

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = name_column()
    state_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    gstin: Mapped[str | None] = mapped_column(String(15), nullable=True)
    is_active: Mapped[bool] = flag(True)


class FinancialYear(TimestampMixin, Base):
    __tablename__ = "financial_years"
    __table_args__ = (
        UniqueConstraint("entity_id", "start_date", name="uq_financial_years_start"),
        _A,
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    label: Mapped[str] = mapped_column(String(64))
    start_date: Mapped[date]
    end_date: Mapped[date]
    is_closed: Mapped[bool] = flag()


class Currency(TimestampMixin, Base):
    __tablename__ = "currencies"
    __table_args__ = _A

    code: Mapped[str] = mapped_column(CHAR(3), primary_key=True)
    name: Mapped[str] = name_column()
    decimal_places: Mapped[int] = mapped_column(TinyInt, default=2, server_default="2")


class ExchangeRate(TimestampMixin, Base):
    __tablename__ = "exchange_rates"
    __table_args__ = (
        UniqueConstraint("from_code", "to_code", "rate_date", name="uq_exchange_rates_day"),
        _A,
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    from_code: Mapped[str] = mapped_column(CHAR(3), ForeignKey(f"{ACCOUNTING}.currencies.code"))
    to_code: Mapped[str] = mapped_column(CHAR(3), ForeignKey(f"{ACCOUNTING}.currencies.code"))
    rate_date: Mapped[date]
    rate: Mapped[Decimal] = mapped_column(FxRate)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)


# --- 4.2 Chart of accounts -------------------------------------------------------------


class StandardAccount(TimestampMixin, Base):
    """Standard chart of accounts for consolidation (RPT-006, CON-011)."""

    __tablename__ = "standard_accounts"
    __table_args__ = _A

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    parent_id: Mapped[int | None] = mapped_column(Id, _fk("standard_accounts"), nullable=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = name_column()
    nature: Mapped[str] = mapped_column(Enum(*NATURES, name="account_nature"))
    statement: Mapped[str] = mapped_column(
        Enum("balance_sheet", "profit_loss", name="financial_statement")
    )
    statement_line: Mapped[str] = mapped_column(String(64))
    cash_flow_class: Mapped[str] = mapped_column(
        Enum("operating", "investing", "financing", "cash", "none", name="cash_flow_class")
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class AccountGroup(SourceTrackingMixin, TimestampMixin, Base):
    """Source group hierarchy (Tally groups), kept as-is per entity."""

    __tablename__ = "account_groups"
    __table_args__ = src_table_args("account_groups", ACCOUNTING)

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    parent_id: Mapped[int | None] = mapped_column(Id, _fk("account_groups"), nullable=True)
    name: Mapped[str] = name_column()
    nature: Mapped[str | None] = mapped_column(Enum(*NATURES, name="account_nature"), nullable=True)
    is_primary: Mapped[bool] = flag()
    affects_gross_profit: Mapped[bool] = flag()
    standard_account_id: Mapped[int | None] = mapped_column(
        Id, _fk("standard_accounts"), nullable=True
    )


class Ledger(SourceTrackingMixin, TimestampMixin, Base):
    __tablename__ = "ledgers"
    __table_args__ = src_table_args(
        "ledgers",
        ACCOUNTING,
        Index("ix_ledgers_entity_group", "entity_id", "group_id"),
        Index("ix_ledgers_entity_name", "entity_id", "name"),
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    group_id: Mapped[int] = mapped_column(Id, _fk("account_groups"))
    name: Mapped[str] = name_column()
    alias: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ledger_kind: Mapped[str] = mapped_column(
        Enum(
            "party", "bank", "cash", "tax", "stock", "income", "expense",
            "asset", "liability", "equity", "other",
            name="ledger_kind",
        ),
        default="other",
    )  # fmt: skip
    party_id: Mapped[int | None] = mapped_column(Id, _fk("parties"), nullable=True)
    standard_account_id: Mapped[int | None] = mapped_column(
        Id, _fk("standard_accounts"), nullable=True
    )
    mapping_status: Mapped[str] = mapped_column(
        Enum("auto", "suggested", "confirmed", "unmapped", name="mapping_status"),
        default="unmapped",
    )
    opening_balance: Mapped[Decimal] = mapped_column(Money, default=0, server_default="0")
    opening_balance_date: Mapped[date | None] = mapped_column(nullable=True)
    currency_code: Mapped[str] = mapped_column(
        CHAR(3), ForeignKey(f"{ACCOUNTING}.currencies.code"), default="INR"
    )
    is_bill_wise: Mapped[bool] = flag()
    is_cost_centre_applicable: Mapped[bool] = flag()
    gstin: Mapped[str | None] = mapped_column(String(15), nullable=True)


# --- 4.3 Parties, items and other masters ----------------------------------------------


class Party(SourceTrackingMixin, TimestampMixin, Base):
    """Customers and vendors. name, pan, email and phone are sensitive (AI-015, ACC-003)."""

    __tablename__ = "parties"
    __table_args__ = src_table_args("parties", ACCOUNTING)

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    name: Mapped[str] = name_column()
    party_type: Mapped[str] = mapped_column(
        Enum("customer", "vendor", "both", "other", name="party_type")
    )
    gstin: Mapped[str | None] = mapped_column(String(15), nullable=True)
    pan: Mapped[str | None] = mapped_column(String(10), nullable=True)
    state_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    country_code: Mapped[str | None] = mapped_column(CHAR(2), nullable=True)
    credit_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    credit_limit: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)


class VoucherType(SourceTrackingMixin, TimestampMixin, Base):
    __tablename__ = "voucher_types"
    __table_args__ = src_table_args("voucher_types", ACCOUNTING)

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    name: Mapped[str] = name_column()
    base_type: Mapped[str] = mapped_column(
        Enum(
            "sales", "purchase", "payment", "receipt", "journal", "contra", "debit_note",
            "credit_note", "stock_journal", "delivery_note", "receipt_note", "other",
            name="voucher_base_type",
        )
    )  # fmt: skip
    is_accounting: Mapped[bool] = flag(True)
    is_inventory: Mapped[bool] = flag()


class ItemGroup(SourceTrackingMixin, TimestampMixin, Base):
    __tablename__ = "item_groups"
    __table_args__ = src_table_args("item_groups", ACCOUNTING)

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    parent_id: Mapped[int | None] = mapped_column(Id, _fk("item_groups"), nullable=True)
    name: Mapped[str] = name_column()


class Unit(SourceTrackingMixin, TimestampMixin, Base):
    __tablename__ = "units"
    __table_args__ = src_table_args("units", ACCOUNTING)

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    symbol: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = name_column()
    decimal_places: Mapped[int] = mapped_column(TinyInt, default=0, server_default="0")


class Item(SourceTrackingMixin, TimestampMixin, Base):
    __tablename__ = "items"
    __table_args__ = src_table_args("items", ACCOUNTING)

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    item_group_id: Mapped[int | None] = mapped_column(Id, _fk("item_groups"), nullable=True)
    name: Mapped[str] = name_column()
    code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    unit_id: Mapped[int | None] = mapped_column(Id, _fk("units"), nullable=True)
    hsn_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    gst_rate: Mapped[Decimal | None] = mapped_column(Rate, nullable=True)
    opening_qty: Mapped[Decimal] = mapped_column(Rate, default=0, server_default="0")
    opening_value: Mapped[Decimal] = mapped_column(Money, default=0, server_default="0")


class Godown(SourceTrackingMixin, TimestampMixin, Base):
    __tablename__ = "godowns"
    __table_args__ = src_table_args("godowns", ACCOUNTING)

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    parent_id: Mapped[int | None] = mapped_column(Id, _fk("godowns"), nullable=True)
    name: Mapped[str] = name_column()


class CostCentre(SourceTrackingMixin, TimestampMixin, Base):
    __tablename__ = "cost_centres"
    __table_args__ = src_table_args("cost_centres", ACCOUNTING)

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    parent_id: Mapped[int | None] = mapped_column(Id, _fk("cost_centres"), nullable=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = name_column()


# --- 4.4 Dimensions --------------------------------------------------------------------


class Dimension(TimestampMixin, Base):
    """User-defined reporting dimension (DAT-005)."""

    __tablename__ = "dimensions"
    __table_args__ = _A

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = name_column()
    applies_to: Mapped[str] = mapped_column(Enum("voucher", "line", name="dimension_applies_to"))
    is_active: Mapped[bool] = flag(True)


class DimensionValue(TimestampMixin, Base):
    __tablename__ = "dimension_values"
    __table_args__ = (
        UniqueConstraint("dimension_id", "code", name="uq_dimension_values_code"),
        _A,
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    dimension_id: Mapped[int] = mapped_column(Id, _fk("dimensions"))
    entity_id: Mapped[int | None] = mapped_column(Id, _fk("entities"), nullable=True)
    parent_id: Mapped[int | None] = mapped_column(Id, _fk("dimension_values"), nullable=True)
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = name_column()


# --- 4.5 Transactions ------------------------------------------------------------------


class Voucher(SourceTrackingMixin, TimestampMixin, Base):
    __tablename__ = "vouchers"
    __table_args__ = src_table_args(
        "vouchers",
        ACCOUNTING,
        Index("ix_vouchers_entity_date", "entity_id", "voucher_date"),
        Index("ix_vouchers_entity_type_date", "entity_id", "voucher_type_id", "voucher_date"),
        Index("ix_vouchers_party_date", "party_id", "voucher_date"),
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    branch_id: Mapped[int | None] = mapped_column(Id, _fk("branches"), nullable=True)
    voucher_type_id: Mapped[int] = mapped_column(Id, _fk("voucher_types"))
    voucher_number: Mapped[str] = mapped_column(String(64))
    voucher_date: Mapped[date]
    reference_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reference_date: Mapped[date | None] = mapped_column(nullable=True)
    party_id: Mapped[int | None] = mapped_column(Id, _fk("parties"), nullable=True)
    narration: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency_code: Mapped[str] = mapped_column(
        CHAR(3), ForeignKey(f"{ACCOUNTING}.currencies.code"), default="INR"
    )
    exchange_rate: Mapped[Decimal] = mapped_column(FxRate, default=1, server_default="1")
    is_cancelled: Mapped[bool] = flag()
    is_optional: Mapped[bool] = flag()
    is_post_dated: Mapped[bool] = flag()


class VoucherLine(TimestampMixin, Base):
    """Double-entry lines; SUM(amount) = 0 per voucher (VAL-001). Debit +, credit −."""

    __tablename__ = "voucher_lines"
    __table_args__ = (
        Index("ix_voucher_lines_entity_ledger_date", "entity_id", "ledger_id", "voucher_date"),
        Index("ix_voucher_lines_voucher", "voucher_id"),
        _A,
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    voucher_id: Mapped[int] = mapped_column(Id, _fk("vouchers", ondelete="CASCADE"))
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    voucher_date: Mapped[date]
    line_no: Mapped[int] = mapped_column(Integer)
    ledger_id: Mapped[int] = mapped_column(Id, _fk("ledgers"))
    amount: Mapped[Decimal] = mapped_column(Money)
    amount_fc: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    is_party_line: Mapped[bool] = flag()
    is_effective: Mapped[bool] = flag(True)


class LineDimension(TimestampMixin, Base):
    __tablename__ = "line_dimensions"
    __table_args__ = _A

    voucher_line_id: Mapped[int] = mapped_column(
        Id, _fk("voucher_lines", ondelete="CASCADE"), primary_key=True
    )
    dimension_value_id: Mapped[int] = mapped_column(Id, _fk("dimension_values"), primary_key=True)


class LineCostAllocation(TimestampMixin, Base):
    __tablename__ = "line_cost_allocations"
    __table_args__ = _A

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    voucher_line_id: Mapped[int] = mapped_column(Id, _fk("voucher_lines", ondelete="CASCADE"))
    cost_centre_id: Mapped[int] = mapped_column(Id, _fk("cost_centres"))
    amount: Mapped[Decimal] = mapped_column(Money)


class BillAllocation(TimestampMixin, Base):
    """Bill-wise allocations, used for receivables and payables ageing."""

    __tablename__ = "bill_allocations"
    __table_args__ = _A

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    voucher_line_id: Mapped[int] = mapped_column(Id, _fk("voucher_lines", ondelete="CASCADE"))
    party_id: Mapped[int | None] = mapped_column(Id, _fk("parties"), nullable=True)
    bill_type: Mapped[str] = mapped_column(
        Enum("new_ref", "against_ref", "advance", "on_account", name="bill_type")
    )
    bill_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bill_date: Mapped[date | None] = mapped_column(nullable=True)
    due_date: Mapped[date | None] = mapped_column(nullable=True)
    amount: Mapped[Decimal] = mapped_column(Money)


class InventoryLine(TimestampMixin, Base):
    """Stock movement; quantity signed: in +, out −."""

    __tablename__ = "inventory_lines"
    __table_args__ = _A

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    voucher_id: Mapped[int] = mapped_column(Id, _fk("vouchers", ondelete="CASCADE"))
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    voucher_date: Mapped[date]
    line_no: Mapped[int] = mapped_column(Integer)
    item_id: Mapped[int] = mapped_column(Id, _fk("items"))
    godown_id: Mapped[int | None] = mapped_column(Id, _fk("godowns"), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Rate)
    unit_id: Mapped[int | None] = mapped_column(Id, _fk("units"), nullable=True)
    rate: Mapped[Decimal | None] = mapped_column(Rate, nullable=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    discount_pct: Mapped[Decimal | None] = mapped_column(Rate, nullable=True)
    batch_name: Mapped[str | None] = mapped_column(String(255), nullable=True)


class TaxLine(TimestampMixin, Base):
    __tablename__ = "tax_lines"
    __table_args__ = _A

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    voucher_id: Mapped[int] = mapped_column(Id, _fk("vouchers", ondelete="CASCADE"))
    voucher_line_id: Mapped[int | None] = mapped_column(
        Id, _fk("voucher_lines", ondelete="CASCADE"), nullable=True
    )
    tax_type: Mapped[str] = mapped_column(
        Enum("cgst", "sgst", "igst", "cess", "tds", "tcs", "vat", "other", name="tax_type")
    )
    rate: Mapped[Decimal | None] = mapped_column(Rate, nullable=True)
    taxable_amount: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    tax_amount: Mapped[Decimal] = mapped_column(Money)
    hsn_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
