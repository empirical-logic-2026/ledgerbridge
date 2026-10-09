"""M2: every remaining table of schema.md Sections 4 and 5 (ADR-016 database names).

Creates the 25 tables of ledgerbridge_accounting (all of Section 4 except
bank_statement_lines, phase 2) and 17 tables of ledgerbridge_system, and adds the foreign
keys connections.agent_id and raw_records.import_batch_id. Types and keys follow
schema.md Section 9. Voucher child tables cascade on delete (Section 8, rule 7).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-09 16:07:34.205570
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ID = sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql").with_variant(
    sa.Integer(), "sqlite"
)
TS = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
TINYINT = sa.Integer().with_variant(mysql.TINYINT(), "mysql")
SMALLINT = sa.Integer().with_variant(mysql.SMALLINT(), "mysql")


def upgrade() -> None:
    op.create_table('currencies',
    sa.Column('code', sa.CHAR(length=3), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('decimal_places', TINYINT, server_default='2', nullable=False),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.PrimaryKeyConstraint('code'),
    schema='ledgerbridge_accounting'
    )
    op.create_table('dimensions',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('code', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('applies_to', sa.Enum('voucher', 'line', name='dimension_applies_to'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code'),
    schema='ledgerbridge_accounting'
    )
    op.create_table('standard_accounts',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('parent_id', ID, nullable=True),
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('nature', sa.Enum('asset', 'liability', 'equity', 'income', 'expense', name='account_nature'), nullable=False),
    sa.Column('statement', sa.Enum('balance_sheet', 'profit_loss', name='financial_statement'), nullable=False),
    sa.Column('statement_line', sa.String(length=64), nullable=False),
    sa.Column('cash_flow_class', sa.Enum('operating', 'investing', 'financing', 'cash', 'none', name='cash_flow_class'), nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.ForeignKeyConstraint(['parent_id'], ['ledgerbridge_accounting.standard_accounts.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code'),
    schema='ledgerbridge_accounting'
    )
    op.create_table('agents',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('cert_fingerprint', sa.String(length=128), nullable=True),
    sa.Column('version', sa.String(length=32), nullable=True),
    sa.Column('last_seen_at', TS, nullable=True),
    sa.Column('status', sa.Enum('active', 'disabled', name='agent_status'), nullable=False),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name'),
    schema='ledgerbridge_system'
    )
    op.create_table('ai_query_log',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('user_id', sa.CHAR(length=36), nullable=True),
    sa.Column('question', sa.Text(), nullable=False),
    sa.Column('generated_sql', sa.Text(), nullable=True),
    sa.Column('status', sa.Enum('succeeded', 'failed', 'refused', name='ai_query_status'), nullable=False),
    sa.Column('row_count', sa.Integer(), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('provider', sa.String(length=64), nullable=True),
    sa.Column('model', sa.String(length=128), nullable=True),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='ledgerbridge_system'
    )
    op.create_index('ix_ai_query_log_user_created', 'ai_query_log', ['user_id', 'created_at'], unique=False, schema='ledgerbridge_system')
    op.create_table('kpi_definitions',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('code', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('formula_view', sa.String(length=128), nullable=False),
    sa.Column('good_threshold', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('bad_threshold', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('direction', sa.Enum('higher_better', 'lower_better', name='kpi_direction'), nullable=False),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code'),
    schema='ledgerbridge_system'
    )
    op.create_table('permissions',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('code', sa.String(length=64), nullable=False),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code'),
    schema='ledgerbridge_system'
    )
    op.create_table('roles',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('code', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('is_system', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code'),
    schema='ledgerbridge_system'
    )
    op.create_table('settings',
    sa.Column('key', sa.String(length=128), nullable=False),
    sa.Column('value', sa.JSON(), nullable=False),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.PrimaryKeyConstraint('key'),
    schema='ledgerbridge_system'
    )
    op.create_table('users',
    sa.Column('id', sa.CHAR(length=36), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('display_name', sa.String(length=255), nullable=False),
    sa.Column('status', sa.Enum('active', 'disabled', 'locked', name='user_status'), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=True),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email'),
    schema='ledgerbridge_system'
    )
    op.create_table('entities',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('legal_name', sa.String(length=255), nullable=True),
    sa.Column('country_code', sa.CHAR(length=2), server_default='IN', nullable=False),
    sa.Column('state_code', sa.String(length=8), nullable=True),
    sa.Column('gstin', sa.String(length=15), nullable=True),
    sa.Column('pan', sa.String(length=10), nullable=True),
    sa.Column('base_currency_code', sa.CHAR(length=3), server_default='INR', nullable=False),
    sa.Column('fy_start_month', TINYINT, server_default='4', nullable=False),
    sa.Column('books_from', sa.Date(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.ForeignKeyConstraint(['base_currency_code'], ['ledgerbridge_accounting.currencies.code'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code'),
    schema='ledgerbridge_accounting'
    )
    op.create_table('exchange_rates',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('from_code', sa.CHAR(length=3), nullable=False),
    sa.Column('to_code', sa.CHAR(length=3), nullable=False),
    sa.Column('rate_date', sa.Date(), nullable=False),
    sa.Column('rate', sa.Numeric(precision=20, scale=8), nullable=False),
    sa.Column('source', sa.String(length=64), nullable=True),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.ForeignKeyConstraint(['from_code'], ['ledgerbridge_accounting.currencies.code'], ),
    sa.ForeignKeyConstraint(['to_code'], ['ledgerbridge_accounting.currencies.code'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('from_code', 'to_code', 'rate_date', name='uq_exchange_rates_day'),
    schema='ledgerbridge_accounting'
    )
    op.create_table('masking_rules',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('role_id', ID, nullable=False),
    sa.Column('target', sa.String(length=64), nullable=False),
    sa.Column('mask_type', sa.Enum('hide', 'partial', 'hash', name='mask_type'), nullable=False),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.ForeignKeyConstraint(['role_id'], ['ledgerbridge_system.roles.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='ledgerbridge_system'
    )
    op.create_table('role_permissions',
    sa.Column('role_id', ID, nullable=False),
    sa.Column('permission_id', ID, nullable=False),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.ForeignKeyConstraint(['permission_id'], ['ledgerbridge_system.permissions.id'], ),
    sa.ForeignKeyConstraint(['role_id'], ['ledgerbridge_system.roles.id'], ),
    sa.PrimaryKeyConstraint('role_id', 'permission_id'),
    schema='ledgerbridge_system'
    )
    op.create_table('user_roles',
    sa.Column('user_id', sa.CHAR(length=36), nullable=False),
    sa.Column('role_id', ID, nullable=False),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.ForeignKeyConstraint(['role_id'], ['ledgerbridge_system.roles.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['ledgerbridge_system.users.id'], ),
    sa.PrimaryKeyConstraint('user_id', 'role_id'),
    schema='ledgerbridge_system'
    )
    op.create_table('branches',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('entity_id', ID, nullable=False),
    sa.Column('code', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('state_code', sa.String(length=8), nullable=True),
    sa.Column('gstin', sa.String(length=15), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.ForeignKeyConstraint(['entity_id'], ['ledgerbridge_accounting.entities.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('entity_id', 'code', name='uq_branches_code'),
    schema='ledgerbridge_accounting'
    )
    op.create_table('dimension_values',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('dimension_id', ID, nullable=False),
    sa.Column('entity_id', ID, nullable=True),
    sa.Column('parent_id', ID, nullable=True),
    sa.Column('code', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.ForeignKeyConstraint(['dimension_id'], ['ledgerbridge_accounting.dimensions.id'], ),
    sa.ForeignKeyConstraint(['entity_id'], ['ledgerbridge_accounting.entities.id'], ),
    sa.ForeignKeyConstraint(['parent_id'], ['ledgerbridge_accounting.dimension_values.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('dimension_id', 'code', name='uq_dimension_values_code'),
    schema='ledgerbridge_accounting'
    )
    op.create_table('entity_sources',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('entity_id', ID, nullable=False),
    sa.Column('connection_id', ID, nullable=False),
    sa.Column('source_entity_key', sa.String(length=191), nullable=False),
    sa.Column('source_entity_name', sa.String(length=255), nullable=False),
    sa.Column('precedence', SMALLINT, server_default='0', nullable=False),
    sa.Column('active_from', sa.Date(), nullable=True),
    sa.Column('active_to', sa.Date(), nullable=True),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.ForeignKeyConstraint(['connection_id'], ['ledgerbridge_system.connections.id'], ),
    sa.ForeignKeyConstraint(['entity_id'], ['ledgerbridge_accounting.entities.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('connection_id', 'source_entity_key', name='uq_entity_sources_source'),
    schema='ledgerbridge_accounting'
    )
    op.create_table('financial_years',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('entity_id', ID, nullable=False),
    sa.Column('label', sa.String(length=64), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=False),
    sa.Column('end_date', sa.Date(), nullable=False),
    sa.Column('is_closed', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.ForeignKeyConstraint(['entity_id'], ['ledgerbridge_accounting.entities.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('entity_id', 'start_date', name='uq_financial_years_start'),
    schema='ledgerbridge_accounting'
    )
    op.create_table('audit_log',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('occurred_at', TS, nullable=False),
    sa.Column('user_id', sa.CHAR(length=36), nullable=True),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('object_type', sa.String(length=64), nullable=True),
    sa.Column('object_id', sa.String(length=64), nullable=True),
    sa.Column('entity_id', ID, nullable=True),
    sa.Column('details', sa.JSON(), nullable=True),
    sa.Column('ip_address', sa.String(length=45), nullable=True),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.ForeignKeyConstraint(['entity_id'], ['ledgerbridge_accounting.entities.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='ledgerbridge_system'
    )
    op.create_index('ix_audit_log_occurred_at', 'audit_log', ['occurred_at'], unique=False, schema='ledgerbridge_system')
    op.create_index('ix_audit_log_user_id', 'audit_log', ['user_id'], unique=False, schema='ledgerbridge_system')
    op.create_table('file_layouts',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('connection_id', ID, nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('column_mapping', sa.JSON(), nullable=False),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.ForeignKeyConstraint(['connection_id'], ['ledgerbridge_system.connections.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('connection_id', 'name', name='uq_file_layouts_name'),
    schema='ledgerbridge_system'
    )
    op.create_table('import_batches',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('connection_id', ID, nullable=False),
    sa.Column('kind', sa.Enum('backup', 'file', name='import_kind'), nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=True),
    sa.Column('file_sha256', sa.CHAR(length=64), nullable=True),
    sa.Column('period_from', sa.Date(), nullable=True),
    sa.Column('period_to', sa.Date(), nullable=True),
    sa.Column('status', sa.Enum('pending', 'running', 'succeeded', 'failed', name='import_status'), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.ForeignKeyConstraint(['connection_id'], ['ledgerbridge_system.connections.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='ledgerbridge_system'
    )
    op.create_table('sync_markers',
    sa.Column('connection_id', ID, nullable=False),
    sa.Column('source_entity_key', sa.String(length=191), nullable=False),
    sa.Column('object_type', sa.String(length=64), nullable=False),
    sa.Column('marker_value', sa.String(length=191), nullable=False),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.ForeignKeyConstraint(['connection_id'], ['ledgerbridge_system.connections.id'], ),
    sa.PrimaryKeyConstraint('connection_id', 'source_entity_key', 'object_type'),
    schema='ledgerbridge_system'
    )
    op.create_table('account_groups',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('entity_id', ID, nullable=False),
    sa.Column('parent_id', ID, nullable=True),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('nature', sa.Enum('asset', 'liability', 'equity', 'income', 'expense', name='account_nature'), nullable=True),
    sa.Column('is_primary', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('affects_gross_profit', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('standard_account_id', ID, nullable=True),
    sa.Column('source_key', sa.String(length=191), nullable=False),
    sa.Column('source_alter_id', sa.BigInteger(), nullable=True),
    sa.Column('origin', sa.Enum('live', 'backup', 'file', 'manual', name='origin'), nullable=False),
    sa.Column('raw_record_id', ID, nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('connection_id', ID, nullable=False),
    sa.Column('import_batch_id', ID, nullable=True),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.ForeignKeyConstraint(['connection_id'], ['ledgerbridge_system.connections.id'], ),
    sa.ForeignKeyConstraint(['entity_id'], ['ledgerbridge_accounting.entities.id'], ),
    sa.ForeignKeyConstraint(['import_batch_id'], ['ledgerbridge_system.import_batches.id'], ),
    sa.ForeignKeyConstraint(['parent_id'], ['ledgerbridge_accounting.account_groups.id'], ),
    sa.ForeignKeyConstraint(['standard_account_id'], ['ledgerbridge_accounting.standard_accounts.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('connection_id', 'source_key', name='uq_account_groups_source'),
    schema='ledgerbridge_accounting'
    )
    op.create_index('ix_account_groups_raw_record', 'account_groups', ['raw_record_id'], unique=False, schema='ledgerbridge_accounting')
    op.create_table('cost_centres',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('entity_id', ID, nullable=False),
    sa.Column('parent_id', ID, nullable=True),
    sa.Column('category', sa.String(length=64), nullable=True),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('source_key', sa.String(length=191), nullable=False),
    sa.Column('source_alter_id', sa.BigInteger(), nullable=True),
    sa.Column('origin', sa.Enum('live', 'backup', 'file', 'manual', name='origin'), nullable=False),
    sa.Column('raw_record_id', ID, nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('connection_id', ID, nullable=False),
    sa.Column('import_batch_id', ID, nullable=True),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.ForeignKeyConstraint(['connection_id'], ['ledgerbridge_system.connections.id'], ),
    sa.ForeignKeyConstraint(['entity_id'], ['ledgerbridge_accounting.entities.id'], ),
    sa.ForeignKeyConstraint(['import_batch_id'], ['ledgerbridge_system.import_batches.id'], ),
    sa.ForeignKeyConstraint(['parent_id'], ['ledgerbridge_accounting.cost_centres.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('connection_id', 'source_key', name='uq_cost_centres_source'),
    schema='ledgerbridge_accounting'
    )
    op.create_index('ix_cost_centres_raw_record', 'cost_centres', ['raw_record_id'], unique=False, schema='ledgerbridge_accounting')
    op.create_table('godowns',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('entity_id', ID, nullable=False),
    sa.Column('parent_id', ID, nullable=True),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('source_key', sa.String(length=191), nullable=False),
    sa.Column('source_alter_id', sa.BigInteger(), nullable=True),
    sa.Column('origin', sa.Enum('live', 'backup', 'file', 'manual', name='origin'), nullable=False),
    sa.Column('raw_record_id', ID, nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('connection_id', ID, nullable=False),
    sa.Column('import_batch_id', ID, nullable=True),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.ForeignKeyConstraint(['connection_id'], ['ledgerbridge_system.connections.id'], ),
    sa.ForeignKeyConstraint(['entity_id'], ['ledgerbridge_accounting.entities.id'], ),
    sa.ForeignKeyConstraint(['import_batch_id'], ['ledgerbridge_system.import_batches.id'], ),
    sa.ForeignKeyConstraint(['parent_id'], ['ledgerbridge_accounting.godowns.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('connection_id', 'source_key', name='uq_godowns_source'),
    schema='ledgerbridge_accounting'
    )
    op.create_index('ix_godowns_raw_record', 'godowns', ['raw_record_id'], unique=False, schema='ledgerbridge_accounting')
    op.create_table('item_groups',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('entity_id', ID, nullable=False),
    sa.Column('parent_id', ID, nullable=True),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('source_key', sa.String(length=191), nullable=False),
    sa.Column('source_alter_id', sa.BigInteger(), nullable=True),
    sa.Column('origin', sa.Enum('live', 'backup', 'file', 'manual', name='origin'), nullable=False),
    sa.Column('raw_record_id', ID, nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('connection_id', ID, nullable=False),
    sa.Column('import_batch_id', ID, nullable=True),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.ForeignKeyConstraint(['connection_id'], ['ledgerbridge_system.connections.id'], ),
    sa.ForeignKeyConstraint(['entity_id'], ['ledgerbridge_accounting.entities.id'], ),
    sa.ForeignKeyConstraint(['import_batch_id'], ['ledgerbridge_system.import_batches.id'], ),
    sa.ForeignKeyConstraint(['parent_id'], ['ledgerbridge_accounting.item_groups.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('connection_id', 'source_key', name='uq_item_groups_source'),
    schema='ledgerbridge_accounting'
    )
    op.create_index('ix_item_groups_raw_record', 'item_groups', ['raw_record_id'], unique=False, schema='ledgerbridge_accounting')
    op.create_table('parties',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('entity_id', ID, nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('party_type', sa.Enum('customer', 'vendor', 'both', 'other', name='party_type'), nullable=False),
    sa.Column('gstin', sa.String(length=15), nullable=True),
    sa.Column('pan', sa.String(length=10), nullable=True),
    sa.Column('state_code', sa.String(length=8), nullable=True),
    sa.Column('country_code', sa.CHAR(length=2), nullable=True),
    sa.Column('credit_days', sa.Integer(), nullable=True),
    sa.Column('credit_limit', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('phone', sa.String(length=32), nullable=True),
    sa.Column('source_key', sa.String(length=191), nullable=False),
    sa.Column('source_alter_id', sa.BigInteger(), nullable=True),
    sa.Column('origin', sa.Enum('live', 'backup', 'file', 'manual', name='origin'), nullable=False),
    sa.Column('raw_record_id', ID, nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('connection_id', ID, nullable=False),
    sa.Column('import_batch_id', ID, nullable=True),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.ForeignKeyConstraint(['connection_id'], ['ledgerbridge_system.connections.id'], ),
    sa.ForeignKeyConstraint(['entity_id'], ['ledgerbridge_accounting.entities.id'], ),
    sa.ForeignKeyConstraint(['import_batch_id'], ['ledgerbridge_system.import_batches.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('connection_id', 'source_key', name='uq_parties_source'),
    schema='ledgerbridge_accounting'
    )
    op.create_index('ix_parties_raw_record', 'parties', ['raw_record_id'], unique=False, schema='ledgerbridge_accounting')
    op.create_table('units',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('entity_id', ID, nullable=False),
    sa.Column('symbol', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('decimal_places', TINYINT, server_default='0', nullable=False),
    sa.Column('source_key', sa.String(length=191), nullable=False),
    sa.Column('source_alter_id', sa.BigInteger(), nullable=True),
    sa.Column('origin', sa.Enum('live', 'backup', 'file', 'manual', name='origin'), nullable=False),
    sa.Column('raw_record_id', ID, nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('connection_id', ID, nullable=False),
    sa.Column('import_batch_id', ID, nullable=True),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.ForeignKeyConstraint(['connection_id'], ['ledgerbridge_system.connections.id'], ),
    sa.ForeignKeyConstraint(['entity_id'], ['ledgerbridge_accounting.entities.id'], ),
    sa.ForeignKeyConstraint(['import_batch_id'], ['ledgerbridge_system.import_batches.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('connection_id', 'source_key', name='uq_units_source'),
    schema='ledgerbridge_accounting'
    )
    op.create_index('ix_units_raw_record', 'units', ['raw_record_id'], unique=False, schema='ledgerbridge_accounting')
    op.create_table('voucher_types',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('entity_id', ID, nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('base_type', sa.Enum('sales', 'purchase', 'payment', 'receipt', 'journal', 'contra', 'debit_note', 'credit_note', 'stock_journal', 'delivery_note', 'receipt_note', 'other', name='voucher_base_type'), nullable=False),
    sa.Column('is_accounting', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('is_inventory', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('source_key', sa.String(length=191), nullable=False),
    sa.Column('source_alter_id', sa.BigInteger(), nullable=True),
    sa.Column('origin', sa.Enum('live', 'backup', 'file', 'manual', name='origin'), nullable=False),
    sa.Column('raw_record_id', ID, nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('connection_id', ID, nullable=False),
    sa.Column('import_batch_id', ID, nullable=True),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.ForeignKeyConstraint(['connection_id'], ['ledgerbridge_system.connections.id'], ),
    sa.ForeignKeyConstraint(['entity_id'], ['ledgerbridge_accounting.entities.id'], ),
    sa.ForeignKeyConstraint(['import_batch_id'], ['ledgerbridge_system.import_batches.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('connection_id', 'source_key', name='uq_voucher_types_source'),
    schema='ledgerbridge_accounting'
    )
    op.create_index('ix_voucher_types_raw_record', 'voucher_types', ['raw_record_id'], unique=False, schema='ledgerbridge_accounting')
    op.create_table('user_entity_access',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('user_id', sa.CHAR(length=36), nullable=False),
    sa.Column('entity_id', ID, nullable=False),
    sa.Column('branch_id', ID, nullable=True),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.ForeignKeyConstraint(['branch_id'], ['ledgerbridge_accounting.branches.id'], ),
    sa.ForeignKeyConstraint(['entity_id'], ['ledgerbridge_accounting.entities.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['ledgerbridge_system.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'entity_id', 'branch_id', name='uq_user_entity_access'),
    schema='ledgerbridge_system'
    )
    op.create_table('validation_runs',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('sync_run_id', ID, nullable=True),
    sa.Column('import_batch_id', ID, nullable=True),
    sa.Column('entity_id', ID, nullable=False),
    sa.Column('started_at', TS, nullable=False),
    sa.Column('status', sa.Enum('running', 'passed', 'failed', name='validation_status'), nullable=False),
    sa.Column('checks_passed', sa.Integer(), nullable=False),
    sa.Column('checks_failed', sa.Integer(), nullable=False),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.ForeignKeyConstraint(['entity_id'], ['ledgerbridge_accounting.entities.id'], ),
    sa.ForeignKeyConstraint(['import_batch_id'], ['ledgerbridge_system.import_batches.id'], ),
    sa.ForeignKeyConstraint(['sync_run_id'], ['ledgerbridge_system.sync_runs.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='ledgerbridge_system'
    )
    op.create_table('items',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('entity_id', ID, nullable=False),
    sa.Column('item_group_id', ID, nullable=True),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('code', sa.String(length=64), nullable=True),
    sa.Column('unit_id', ID, nullable=True),
    sa.Column('hsn_code', sa.String(length=16), nullable=True),
    sa.Column('gst_rate', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('opening_qty', sa.Numeric(precision=20, scale=6), server_default='0', nullable=False),
    sa.Column('opening_value', sa.Numeric(precision=20, scale=4), server_default='0', nullable=False),
    sa.Column('source_key', sa.String(length=191), nullable=False),
    sa.Column('source_alter_id', sa.BigInteger(), nullable=True),
    sa.Column('origin', sa.Enum('live', 'backup', 'file', 'manual', name='origin'), nullable=False),
    sa.Column('raw_record_id', ID, nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('connection_id', ID, nullable=False),
    sa.Column('import_batch_id', ID, nullable=True),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.ForeignKeyConstraint(['connection_id'], ['ledgerbridge_system.connections.id'], ),
    sa.ForeignKeyConstraint(['entity_id'], ['ledgerbridge_accounting.entities.id'], ),
    sa.ForeignKeyConstraint(['import_batch_id'], ['ledgerbridge_system.import_batches.id'], ),
    sa.ForeignKeyConstraint(['item_group_id'], ['ledgerbridge_accounting.item_groups.id'], ),
    sa.ForeignKeyConstraint(['unit_id'], ['ledgerbridge_accounting.units.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('connection_id', 'source_key', name='uq_items_source'),
    schema='ledgerbridge_accounting'
    )
    op.create_index('ix_items_raw_record', 'items', ['raw_record_id'], unique=False, schema='ledgerbridge_accounting')
    op.create_table('ledgers',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('entity_id', ID, nullable=False),
    sa.Column('group_id', ID, nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('alias', sa.String(length=255), nullable=True),
    sa.Column('ledger_kind', sa.Enum('party', 'bank', 'cash', 'tax', 'stock', 'income', 'expense', 'asset', 'liability', 'equity', 'other', name='ledger_kind'), nullable=False),
    sa.Column('party_id', ID, nullable=True),
    sa.Column('standard_account_id', ID, nullable=True),
    sa.Column('mapping_status', sa.Enum('auto', 'suggested', 'confirmed', 'unmapped', name='mapping_status'), nullable=False),
    sa.Column('opening_balance', sa.Numeric(precision=20, scale=4), server_default='0', nullable=False),
    sa.Column('opening_balance_date', sa.Date(), nullable=True),
    sa.Column('currency_code', sa.CHAR(length=3), nullable=False),
    sa.Column('is_bill_wise', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('is_cost_centre_applicable', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('gstin', sa.String(length=15), nullable=True),
    sa.Column('source_key', sa.String(length=191), nullable=False),
    sa.Column('source_alter_id', sa.BigInteger(), nullable=True),
    sa.Column('origin', sa.Enum('live', 'backup', 'file', 'manual', name='origin'), nullable=False),
    sa.Column('raw_record_id', ID, nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('connection_id', ID, nullable=False),
    sa.Column('import_batch_id', ID, nullable=True),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.ForeignKeyConstraint(['connection_id'], ['ledgerbridge_system.connections.id'], ),
    sa.ForeignKeyConstraint(['currency_code'], ['ledgerbridge_accounting.currencies.code'], ),
    sa.ForeignKeyConstraint(['entity_id'], ['ledgerbridge_accounting.entities.id'], ),
    sa.ForeignKeyConstraint(['group_id'], ['ledgerbridge_accounting.account_groups.id'], ),
    sa.ForeignKeyConstraint(['import_batch_id'], ['ledgerbridge_system.import_batches.id'], ),
    sa.ForeignKeyConstraint(['party_id'], ['ledgerbridge_accounting.parties.id'], ),
    sa.ForeignKeyConstraint(['standard_account_id'], ['ledgerbridge_accounting.standard_accounts.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('connection_id', 'source_key', name='uq_ledgers_source'),
    schema='ledgerbridge_accounting'
    )
    op.create_index('ix_ledgers_entity_group', 'ledgers', ['entity_id', 'group_id'], unique=False, schema='ledgerbridge_accounting')
    op.create_index('ix_ledgers_entity_name', 'ledgers', ['entity_id', 'name'], unique=False, schema='ledgerbridge_accounting')
    op.create_index('ix_ledgers_raw_record', 'ledgers', ['raw_record_id'], unique=False, schema='ledgerbridge_accounting')
    op.create_table('vouchers',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('entity_id', ID, nullable=False),
    sa.Column('branch_id', ID, nullable=True),
    sa.Column('voucher_type_id', ID, nullable=False),
    sa.Column('voucher_number', sa.String(length=64), nullable=False),
    sa.Column('voucher_date', sa.Date(), nullable=False),
    sa.Column('reference_number', sa.String(length=128), nullable=True),
    sa.Column('reference_date', sa.Date(), nullable=True),
    sa.Column('party_id', ID, nullable=True),
    sa.Column('narration', sa.Text(), nullable=True),
    sa.Column('currency_code', sa.CHAR(length=3), nullable=False),
    sa.Column('exchange_rate', sa.Numeric(precision=20, scale=8), server_default='1', nullable=False),
    sa.Column('is_cancelled', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('is_optional', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('is_post_dated', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('source_key', sa.String(length=191), nullable=False),
    sa.Column('source_alter_id', sa.BigInteger(), nullable=True),
    sa.Column('origin', sa.Enum('live', 'backup', 'file', 'manual', name='origin'), nullable=False),
    sa.Column('raw_record_id', ID, nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('connection_id', ID, nullable=False),
    sa.Column('import_batch_id', ID, nullable=True),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.ForeignKeyConstraint(['branch_id'], ['ledgerbridge_accounting.branches.id'], ),
    sa.ForeignKeyConstraint(['connection_id'], ['ledgerbridge_system.connections.id'], ),
    sa.ForeignKeyConstraint(['currency_code'], ['ledgerbridge_accounting.currencies.code'], ),
    sa.ForeignKeyConstraint(['entity_id'], ['ledgerbridge_accounting.entities.id'], ),
    sa.ForeignKeyConstraint(['import_batch_id'], ['ledgerbridge_system.import_batches.id'], ),
    sa.ForeignKeyConstraint(['party_id'], ['ledgerbridge_accounting.parties.id'], ),
    sa.ForeignKeyConstraint(['voucher_type_id'], ['ledgerbridge_accounting.voucher_types.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('connection_id', 'source_key', name='uq_vouchers_source'),
    schema='ledgerbridge_accounting'
    )
    op.create_index('ix_vouchers_entity_date', 'vouchers', ['entity_id', 'voucher_date'], unique=False, schema='ledgerbridge_accounting')
    op.create_index('ix_vouchers_entity_type_date', 'vouchers', ['entity_id', 'voucher_type_id', 'voucher_date'], unique=False, schema='ledgerbridge_accounting')
    op.create_index('ix_vouchers_party_date', 'vouchers', ['party_id', 'voucher_date'], unique=False, schema='ledgerbridge_accounting')
    op.create_index('ix_vouchers_raw_record', 'vouchers', ['raw_record_id'], unique=False, schema='ledgerbridge_accounting')
    op.create_table('validation_issues',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('validation_run_id', ID, nullable=False),
    sa.Column('check_code', sa.String(length=64), nullable=False),
    sa.Column('severity', sa.Enum('error', 'warning', 'info', name='issue_severity'), nullable=False),
    sa.Column('object_type', sa.String(length=64), nullable=True),
    sa.Column('object_id', sa.String(length=64), nullable=True),
    sa.Column('expected_value', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('actual_value', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('resolved_at', TS, nullable=True),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.ForeignKeyConstraint(['validation_run_id'], ['ledgerbridge_system.validation_runs.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='ledgerbridge_system'
    )
    op.create_table('inventory_lines',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('voucher_id', ID, nullable=False),
    sa.Column('entity_id', ID, nullable=False),
    sa.Column('voucher_date', sa.Date(), nullable=False),
    sa.Column('line_no', sa.Integer(), nullable=False),
    sa.Column('item_id', ID, nullable=False),
    sa.Column('godown_id', ID, nullable=True),
    sa.Column('quantity', sa.Numeric(precision=20, scale=6), nullable=False),
    sa.Column('unit_id', ID, nullable=True),
    sa.Column('rate', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('amount', sa.Numeric(precision=20, scale=4), nullable=False),
    sa.Column('discount_pct', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('batch_name', sa.String(length=255), nullable=True),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.ForeignKeyConstraint(['entity_id'], ['ledgerbridge_accounting.entities.id'], ),
    sa.ForeignKeyConstraint(['godown_id'], ['ledgerbridge_accounting.godowns.id'], ),
    sa.ForeignKeyConstraint(['item_id'], ['ledgerbridge_accounting.items.id'], ),
    sa.ForeignKeyConstraint(['unit_id'], ['ledgerbridge_accounting.units.id'], ),
    sa.ForeignKeyConstraint(['voucher_id'], ['ledgerbridge_accounting.vouchers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    schema='ledgerbridge_accounting'
    )
    op.create_table('voucher_lines',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('voucher_id', ID, nullable=False),
    sa.Column('entity_id', ID, nullable=False),
    sa.Column('voucher_date', sa.Date(), nullable=False),
    sa.Column('line_no', sa.Integer(), nullable=False),
    sa.Column('ledger_id', ID, nullable=False),
    sa.Column('amount', sa.Numeric(precision=20, scale=4), nullable=False),
    sa.Column('amount_fc', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('is_party_line', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('is_effective', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.ForeignKeyConstraint(['entity_id'], ['ledgerbridge_accounting.entities.id'], ),
    sa.ForeignKeyConstraint(['ledger_id'], ['ledgerbridge_accounting.ledgers.id'], ),
    sa.ForeignKeyConstraint(['voucher_id'], ['ledgerbridge_accounting.vouchers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    schema='ledgerbridge_accounting'
    )
    op.create_index('ix_voucher_lines_entity_ledger_date', 'voucher_lines', ['entity_id', 'ledger_id', 'voucher_date'], unique=False, schema='ledgerbridge_accounting')
    op.create_index('ix_voucher_lines_voucher', 'voucher_lines', ['voucher_id'], unique=False, schema='ledgerbridge_accounting')
    op.create_table('bill_allocations',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('voucher_line_id', ID, nullable=False),
    sa.Column('party_id', ID, nullable=True),
    sa.Column('bill_type', sa.Enum('new_ref', 'against_ref', 'advance', 'on_account', name='bill_type'), nullable=False),
    sa.Column('bill_name', sa.String(length=255), nullable=True),
    sa.Column('bill_date', sa.Date(), nullable=True),
    sa.Column('due_date', sa.Date(), nullable=True),
    sa.Column('amount', sa.Numeric(precision=20, scale=4), nullable=False),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.ForeignKeyConstraint(['party_id'], ['ledgerbridge_accounting.parties.id'], ),
    sa.ForeignKeyConstraint(['voucher_line_id'], ['ledgerbridge_accounting.voucher_lines.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    schema='ledgerbridge_accounting'
    )
    op.create_table('line_cost_allocations',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('voucher_line_id', ID, nullable=False),
    sa.Column('cost_centre_id', ID, nullable=False),
    sa.Column('amount', sa.Numeric(precision=20, scale=4), nullable=False),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.ForeignKeyConstraint(['cost_centre_id'], ['ledgerbridge_accounting.cost_centres.id'], ),
    sa.ForeignKeyConstraint(['voucher_line_id'], ['ledgerbridge_accounting.voucher_lines.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    schema='ledgerbridge_accounting'
    )
    op.create_table('line_dimensions',
    sa.Column('voucher_line_id', ID, nullable=False),
    sa.Column('dimension_value_id', ID, nullable=False),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.ForeignKeyConstraint(['dimension_value_id'], ['ledgerbridge_accounting.dimension_values.id'], ),
    sa.ForeignKeyConstraint(['voucher_line_id'], ['ledgerbridge_accounting.voucher_lines.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('voucher_line_id', 'dimension_value_id'),
    schema='ledgerbridge_accounting'
    )
    op.create_table('tax_lines',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('voucher_id', ID, nullable=False),
    sa.Column('voucher_line_id', ID, nullable=True),
    sa.Column('tax_type', sa.Enum('cgst', 'sgst', 'igst', 'cess', 'tds', 'tcs', 'vat', 'other', name='tax_type'), nullable=False),
    sa.Column('rate', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('taxable_amount', sa.Numeric(precision=20, scale=4), nullable=True),
    sa.Column('tax_amount', sa.Numeric(precision=20, scale=4), nullable=False),
    sa.Column('hsn_code', sa.String(length=16), nullable=True),
    sa.Column('created_at', TS, nullable=False),
    sa.Column('updated_at', TS, nullable=False),
    sa.ForeignKeyConstraint(['voucher_id'], ['ledgerbridge_accounting.vouchers.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['voucher_line_id'], ['ledgerbridge_accounting.voucher_lines.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    schema='ledgerbridge_accounting'
    )
    op.create_foreign_key('fk_raw_records_import_batch', 'raw_records', 'import_batches', ['import_batch_id'], ['id'], source_schema='ledgerbridge_source', referent_schema='ledgerbridge_system')
    op.create_foreign_key('fk_connections_agent', 'connections', 'agents', ['agent_id'], ['id'], source_schema='ledgerbridge_system', referent_schema='ledgerbridge_system')


def downgrade() -> None:
    op.drop_constraint('fk_connections_agent', 'connections', schema='ledgerbridge_system', type_='foreignkey')
    op.drop_constraint('fk_raw_records_import_batch', 'raw_records', schema='ledgerbridge_source', type_='foreignkey')
    op.drop_table('tax_lines', schema='ledgerbridge_accounting')
    op.drop_table('line_dimensions', schema='ledgerbridge_accounting')
    op.drop_table('line_cost_allocations', schema='ledgerbridge_accounting')
    op.drop_table('bill_allocations', schema='ledgerbridge_accounting')
    op.drop_table('voucher_lines', schema='ledgerbridge_accounting')
    op.drop_table('inventory_lines', schema='ledgerbridge_accounting')
    op.drop_table('validation_issues', schema='ledgerbridge_system')
    op.drop_table('vouchers', schema='ledgerbridge_accounting')
    op.drop_table('ledgers', schema='ledgerbridge_accounting')
    op.drop_table('items', schema='ledgerbridge_accounting')
    op.drop_table('validation_runs', schema='ledgerbridge_system')
    op.drop_table('user_entity_access', schema='ledgerbridge_system')
    op.drop_table('voucher_types', schema='ledgerbridge_accounting')
    op.drop_table('units', schema='ledgerbridge_accounting')
    op.drop_table('parties', schema='ledgerbridge_accounting')
    op.drop_table('item_groups', schema='ledgerbridge_accounting')
    op.drop_table('godowns', schema='ledgerbridge_accounting')
    op.drop_table('cost_centres', schema='ledgerbridge_accounting')
    op.drop_table('account_groups', schema='ledgerbridge_accounting')
    op.drop_table('sync_markers', schema='ledgerbridge_system')
    op.drop_table('import_batches', schema='ledgerbridge_system')
    op.drop_table('file_layouts', schema='ledgerbridge_system')
    op.drop_table('audit_log', schema='ledgerbridge_system')
    op.drop_table('financial_years', schema='ledgerbridge_accounting')
    op.drop_table('entity_sources', schema='ledgerbridge_accounting')
    op.drop_table('dimension_values', schema='ledgerbridge_accounting')
    op.drop_table('branches', schema='ledgerbridge_accounting')
    op.drop_table('user_roles', schema='ledgerbridge_system')
    op.drop_table('role_permissions', schema='ledgerbridge_system')
    op.drop_table('masking_rules', schema='ledgerbridge_system')
    op.drop_table('exchange_rates', schema='ledgerbridge_accounting')
    op.drop_table('entities', schema='ledgerbridge_accounting')
    op.drop_table('users', schema='ledgerbridge_system')
    op.drop_table('settings', schema='ledgerbridge_system')
    op.drop_table('roles', schema='ledgerbridge_system')
    op.drop_table('permissions', schema='ledgerbridge_system')
    op.drop_table('kpi_definitions', schema='ledgerbridge_system')
    op.drop_table('ai_query_log', schema='ledgerbridge_system')
    op.drop_table('agents', schema='ledgerbridge_system')
    op.drop_table('standard_accounts', schema='ledgerbridge_accounting')
    op.drop_table('dimensions', schema='ledgerbridge_accounting')
    op.drop_table('currencies', schema='ledgerbridge_accounting')
