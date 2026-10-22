"""Generates docs/database/schema-reference.md from the database models (core/models).

    python -m devtools.schema_reference            # write the document
    python -m devtools.schema_reference --check    # exit 1 if it is out of date

Every table and column comes from the SQLAlchemy models, so the reference always matches
the code: types (as MySQL sees them), nullability, primary, unique and foreign keys,
indexes, relationships both ways. What each table is for and how it is filled is written
below (TABLES); a column's meaning comes, in order, from COLUMNS below, the comment beside
the column in core/models, the column notes in docs/schema.md, the common columns
(COMMON), and finally its kind (a foreign key, a flag, a timestamp). `./dev.ps1 diagrams`
runs this with the diagram generator; a test fails when the document is stale.

Developer tool (devtools/): never imported by product code.
"""

import argparse
import re
import sys
from pathlib import Path

from sqlalchemy import Table
from sqlalchemy.dialects import mysql

from core.models import Base
from core.models.schemas import ACCOUNTING, REPORTING, SOURCE, SYSTEM
from devtools.diagrams import AREAS, SCHEMA_GROUPS, USERS

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "database" / "schema-reference.md"
MODELS = ROOT / "data-plane" / "core" / "models"
SCHEMA_MD = ROOT / "docs" / "schema.md"

DATABASES = (
    (SOURCE, "Raw layer: every record exactly as the source sent it (ADR-005). Written only "
             "by connectors through the sync; the transform reads it."),
    (ACCOUNTING, "Canonical model: companies, chart of accounts, masters and transactions in "
                 "one shape for every source. Written by the transform; read by validation, "
                 "reports and (later) the reporting layer."),
    (REPORTING, "Semantic layer for reports and AI (M6): views and aggregate tables. Empty "
                "until M6; the only database the AI user can read (AI-003)."),
    (SYSTEM, "Running the platform: connections, sync runs and progress, validation, alerts, "
             "users, roles, audit and AI logs, configuration."),
)  # fmt: skip

# What each table is for, and how it is filled.
TABLES: dict[str, tuple[str, str]] = {
    "raw_records": ("Every object fetched from a source, exactly as received (XML for Tally), "
                    "one row per version.",
                    "Sync (connector -> RawStore): a new row only when the payload changed "
                    "(hash); `process_status` tracks the transform."),
    "entities": ("A company in the platform (one per source company).",
                 "Transform, from the source's company record, on the first sync."),
    "entity_sources": ("Which source company (by its key, Tally's GUID) belongs to which "
                       "entity, on which connection.", "Transform, with the entity."),
    "branches": ("Branches of an entity (planned).", "Not filled yet."),
    "financial_years": ("Financial years of an entity (planned).", "Not filled yet."),
    "currencies": ("Currencies by ISO code.", "Seeded (INR); foreign currencies in M4b (FX-001)."),
    "exchange_rates": ("Exchange rates by date (outline; redesigned for FX-003).",
                       "Not filled yet."),
    "standard_accounts": ("The standard chart of accounts used to compare and combine companies "
                          "(RPT-006).", "Seeded by a migration."),
    "account_groups": ("The source's group tree (Tally groups), per entity, as kept there.",
                       "Transform, from group masters; renamed reserved groups keep their "
                       "reserved name as an alias."),
    "ledgers": ("The source's ledgers, per entity, with their group, kind, standard account, "
                "opening balance as at the books' beginning and tax type.",
                "Transform, from ledger masters fetched for a period starting on the books' "
                "beginning."),
    "parties": ("Customers and vendors (the ledgers under Sundry Debtors / Creditors), with "
                "GST, PAN and contact details (sensitive: AI-015).",
                "Transform, with their ledgers."),
    "voucher_types": ("The source's voucher types and the standard type each derives from; "
                      "whether its vouchers post to the books and move stock.",
                      "Transform, from voucher type masters (type tree resolved, ADR-027)."),
    "item_groups": ("Stock groups.", "Transform, from stock group masters."),
    "units": ("Units of measure.", "Transform, from unit masters."),
    "items": ("Stock items with their opening quantity and value.",
              "Transform, from stock item masters (as at the books' beginning)."),
    "godowns": ("Godowns (locations) and whose stock they hold (`holding`, ADR-031).",
                "Transform, from godown masters."),
    "cost_centres": ("Cost centres and their categories.", "Transform, from cost centre masters."),
    "dimensions": ("User-defined reporting dimensions (DAT-005), e.g. a promoted UDF.",
                   "`promote-field`, from the field catalogue."),
    "dimension_values": ("The values of a dimension.", "Transform, for promoted fields."),
    "source_fields": ("Field catalogue (ADR-025): every source field that has no column, kept "
                      "in `extra`, with counts and an inferred type.", "Transform."),
    "stock_values": ("The source's own stock value as of a date (DAT-013, ADR-040): the "
                     "total its Profit and Loss uses, and by stock group and godown.",
                     "Validation (as-of date, year ends) and `./dev.ps1 statements` (every "
                     "month end and year end)."),
    "fx_revaluation_snapshots": ("Each foreign-currency ledger's balance as the source reports "
                                 "it (revalued at current rates) against its book value "
                                 "(FX-004, ADR-037, ADR-040).",
                                 "Validation and `./dev.ps1 statements`, for each date."),
    "statement_lines": ("Trial Balance, Profit & Loss and Balance Sheet lines, ours and the "
                        "source's, as of each stored date (RPT-012, ADR-040); the views "
                        "v_trial_balance, v_profit_loss, v_balance_sheet and "
                        "v_statement_check read them.",
                        "Validation and `./dev.ps1 statements` (core/statements.py)."),
    "vouchers": ("Vouchers (transactions) with their type, number, date, party and flags.",
                 "Transform, from voucher records; replaced as a whole with their child rows "
                 "(schema.md 8 rule 7)."),
    "voucher_lines": ("The double-entry lines of each voucher (debit +, credit −); "
                      "`is_effective` says whether a line counts in the books.",
                      "Transform, with the voucher."),
    "line_dimensions": ("A voucher line's value for each dimension.",
                        "Transform, with the voucher."),
    "line_cost_allocations": ("Cost centre allocations of a line.", "Transform, with the voucher."),
    "bill_allocations": ("Bill-wise allocations of a line (receivables and payables ageing).",
                         "Transform, with the voucher."),
    "inventory_lines": ("Stock movements of a voucher (in +, out −) by item, godown and batch; "
                        "`stock_quantity` is what moves stock (tracked lines move nothing).",
                        "Transform, with the voucher."),
    "tax_lines": ("Tax amounts of a voucher (GST, TDS, ...) from lines posted to tax ledgers.",
                  "Transform, with the voucher."),
    "sources": ("Registered connector types (e.g. `tally`).", "Seeded on first use."),
    "agents": ("Connector agents near on-premise sources (Phase 1b).", "Not filled yet."),
    "connections": ("Each configured connection: source, origin, companies, settings, status.",
                    "`connect`; status by `connect -Activate / -Paused`."),
    "sync_markers": ("The last AlterID stored per connection, company and object type "
                     "(incremental syncs).", "Sync."),
    "sync_runs": ("Every sync, deletion check and transform run with its status and counts "
                  "(SYN-005).", "Sync, deletion check, transform."),
    "sync_logs": ("Output lines of a background job, for `sync watch` (ADR-024).",
                  "Background jobs."),
    "sync_checkpoints": ("Chunks of a full sync fetched and stored, so an interrupted one "
                         "resumes (ADR-022).", "Sync."),
    "sync_slow_periods": ("Months the source couldn't deliver in one request; later runs split "
                          "them directly.", "Sync."),
    "sync_unverified_ranges": ("Date ranges whose records couldn't be proven complete "
                               "(ADR-023).", "Sync."),
    "import_batches": ("Backup or file imports (IMP-003, IMP-004).", "Imports (later)."),
    "file_layouts": ("Saved CSV/TXT column mappings (CON-003).", "Not filled yet."),
    "validation_runs": ("Each validation of an entity as of a date, with counts (VAL-001).",
                        "Validation after every sync and on `validate`."),
    "validation_issues": ("Each failed check of a run, with its code and the two figures; "
                          "resolved when a later run no longer finds it.", "Validation."),
    "alerts": ("In-app alerts: one open per connection and kind (SYN-006, ADR-019).",
               "Sync and validation."),
    "users": ("Users (same id as the control plane); local password only with AUTH_MODE=local.",
              "M5."),
    "roles": ("Roles.", "M5 (seeded defaults)."),
    "permissions": ("Permission codes, e.g. `validation.view`.", "M5 (seeded)."),
    "role_permissions": ("Which role has which permission.", "M5."),
    "user_roles": ("Which user has which role.", "M5."),
    "user_entity_access": ("Which entities (and branches) a user may see (ACC-002).", "M5."),
    "masking_rules": ("Masking per role for sensitive fields (ACC-003, AI-015).", "M5 / M8."),
    "audit_log": ("Append-only audit trail (AUD-001).", "API and workers (M5)."),
    "ai_query_log": ("One row per AI question (AI-007).", "M8."),
    "kpi_definitions": ("Business health indicators and thresholds (RPT-002).", "M6."),
    "settings": ("Key-value settings.", "Configuration."),
}  # fmt: skip

# Columns whose meaning isn't obvious from elsewhere: (table, column) -> meaning.
COLUMNS: dict[tuple[str, str], str] = {
    ("raw_records", "payload"): "The record exactly as received (re-serialised XML).",
    ("raw_records", "payload_hash"): "SHA-256 of the payload: an unchanged record isn't "
                                     "stored again.",
    ("raw_records", "process_status"): "pending / processed / failed / skipped (superseded).",
    ("raw_records", "process_error"): "Why the transform failed: error type and a short "
                                      "message, never SQL.",
    ("vouchers", "voucher_number"): "The source's voucher number (up to 255 characters).",
    ("vouchers", "reference_number"): "The source's reference (e.g. the supplier's invoice "
                                      "number).",
    ("raw_records", "object_type"): "group, ledger, voucher_type, voucher, stock_item, ...",
    ("ledgers", "ledger_kind"): "party, bank, cash, tax, stock, ... (from the reserved group).",
    ("ledgers", "mapping_status"): "auto (a standard account was found) or unmapped.",
    ("ledgers", "tax_type"): "cgst, sgst, igst, cess, tds, tcs, vat for tax ledgers.",
    ("vouchers", "is_post_dated"): "The source marks it post-dated; it counts from its date.",
    ("voucher_lines", "is_effective"): "Counts in the books: not cancelled, optional or "
                                       "deleted, and of a type that posts.",
    ("inventory_lines", "stock_quantity"): "What the line moves in stock: the quantity "
                                           "less the part tracked to a note.",
    ("godowns", "holding"): "own / ours_with_third_party (a job worker's) / third_party_with_us.",
    ("validation_issues", "check_code"): "The check (see the error catalogue, LB-VAL-xxx).",
    ("stock_values", "scope"): "total (what the source's profit uses), stock_group or godown.",
    ("stock_values", "integrated"): "Whether the source integrates accounts with inventory "
                                    "(total rows).",
    ("fx_revaluation_snapshots", "unrealised_gain_loss"): "Book value less revalued value "
                                                          "(a debit is an unrealised loss).",
    ("statement_lines", "figures"): "ours (built here) or source (the source's own report).",
    ("statement_lines", "match_key"): "The label as both sides are compared.",
    ("statement_lines", "level"): "main, sub (inside a block) or detail (ours only, never "
                                  "compared).",
    ("validation_runs", "thorough"): "Whether the source's controls (counts, stock, "
                                     "bills, year ends) were compared.",
}  # fmt: skip

COMMON = {
    "id": "Row id.",
    "created_at": "When the row was created (UTC).",
    "updated_at": "When the row was last changed (UTC).",
    "connection_id": "The connection the row came from.",
    "entity_id": "The entity (company) the row belongs to.",
    "import_batch_id": "The import it came from, for imported data.",
    "source_key": "The source's own key (Tally: GUID); unique per connection.",
    "source_alter_id": "The source's change counter (Tally: AlterID) when last stored.",
    "origin": "live or backup (IMP-004).",
    "raw_record_id": "The raw record it was transformed from.",
    "is_deleted": "Deleted in the source (soft delete; kept for history).",
    "extra": "Source fields with no column, as JSON (ADR-025).",
    "name": "Name as the source keeps it.",
    "code": "Short stable code.",
    "status": "Current state.",
    "parent_id": "The parent row in the same table (a tree).",
    "sync_run_id": "The sync run it belongs to.",
    "source_entity_key": "The source company's key (Tally: company GUID).",
    "object_type": "Kind of source object.",
    "is_active": "Whether it is in use.",
    "gstin": "GST registration number.",
    "state_code": "GST state code.",
    "currency_code": "Currency (ISO code).",
    "decimal_places": "Decimals shown.",
    "voucher_date": "The voucher's date (denormalised for fast period queries).",
    "line_no": "Position of the line in its voucher.",
    "amount": "Amount in the base currency, canonical sign (debit +, credit −).",
    "rate": "Rate.",
    "resolved_at": "When it was resolved (NULL while open).",
    "started_at": "When it started.",
    "finished_at": "When it finished.",
    "email": "E-mail address.",
}  # fmt: skip


def _model_comments() -> dict[tuple[str, str], str]:
    """Comments written beside columns in core/models: (table, column) -> comment."""
    out = {}
    for path in MODELS.glob("*.py"):
        table = None
        for line in path.read_text(encoding="utf-8").splitlines():
            if m := re.match(r'\s+__tablename__ = "(\w+)"', line):
                table = m.group(1)
            elif table and (m := re.match(r"\s+(\w+): Mapped\[.*#\s*(.+)$", line)):
                out[(table, m.group(1))] = m.group(2).strip()
    return out


def _schema_notes() -> dict[tuple[str, str], str]:
    """Column notes in docs/schema.md's per-table sections: (table, column) -> note."""
    out = {}
    for block in re.split(r"\n#### ", SCHEMA_MD.read_text(encoding="utf-8")):
        m = re.match(r"`ledgerbridge_\w+\.(\w+)`", block)
        if not m:
            continue
        for column, note in re.findall(r"^\| (\w+) \| [^|]+ \| ([^|]*) \|", block, re.M):
            if note.strip() and column not in ("Column", "Table"):
                out[(m.group(1), column)] = note.strip()
    return out


def _words(name: str) -> str:
    return name.replace("_", " ")


def _meaning(table: Table, column: object, comments: dict, notes: dict) -> str:
    name = column.name  # type: ignore[attr-defined]
    key = (table.name, name)
    for source in (COLUMNS, comments, notes):
        if key in source:
            return source[key].replace("|", "/")
    if name in COMMON:
        return COMMON[name]
    if column.foreign_keys:  # type: ignore[attr-defined]
        target = next(iter(column.foreign_keys)).column.table.name  # type: ignore[attr-defined]
        return f"Refers to `{target}`."
    if name.startswith(("is_", "has_")):
        return f"Whether {_words(name.split('_', 1)[1])}."
    if name.endswith("_at"):
        return f"When: {_words(name[:-3])}."
    return _words(name).capitalize() + "."


def _type(column: object) -> str:
    try:
        text = column.type.compile(dialect=mysql.dialect())  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - a type MySQL can't compile: its Python name
        text = type(column.type).__name__.upper()  # type: ignore[attr-defined]
    return text.replace("|", "/")


def _table_section(table: Table, comments: dict, notes: dict, referenced: dict) -> list[str]:
    purpose, filled = TABLES.get(table.name, ("", ""))
    lines = [f"### `{table.schema}.{table.name}`", ""]
    if purpose:
        lines += [f"**Purpose:** {purpose}", "", f"**Filled by:** {filled}", ""]
    unique = {c.name for c in table.columns if c.unique}
    for constraint in table.constraints:
        if constraint.__class__.__name__ == "UniqueConstraint":
            unique.update(c.name for c in constraint.columns)  # type: ignore[attr-defined]
    lines += ["| Column | Type | Null | Key | Meaning |", "| --- | --- | --- | --- | --- |"]
    for column in table.columns:
        keys = []
        if column.primary_key:
            keys.append("PK")
        if column.foreign_keys:
            keys.append("FK")
        if column.name in unique and not column.primary_key:
            keys.append("UK")
        lines.append(
            f"| `{column.name}` | {_type(column)} | {'yes' if column.nullable else 'no'} | "
            f"{', '.join(keys)} | {_meaning(table, column, comments, notes)} |"
        )
    lines.append("")
    constraints = [
        "unique (" + ", ".join(c.name for c in con.columns) + ")"  # type: ignore[attr-defined]
        for con in table.constraints
        if con.__class__.__name__ == "UniqueConstraint"
    ]
    indexes = [
        f"{'unique ' if i.unique else ''}index `{i.name}` ("
        + ", ".join(c.name for c in i.columns)
        + ")"
        for i in sorted(table.indexes, key=lambda i: i.name or "")
    ]
    if constraints or indexes:
        lines += ["**Keys and indexes:** " + "; ".join([*constraints, *indexes]) + ".", ""]
    links = []
    for column in table.columns:
        for fk in column.foreign_keys:
            target = fk.column.table
            delete = f", on delete {fk.ondelete.lower()}" if fk.ondelete else ""
            links.append(f"`{column.name}` → `{target.name}.{fk.column.name}`{delete}")
    if links:
        lines += ["**Refers to:** " + "; ".join(links) + ".", ""]
    if referenced.get(table.name):
        listed = ", ".join(f"`{t}`" for t in sorted(referenced[table.name]))
        lines += [f"**Referred to by:** {listed}.", ""]
    return lines


def _image(name: str, alt: str) -> str:
    return f"[![{alt}](../diagrams/{name}.png)](../diagrams/{name}.svg)"


def generate() -> str:
    tables = {t.name: t for t in Base.metadata.sorted_tables}
    missing = sorted(set(tables) - set(TABLES))
    if missing:
        raise ValueError(f"tables without a description in TABLES: {', '.join(missing)}")
    comments, notes = _model_comments(), _schema_notes()
    referenced: dict[str, set[str]] = {}
    for table in tables.values():
        for column in table.columns:
            for fk in column.foreign_keys:
                referenced.setdefault(fk.column.table.name, set()).add(table.name)
    out = [
        "<!-- Generated by `python -m devtools.schema_reference` from core/models "
        "(./dev.ps1 diagrams): don't edit by hand. -->",
        "",
        "# Database schema reference",
        "",
        "Every database, table and column of the client-hosted data plane (MySQL 8), "
        "generated from the code. For the design and its reasons see "
        "[schema.md](../schema.md) and the decision log in "
        "[architecture.md](../architecture.md); for the conversion and validation rules see "
        "[the rulebook](../rules/validation-and-conversion-rules.md).",
        "",
        f"{len(tables)} tables, {sum(len(t.columns) for t in tables.values())} columns.",
        "",
        "**Conventions.** Amounts are `DECIMAL(20,4)` in the base currency with the "
        "**canonical sign**: debit positive, credit negative (schema.md 1, 7.1). Every "
        "accounting table carries its source tracking columns (`connection_id`, `source_key`, "
        "`source_alter_id`, `origin`, `import_batch_id`, `raw_record_id`). Rows deleted in the "
        "source are kept with `is_deleted` (soft delete). `PK` primary key, `FK` foreign key, "
        "`UK` part of a unique key.",
        "",
        "## 1. The four databases",
        "",
        "| Database | What it holds | Tables |",
        "| --- | --- | --- |",
    ]
    for schema, text in DATABASES:
        count = sum(1 for t in tables.values() if t.schema == schema)
        out.append(f"| `{schema}` | {text} | {count} |")
    out += [
        "",
        _image("schema-databases", "The four databases and the database users"),
        "",
        "## 2. Database users and their rights",
        "",
        "Created by `deploy/mysql/init/01-schemas.sh` (schema.md 2.1). Each user has only the "
        "rights it needs; the AI can read the reporting layer and nothing else.",
        "",
        "| User | Used by | Rights | Databases |",
        "| --- | --- | --- | --- |",
    ]
    for code, label, rights, databases in USERS:
        used = label.split("<br/>", 1)[1] if "<br/>" in label else label
        out.append(
            f"| `{code}` | {used.replace('<br/>', ' ')} | {rights.replace('<br/>', ' ')} | "
            + ", ".join(f"`{d}`" for d in databases)
            + " |"
        )
    out += [
        "",
        "## 3. Diagrams",
        "",
        "How to read them: [docs/diagrams/README.md](../diagrams/README.md).",
        "",
        "**Overview** (keys only)",
        "",
        _image("er-overview", "ER overview"),
        "",
    ]
    for area in AREAS[:-1]:
        out += [f"**{area.title}**", "", _image(area.file, area.title), ""]
    out += [
        "**Data flow, level 0** (the platform and what it talks to)",
        "",
        _image("dataflow-context", "Data flow level 0"),
        "",
        "**Data flow, level 1** (inside the data plane)",
        "",
        _image("dataflow-level1", "Data flow level 1"),
        "",
        "## 4. Tables",
        "",
    ]
    for schema, title, names in SCHEMA_GROUPS:
        out += [f"## `{schema}`: {title}", ""]
        for name in names:
            out += _table_section(tables[name], comments, notes, referenced)
    out += [
        f"## `{REPORTING}`",
        "",
        "No tables yet: the reporting views and aggregate tables are built in M6 (designed in "
        "schema.md Section 6).",
        "",
    ]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m devtools.schema_reference")
    parser.add_argument("--check", action="store_true", help="exit 1 if out of date")
    args = parser.parse_args(argv)
    content = generate()
    current = OUT.read_text(encoding="utf-8").replace("\r\n", "\n") if OUT.exists() else None
    if args.check:
        if current != content:
            print("Out of date: docs/database/schema-reference.md. Run ./dev.ps1 diagrams.",
                  file=sys.stderr)  # fmt: skip
            return 1
        print("The schema reference is up to date.")
        return 0
    if current != content:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(content, encoding="utf-8", newline="\n")
        print(f"Wrote {OUT.relative_to(ROOT)}")
    else:
        print("The schema reference is up to date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
