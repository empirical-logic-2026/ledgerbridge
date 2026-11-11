"""`ledgerbridge_accounting`: the canonical, source-independent accounting model
(schema.md Section 4; types per Section 9).

Sign convention: debit positive, credit negative (schema.md Section 1).
Voucher child tables cascade on delete: a changed voucher's children are replaced as a
whole in one transaction (schema.md Section 8, rule 7).
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CHAR,
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import (
    ORIGINS,
    Base,
    FxRate,
    Id,
    Money,
    Rate,
    SmallInt,
    SourceTrackingMixin,
    Timestamp,
    TimestampMixin,
    TinyInt,
    flag,
    name_column,
    src_table_args,
)
from core.models.schemas import ACCOUNTING, SYSTEM

SOURCE_CHECKS = ("sync", "entity_check")  # what asked the source which companies are loaded

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
    gstin: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pan: Mapped[str | None] = mapped_column(String(32), nullable=True)
    base_currency_code: Mapped[str] = mapped_column(
        CHAR(3), ForeignKey(f"{ACCOUNTING}.currencies.code"), default="INR", server_default="INR"
    )
    fy_start_month: Mapped[int] = mapped_column(TinyInt, default=4, server_default="4")
    books_from: Mapped[date | None] = mapped_column(nullable=True)
    is_active: Mapped[bool] = flag(True)
    # On hold (SYN-007): skipped by sync, validation and statements unless named, left out of
    # the report's verdict and hidden from dashboards; set with `./dev.ps1 on-hold`.
    is_on_hold: Mapped[bool] = flag()
    # The source's settings (migration 0035; NULL: not read): accounts integrated with
    # inventory, stock valued FIFO, the books audited up to a date.
    is_integrated: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_fifo: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    audited_upto: Mapped[date | None] = mapped_column(nullable=True)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)  # ADR-025


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
    # Whether the source had this company loaded when last asked (by a sync or entity-check;
    # migration 0025): the dashboard shows it without contacting the source. NULL: never asked.
    source_checked_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    source_loaded: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    source_checked_by: Mapped[str | None] = mapped_column(
        Enum(*SOURCE_CHECKS, name="source_check"), nullable=True
    )


class Branch(TimestampMixin, Base):
    __tablename__ = "branches"
    __table_args__ = (UniqueConstraint("entity_id", "code", name="uq_branches_code"), _A)

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = name_column()
    state_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    gstin: Mapped[str | None] = mapped_column(String(32), nullable=True)
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

    code: Mapped[str] = mapped_column(CHAR(3), primary_key=True)  # ISO 4217
    name: Mapped[str] = name_column()
    decimal_places: Mapped[int] = mapped_column(TinyInt, default=2, server_default="2")
    symbol: Mapped[str | None] = mapped_column(String(16), nullable=True)  # e.g. "$"


class CurrencySource(SourceTrackingMixin, TimestampMixin, Base):
    """A currency as one entity's source names it (Tally: a currency master, e.g. "$"),
    mapped to its ISO code when the source gives one (FX-001, schema.md 4.8)."""

    __tablename__ = "currency_sources"
    __table_args__ = src_table_args("currency_sources", ACCOUNTING)

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    name: Mapped[str] = name_column()  # as the source writes it in amounts ("$")
    currency_code: Mapped[str | None] = mapped_column(
        CHAR(3), ForeignKey(f"{ACCOUNTING}.currencies.code"), nullable=True
    )
    formal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decimal_places: Mapped[int | None] = mapped_column(TinyInt, nullable=True)


RATE_KINDS = ("standard", "buying", "selling", "vouchers")
RATE_SOURCES = ("source_rate_list", "vouchers")


class ExchangeRate(TimestampMixin, Base):
    """A rate (base currency per unit of a foreign currency) on a date, per entity, with
    where it came from (FX-003): the source's own rate list (its kind: standard, buying,
    selling), or the day's foreign-currency voucher lines weighted by foreign amount."""

    __tablename__ = "exchange_rates"
    __table_args__ = (
        UniqueConstraint(
            "entity_id", "currency_name", "rate_date", "rate_kind", name="uq_exchange_rates_day"
        ),
        _A,
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    # The currency as the source names it (currency_sources.name); its ISO code when known.
    currency_name: Mapped[str] = mapped_column(String(64))
    currency_code: Mapped[str | None] = mapped_column(
        CHAR(3), ForeignKey(f"{ACCOUNTING}.currencies.code"), nullable=True
    )
    rate_date: Mapped[date]
    rate: Mapped[Decimal] = mapped_column(FxRate)
    rate_kind: Mapped[str] = mapped_column(Enum(*RATE_KINDS, name="rate_kind"))
    source: Mapped[str] = mapped_column(Enum(*RATE_SOURCES, name="rate_source"))
    voucher_count: Mapped[int | None] = mapped_column(Integer, nullable=True)


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
    # The source's own predefined group this is, renamed or not, in our vocabulary (e.g.
    # "sales_accounts"; Tally: its RESERVEDNAME). NULL for groups the user created
    # (migration 0021, RPT-013).
    predefined_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    standard_account_id: Mapped[int | None] = mapped_column(
        Id, _fk("standard_accounts"), nullable=True
    )
    # Where the source lists it among its siblings (Tally SORTPOSITION; migration 0035):
    # the statements order primary groups by it, as the source does.
    sort_position: Mapped[int | None] = mapped_column(Integer, nullable=True)


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
    # The ledger's own currency (FX-001; migration 0022): as the source names it (Tally
    # CURRENCYNAME, e.g. "$"), its ISO code (NULL when the source's currency has none), and
    # whether it is another than the entity's base currency. Base-currency figures stay the
    # books; a ledger kept in the base currency can still hold foreign amounts (its lines'
    # `amount_fc`, its opening's below).
    currency_code: Mapped[str | None] = mapped_column(
        CHAR(3), ForeignKey(f"{ACCOUNTING}.currencies.code"), nullable=True, default="INR"
    )
    currency_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_foreign_currency: Mapped[bool] = flag()
    # The currency and amount of the opening's foreign part, when it has one.
    opening_currency_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    opening_balance_fc: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    is_bill_wise: Mapped[bool] = flag()
    is_cost_centre_applicable: Mapped[bool] = flag()
    # Where the source lists it (Tally SORTPOSITION) and whether it affects stock (Tally
    # AFFECTSSTOCK); migration 0035, NULL: not read.
    sort_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    affects_stock: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    gstin: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Set for tax ledgers (e.g. CGST payable); lines posted to them become tax_lines (M3).
    tax_type: Mapped[str | None] = mapped_column(
        Enum("cgst", "sgst", "igst", "cess", "tds", "tcs", "vat", "other", name="tax_type"),
        nullable=True,
    )


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
    gstin: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pan: Mapped[str | None] = mapped_column(String(32), nullable=True)
    state_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    country_code: Mapped[str | None] = mapped_column(CHAR(2), nullable=True)
    credit_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    credit_limit: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Regular, Composition, Unregistered, Consumer, ... (migration 0034).
    gst_registration_type: Mapped[str | None] = mapped_column(String(32), nullable=True)


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
    # The source's own standard type it derives from (e.g. Tally's "Sales Order"), from the
    # source's fixed list of standard names only; NULL when it can't be told (ADR-027).
    standard_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Whether its vouchers' inventory lines move stock (orders and memorandum don't).
    moves_stock: Mapped[bool] = flag(True)


class VoucherNumberSeries(TimestampMixin, Base):
    """A voucher type's numbering series (Tally: VOUCHERNUMBERSERIES.LIST; migration 0035),
    e.g. "Default" and a branch's own. Replaced as a whole with each read of the type."""

    __tablename__ = "voucher_number_series"
    __table_args__ = _A

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    voucher_type_id: Mapped[int] = mapped_column(
        Id, _fk("voucher_types", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    numbering_method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    numbering_sub_method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    beginning_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prefill_zero: Mapped[bool] = flag()
    prevent_duplicates: Mapped[bool] = flag()


class ItemGroup(SourceTrackingMixin, TimestampMixin, Base):
    __tablename__ = "item_groups"
    __table_args__ = src_table_args("item_groups", ACCOUNTING)

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    parent_id: Mapped[int | None] = mapped_column(Id, _fk("item_groups"), nullable=True)
    name: Mapped[str] = name_column()


class StockCategory(SourceTrackingMixin, TimestampMixin, Base):
    """A stock category: a second way of grouping stock items, across their groups (Tally:
    Stock Category; migration 0036)."""

    __tablename__ = "stock_categories"
    __table_args__ = src_table_args("stock_categories", ACCOUNTING)

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    parent_id: Mapped[int | None] = mapped_column(Id, _fk("stock_categories"), nullable=True)
    name: Mapped[str] = name_column()


class SourceBudget(SourceTrackingMixin, TimestampMixin, Base):
    """A budget kept in the source (Tally: Budget; migration 0036). Kept apart from our own
    budgets (schema.md 4.7, proposed for M7b) so that design isn't pre-empted."""

    __tablename__ = "source_budgets"
    __table_args__ = src_table_args("source_budgets", ACCOUNTING)

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    parent_id: Mapped[int | None] = mapped_column(Id, _fk("source_budgets"), nullable=True)
    name: Mapped[str] = name_column()
    use_actuals: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class SourceBudgetLine(TimestampMixin, Base):
    """A ledger's budget for a period in a source budget (migration 0036): on its net
    transactions or its closing balance, the amount as the source writes it. Replaced as a
    whole with each read of the budget."""

    __tablename__ = "source_budget_lines"
    __table_args__ = _A

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    budget_id: Mapped[int] = mapped_column(
        Id, _fk("source_budgets", ondelete="CASCADE"), index=True
    )
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    ledger_id: Mapped[int | None] = mapped_column(Id, _fk("ledgers"), nullable=True)
    ledger_name: Mapped[str] = mapped_column(String(255))
    period_from: Mapped[date | None] = mapped_column(nullable=True)
    period_to: Mapped[date | None] = mapped_column(nullable=True)
    basis: Mapped[str] = mapped_column(String(32))  # net_transactions / closing_balance
    amount: Mapped[Decimal] = mapped_column(Money)


class ItemPrice(TimestampMixin, Base):
    """A price in a stock item's price list (Tally: FULLPRICELIST; migration 0036): for a
    price level, from a date, for a quantity range, with its discount. Replaced as a whole
    with each read of the item."""

    __tablename__ = "item_prices"
    __table_args__ = _A

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    item_id: Mapped[int] = mapped_column(Id, _fk("items", ondelete="CASCADE"), index=True)
    price_level: Mapped[str] = mapped_column(String(255))
    applicable_from: Mapped[date | None] = mapped_column(nullable=True)
    rate: Mapped[Decimal | None] = mapped_column(Rate, nullable=True)
    from_quantity: Mapped[Decimal | None] = mapped_column(Rate, nullable=True)
    to_quantity: Mapped[Decimal | None] = mapped_column(Rate, nullable=True)
    discount_pct: Mapped[Decimal | None] = mapped_column(Rate, nullable=True)


class Unit(SourceTrackingMixin, TimestampMixin, Base):
    __tablename__ = "units"
    __table_args__ = src_table_args("units", ACCOUNTING)

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    symbol: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = name_column()
    decimal_places: Mapped[int] = mapped_column(TinyInt, default=0, server_default="0")


class Item(SourceTrackingMixin, TimestampMixin, Base):
    __tablename__ = "items"
    __table_args__ = src_table_args("items", ACCOUNTING)

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    item_group_id: Mapped[int | None] = mapped_column(Id, _fk("item_groups"), nullable=True)
    name: Mapped[str] = name_column()
    code: Mapped[str | None] = mapped_column(String(255), nullable=True)
    unit_id: Mapped[int | None] = mapped_column(Id, _fk("units"), nullable=True)
    hsn_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    gst_rate: Mapped[Decimal | None] = mapped_column(Rate, nullable=True)
    opening_qty: Mapped[Decimal] = mapped_column(Rate, default=0, server_default="0")
    opening_value: Mapped[Decimal] = mapped_column(Money, default=0, server_default="0")
    # GST taxability (Taxable, Exempt, Nil Rated, ...) and HSN classification (migration
    # 0034); `hsn_code` and `gst_rate` (the integrated rate) are filled from then too.
    gst_taxability: Mapped[str | None] = mapped_column(String(32), nullable=True)
    gst_classification: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Its stock category, reorder level and minimum order quantity (base units; migration
    # 0036).
    stock_category_id: Mapped[int | None] = mapped_column(
        Id, _fk("stock_categories"), nullable=True
    )
    reorder_level: Mapped[Decimal | None] = mapped_column(Rate, nullable=True)
    min_order_quantity: Mapped[Decimal | None] = mapped_column(Rate, nullable=True)


GODOWN_HOLDINGS = ("own", "ours_with_third_party", "third_party_with_us")


class Godown(SourceTrackingMixin, TimestampMixin, Base):
    __tablename__ = "godowns"
    __table_args__ = src_table_args("godowns", ACCOUNTING)

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    parent_id: Mapped[int | None] = mapped_column(Id, _fk("godowns"), nullable=True)
    name: Mapped[str] = name_column()
    # Whose stock it holds: stock at an `ours_with_third_party` godown (a job worker's
    # location) isn't in the source's stock balances; `third_party_with_us` stock is.
    holding: Mapped[str] = mapped_column(
        Enum(*GODOWN_HOLDINGS, name="godown_holding"), default="own", server_default="own"
    )


class CostCategory(SourceTrackingMixin, TimestampMixin, Base):
    """A set of cost centres a line's amount is allocated over; one line can be allocated in
    several categories, each in full (Tally: Cost Category)."""

    __tablename__ = "cost_categories"
    __table_args__ = src_table_args("cost_categories", ACCOUNTING)

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    name: Mapped[str] = name_column()


class TaxUnit(SourceTrackingMixin, TimestampMixin, Base):
    """A tax registration of the company (Tally: Tax Unit; migration 0034): e.g. its GSTIN
    in a state, with the registration type and the date it applies from."""

    __tablename__ = "tax_units"
    __table_args__ = src_table_args("tax_units", ACCOUNTING)

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    name: Mapped[str] = name_column()
    gstin: Mapped[str | None] = mapped_column(String(32), nullable=True)
    state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    registration_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    registered_from: Mapped[date | None] = mapped_column(nullable=True)
    used_for: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_primary: Mapped[bool] = flag()


class CostCentre(SourceTrackingMixin, TimestampMixin, Base):
    __tablename__ = "cost_centres"
    __table_args__ = src_table_args("cost_centres", ACCOUNTING)

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    parent_id: Mapped[int | None] = mapped_column(Id, _fk("cost_centres"), nullable=True)
    category: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # as the source names it
    cost_category_id: Mapped[int | None] = mapped_column(Id, _fk("cost_categories"), nullable=True)
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
    # Set for a dimension promoted from a catalogued source field (ADR-025): its values come
    # from that field in `extra` of records of this object type, kept up to date by the
    # transform.
    source_object_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_field: Mapped[str | None] = mapped_column(String(255), nullable=True)


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


class SourceField(Base):
    """Field catalogue (ADR-025): every field found in `extra` (fields with no column, e.g.
    Tally UDFs), per entity and object type, filled by the transform. Field names only;
    values stay in `extra`."""

    __tablename__ = "source_fields"
    __table_args__ = (
        UniqueConstraint("entity_id", "object_type", "field_path", name="uq_source_fields_field"),
        _A,
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    object_type: Mapped[str] = mapped_column(String(64))
    field_path: Mapped[str] = mapped_column(String(255))
    prefix: Mapped[str | None] = mapped_column(String(64), nullable=True)
    inferred_type: Mapped[str] = mapped_column(
        Enum("text", "number", "date", "flag", "mixed", name="source_field_type")
    )
    record_count: Mapped[int] = mapped_column(BigInteger, default=0)
    first_seen_at: Mapped[datetime] = mapped_column(Timestamp)
    last_seen_at: Mapped[datetime] = mapped_column(Timestamp)


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
    voucher_number: Mapped[str] = mapped_column(String(255))
    voucher_date: Mapped[date]
    reference_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reference_date: Mapped[date | None] = mapped_column(nullable=True)
    # Keep Tally's timezone-unspecified wall-clock value; it is not a UTC system timestamp.
    source_altered_at: Mapped[datetime | None] = mapped_column(
        DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True
    )
    # The source's effective date (Tally's EFFECTIVEDATE); balances count by voucher_date.
    effective_date: Mapped[date | None] = mapped_column(nullable=True)
    party_id: Mapped[int | None] = mapped_column(Id, _fk("parties"), nullable=True)
    narration: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency_code: Mapped[str] = mapped_column(
        CHAR(3), ForeignKey(f"{ACCOUNTING}.currencies.code"), default="INR"
    )
    exchange_rate: Mapped[Decimal] = mapped_column(FxRate, default=1, server_default="1")
    is_cancelled: Mapped[bool] = flag()
    is_optional: Mapped[bool] = flag()
    is_post_dated: Mapped[bool] = flag()
    # GST (migration 0034): the company's registration (tax unit) the voucher is under, the
    # place of supply, the e-invoice (IRN, acknowledgement number and date), the e-way bill.
    gst_registration: Mapped[str | None] = mapped_column(String(255), nullable=True)
    place_of_supply: Mapped[str | None] = mapped_column(String(64), nullable=True)
    irn: Mapped[str | None] = mapped_column(String(128), nullable=True)
    irn_ack_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    irn_date: Mapped[date | None] = mapped_column(nullable=True)
    eway_bill_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    eway_bill_date: Mapped[date | None] = mapped_column(nullable=True)
    # Migration 0035: the numbering series it is numbered in, the last day a reversing
    # journal applies (Tally ACTIVETO), and whether it affects cash flow (HASCASHFLOW).
    number_series: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active_to: Mapped[date | None] = mapped_column(nullable=True)
    has_cash_flow: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


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
    # A foreign-currency line's currency as the source names it and its rate as written
    # (base per unit; FX-001). NULL on base-currency lines.
    currency_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    exchange_rate: Mapped[Decimal | None] = mapped_column(FxRate, nullable=True)
    is_party_line: Mapped[bool] = flag()
    is_effective: Mapped[bool] = flag(True)
    # A bank line's instrument ("; " between several): the cheque or instrument number, its
    # kind, dates and reconciliation status (migration 0030); the source's own id for the bank
    # entry, never a UTR; the UTR, only a value that looks like one (core/utr.py), and where
    # it was found (bank_field, udf or narration).
    instrument_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    utr: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tally_bank_entry_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    utr_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    transaction_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    instrument_date: Mapped[date | None] = mapped_column(nullable=True)
    bank_cleared_date: Mapped[date | None] = mapped_column(nullable=True)
    bank_recon_status: Mapped[str | None] = mapped_column(String(64), nullable=True)


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
    cost_category_id: Mapped[int | None] = mapped_column(Id, _fk("cost_categories"), nullable=True)
    cost_centre_id: Mapped[int] = mapped_column(Id, _fk("cost_centres"))
    amount: Mapped[Decimal] = mapped_column(Money)  # canonical sign, as the line's


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


class ItemOpeningBatch(TimestampMixin, Base):
    """A stock item's opening at one godown and batch (migration 0032): the parts of
    `items.opening_qty` and `opening_value`, as at the books' beginning. Replaced as a whole
    with each read of the item."""

    __tablename__ = "item_opening_batches"
    __table_args__ = _A

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    item_id: Mapped[int] = mapped_column(Id, _fk("items", ondelete="CASCADE"), index=True)
    godown_id: Mapped[int | None] = mapped_column(Id, _fk("godowns"), nullable=True)
    batch_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Rate)
    rate: Mapped[Decimal | None] = mapped_column(Rate, nullable=True)
    value: Mapped[Decimal] = mapped_column(Money)


class OpeningBill(TimestampMixin, Base):
    """A bill of a ledger's opening balance (its bill-wise opening; migration 0031): the
    bills from before the books' beginning, for ageing. Replaced as a whole with each read of
    the ledger's opening bills. Canonical sign (debit positive)."""

    __tablename__ = "opening_bills"
    __table_args__ = _A

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    ledger_id: Mapped[int] = mapped_column(Id, _fk("ledgers", ondelete="CASCADE"), index=True)
    party_id: Mapped[int | None] = mapped_column(Id, _fk("parties"), nullable=True)
    bill_name: Mapped[str] = mapped_column(String(255))
    bill_date: Mapped[date | None] = mapped_column(nullable=True)
    due_date: Mapped[date | None] = mapped_column(nullable=True)
    amount: Mapped[Decimal] = mapped_column(Money)


class VoucherVersion(Base):
    """An observed voucher snapshot retained for alteration-history comparisons."""

    __tablename__ = "voucher_versions"
    __table_args__ = (
        UniqueConstraint("connection_id", "capture_key", name="uq_voucher_versions_capture"),
        Index("ix_voucher_versions_entity_key", "entity_id", "voucher_source_key", "id"),
        Index("ix_voucher_versions_altered_at", "source_altered_at"),
        _A,
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    voucher_id: Mapped[int] = mapped_column(Id, _fk("vouchers"))
    connection_id: Mapped[int] = mapped_column(Id, ForeignKey(f"{SYSTEM}.connections.id"))
    voucher_source_key: Mapped[str] = mapped_column(String(191))
    company_name: Mapped[str] = mapped_column(String(255))
    voucher_number: Mapped[str] = mapped_column(String(255))
    capture_key: Mapped[str] = mapped_column(String(191))
    raw_record_id: Mapped[int | None] = mapped_column(Id, nullable=True)
    payload_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    source_alter_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source_altered_at: Mapped[datetime | None] = mapped_column(
        DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True
    )
    observed_at: Mapped[datetime] = mapped_column(Timestamp)
    is_deleted: Mapped[bool] = flag()
    deletion_detected_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    previous_version_id: Mapped[int | None] = mapped_column(
        Id, ForeignKey(f"{ACCOUNTING}.voucher_versions.id"), nullable=True
    )


class VoucherVersionLine(Base):
    """One ledger posting as captured in a voucher version."""

    __tablename__ = "voucher_version_lines"
    __table_args__ = (
        Index("ix_voucher_version_lines_version", "voucher_version_id", "line_no"),
        Index("ix_voucher_version_lines_ledger", "ledger_source_key"),
        _A,
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    voucher_version_id: Mapped[int] = mapped_column(Id, _fk("voucher_versions", ondelete="CASCADE"))
    line_no: Mapped[int] = mapped_column(Integer)
    ledger_id: Mapped[int] = mapped_column(Id, _fk("ledgers"))
    ledger_source_key: Mapped[str] = mapped_column(String(191))
    ledger_name: Mapped[str] = mapped_column(String(255))
    amount: Mapped[Decimal] = mapped_column(Money)
    amount_fc: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    currency_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    exchange_rate: Mapped[Decimal | None] = mapped_column(FxRate, nullable=True)
    is_party_line: Mapped[bool] = flag()
    details: Mapped[dict[str, Any]] = mapped_column(JSON)
    identity_hash: Mapped[str] = mapped_column(CHAR(64))
    content_hash: Mapped[str] = mapped_column(CHAR(64))


class VoucherLedgerChange(Base):
    """A classified difference between two captured voucher versions."""

    __tablename__ = "voucher_ledger_changes"
    __table_args__ = (
        Index("ix_voucher_ledger_changes_version", "version_id"),
        Index("ix_voucher_ledger_changes_previous_version", "previous_version_id"),
        _A,
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    previous_version_id: Mapped[int | None] = mapped_column(
        Id, _fk("voucher_versions"), nullable=True
    )
    version_id: Mapped[int] = mapped_column(Id, _fk("voucher_versions", ondelete="CASCADE"))
    previous_line_id: Mapped[int | None] = mapped_column(
        Id, _fk("voucher_version_lines"), nullable=True
    )
    new_line_id: Mapped[int | None] = mapped_column(Id, _fk("voucher_version_lines"), nullable=True)
    change_type: Mapped[str] = mapped_column(
        Enum("added", "modified", "deleted", "ambiguous", name="voucher_ledger_change_type")
    )
    matching_basis: Mapped[str] = mapped_column(String(64))


def _same_quantity(context: Any) -> Decimal:
    """Default stock_quantity: the line's quantity (untracked lines move all of it)."""
    return context.get_current_parameters()["quantity"]


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
    # The quantity this line moves in stock: the quantity, less the part tracked to a
    # delivery or receipt note on a voucher that posts to the books (the note moves it).
    stock_quantity: Mapped[Decimal] = mapped_column(Rate, default=_same_quantity)
    unit_id: Mapped[int | None] = mapped_column(Id, _fk("units"), nullable=True)
    rate: Mapped[Decimal | None] = mapped_column(Rate, nullable=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    discount_pct: Mapped[Decimal | None] = mapped_column(Rate, nullable=True)
    batch_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # The other godown of a move between godowns: where an outgoing line's stock goes, where
    # an incoming line's came from (a transfer between godowns, a job worker's godown).
    # Migration 0032.
    counterpart_godown_id: Mapped[int | None] = mapped_column(Id, _fk("godowns"), nullable=True)
    # The sales or purchase order the line belongs to (on the order) or is against (on an
    # invoice or note), and when the order is due. Migration 0033.
    order_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    order_due_date: Mapped[date | None] = mapped_column(nullable=True)


class LineGstRate(TimestampMixin, Base):
    """A GST rate per duty head on a voucher's ledger line or inventory line (Tally:
    RATEDETAILS; migration 0034), when the line carries its own (not every head 0).
    Replaced with the voucher's other child rows."""

    __tablename__ = "line_gst_rates"
    __table_args__ = _A

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    voucher_id: Mapped[int] = mapped_column(Id, _fk("vouchers", ondelete="CASCADE"), index=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    voucher_line_id: Mapped[int | None] = mapped_column(
        Id, _fk("voucher_lines", ondelete="CASCADE"), nullable=True
    )
    inventory_line_id: Mapped[int | None] = mapped_column(
        Id, _fk("inventory_lines", ondelete="CASCADE"), nullable=True
    )
    duty_head: Mapped[str] = mapped_column(String(32))
    rate: Mapped[Decimal] = mapped_column(Rate)


class VoucherOrder(TimestampMixin, Base):
    """An order a voucher (an invoice, a delivery or receipt note) is made against
    (migration 0033): its number and date as the voucher names them, and the order voucher
    when one with that number is stored (sales orders for sales-side vouchers, purchase
    orders for purchase-side ones). Replaced with the voucher's other child rows."""

    __tablename__ = "voucher_orders"
    __table_args__ = _A

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    voucher_id: Mapped[int] = mapped_column(Id, _fk("vouchers", ondelete="CASCADE"), index=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    order_number: Mapped[str] = mapped_column(String(255))
    order_date: Mapped[date | None] = mapped_column(nullable=True)
    order_voucher_id: Mapped[int | None] = mapped_column(
        Id, _fk("vouchers", ondelete="SET NULL"), nullable=True
    )


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
    hsn_code: Mapped[str | None] = mapped_column(String(32), nullable=True)


# --- 4.9 Source figures (ADR-033, ADR-040) ---------------------------------------------
# Figures the source calculates itself and our statements take from it, stored as source
# figures (never posted as vouchers), with the date they are for and when they were read.


class StockValue(TimestampMixin, Base):
    """The source's stock value as of a date, for the period from the books' beginning:
    `total` is the stock its profit uses (opening at the books' beginning, closing at the
    date); `stock_group`, `godown` and `item` rows (migration 0029), by name, where the source
    gives them. Canonical sign (stock is a debit)."""

    __tablename__ = "stock_values"
    __table_args__ = (
        UniqueConstraint(
            "entity_id", "as_of", "scope", "scope_name", name="uq_stock_values_entity_date"
        ),
        _A,
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    connection_id: Mapped[int] = mapped_column(Id, ForeignKey(f"{SYSTEM}.connections.id"))
    origin: Mapped[str] = mapped_column(Enum(*ORIGINS, name="origin"))
    as_of: Mapped[date] = mapped_column(Date)
    scope: Mapped[str] = mapped_column(
        Enum("total", "stock_group", "godown", "item", name="stock_value_scope")
    )
    scope_name: Mapped[str] = mapped_column(String(255), default="")
    opening_value: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    closing_value: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    # Whether the source integrates accounts with inventory (total rows only).
    integrated: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    read_at: Mapped[datetime] = mapped_column(Timestamp)


class FxRevaluationSnapshot(TimestampMixin, Base):
    """A foreign-currency ledger's balance as the source reports it at a date, revalued at
    its current rate, against its book value (FX-004, ADR-037): the difference is the
    source's unrealised gain or loss, never posted as a voucher. `currency_code` and
    `balance_fc` are filled by the foreign-currency data layer (M4b)."""

    __tablename__ = "fx_revaluation_snapshots"
    __table_args__ = (
        UniqueConstraint("ledger_id", "as_of", name="uq_fx_revaluation_ledger_date"),
        Index("ix_fx_revaluation_entity_date", "entity_id", "as_of"),
        _A,
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    ledger_id: Mapped[int] = mapped_column(Id, _fk("ledgers"))
    connection_id: Mapped[int] = mapped_column(Id, ForeignKey(f"{SYSTEM}.connections.id"))
    origin: Mapped[str] = mapped_column(Enum(*ORIGINS, name="origin"))
    as_of: Mapped[date] = mapped_column(Date)
    currency_code: Mapped[str | None] = mapped_column(CHAR(3), nullable=True)
    balance_fc: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    # Our balance (validated equal to the source's book value, VAL-013).
    book_value: Mapped[Decimal] = mapped_column(Money)
    revalued_value: Mapped[Decimal] = mapped_column(Money)
    # book - revalued, canonical sign: a debit (positive) is an unrealised loss.
    unrealised_gain_loss: Mapped[Decimal] = mapped_column(Money)
    read_at: Mapped[datetime] = mapped_column(Timestamp)


# --- 4.10 Settings for the figures (F-RAT-008) -----------------------------------------
# Choices a person makes about the client's ledgers; not source data. Set by a command,
# each change audited (AUD-001).


class ShortTermBorrowing(TimestampMixin, Base):
    """A ledger under Loans (Liability) marked as short-term (e.g. a cash-credit or
    working-capital loan under Secured Loans): the ratios count its credit balance as a
    current liability, like Bank OD A/c (core/ratios.py, F-RAT-008). Set with
    `./dev.ps1 loans mark -Ledger <id>`; ids only, never names."""

    __tablename__ = "short_term_borrowings"
    __table_args__ = (UniqueConstraint("ledger_id", name="uq_short_term_borrowings_ledger"), _A)

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Id, _fk("entities"))
    ledger_id: Mapped[int] = mapped_column(Id, _fk("ledgers"))
