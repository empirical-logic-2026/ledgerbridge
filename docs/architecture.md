# Architecture: Accounting Data Integration & Analytics Platform

| Field | Value |
| --- | --- |
| Version | 0.32 (Draft) |
| Date | 2026-10-16 |
| Related | `docs/requirements.md`, `CLAUDE.md` |

---

## 1. Design principles

1. **Data sovereignty.** The provider stores only logins, user-to-client mapping and licences. All client data lives and is processed in the client's own environment (PM-003 to PM-006).
2. **Read-only towards sources.** The platform never writes to Tally, Zoho, banks or upstream systems (CON-008).
3. **Pluggable connectors.** Every data source is an adapter behind one interface; the core never depends on a specific source (CON-001, MNT-002).
4. **One codebase, many clients.** Client differences are configuration, never forks (MNT-001).
5. **Secure by default.** Encryption, least privilege, signed releases, no telemetry (Section 5 of requirements).
6. **Verifiable numbers.** Every figure, including AI answers, can be traced to source records (AI-002, RPT-007).

## 2. System overview

The system has three deployable parts:

| Part | Hosted by | Holds client data? | Purpose |
| --- | --- | --- | --- |
| **Control plane** | Provider | **No** | Login, MFA, licence checks, user-to-client mapping, serving the signed dashboard bundle. |
| **Client deployment (data plane)** | Client (own cloud account by default, or office server) | Yes | Database, connectors, sync, validation, reporting API, AI layer, audit log. |
| **Connector agent** | Client (on machine near Tally or other on-prem sources) | Transiently | Reads on-prem sources and pushes changes outbound to the client deployment. |

```mermaid
flowchart LR
    subgraph Provider["Provider infrastructure (no client data)"]
        CP["Control plane<br/>Auth · MFA · Licences"]
        FE["Signed React dashboard bundle"]
    end

    subgraph Browser["User's browser"]
        UI["Dashboard (React)"]
    end

    subgraph Client["Client environment (client cloud or office server)"]
        API["Data plane API (FastAPI)"]
        W["Sync & job workers"]
        DB[("MySQL 8<br/>raw · canonical · reporting")]
        VS[("Vector store")]
        AI["AI service"]
        LLM["Model provider<br/>client cloud (Bedrock/Vertex)<br/>or local model"]
        AGT["Connector agent"]
        TALLY["Tally / on-prem sources"]
    end

    CLOUD["Cloud sources<br/>Zoho, bank APIs"]

    UI -- "1. login" --> CP
    CP -- "2. signed token + deployment URL" --> UI
    FE -. "app code" .-> UI
    UI -- "3. all data requests" --> API
    API --> DB
    API --> AI
    AI --> DB
    AI --> VS
    AI --> LLM
    W --> DB
    TALLY --> AGT
    AGT -- "outbound HTTPS" --> W
    CLOUD --> W
```

The data flow as built, with planned parts dashed ([diagrams/README.md](diagrams/README.md) explains all diagrams; regenerate with `./dev.ps1 diagrams`):

[![Data flow level 0](diagrams/dataflow-context.png)](diagrams/dataflow-context.svg)

[![Data flow level 1](diagrams/dataflow-level1.png)](diagrams/dataflow-level1.svg)

## 3. Control plane

**Responsibilities:** user accounts, password hashing, MFA, login, token issuance, licence status, client registry (client ID → deployment URL), platform admin console, hosting the signed frontend bundle.

**Stores only:**

- `clients` — client ID, name, licence status, deployment URL, token-signing settings.
- `users` — user ID, email, password hash, MFA secret (encrypted), client ID, status.
- `auth_events` — security events only (login success/failure, lockouts), no business activity.

**Does not store:** roles, entity permissions, connection details, any accounting data, report or AI activity. Those live in the client deployment.

**Token flow:**

1. User logs in at the control plane (password + MFA).
2. Control plane checks the licence and issues a short-lived signed JWT (e.g. 15 minutes, refreshable) containing user ID, client ID and audience = that client's deployment.
3. Browser calls the client deployment directly with the token.
4. Client deployment verifies the signature using the control plane's published public keys (JWKS), then applies its own local roles and permissions.

## 4. Client deployment (data plane)

### 4.1 Components

| Component | Technology | Role |
| --- | --- | --- |
| API | Python, FastAPI | Reporting, admin, connections, AI endpoints; token verification; authorization. |
| Workers | Python, Celery (or equivalent) + Redis | Sync jobs, imports, validation, scheduled reports, alerts. |
| Database | MySQL 8 | All accounting data, local roles/permissions, audit log. |
| Vector store | Qdrant (self-hosted) | Embeddings for schema docs, business definitions, uploaded documents. |
| AI service | Python module within the API/workers | Text-to-SQL, explanations, insights; provider abstraction. |
| File storage | Local volume or client's object storage | Raw uploaded files, backup files, (later) scanned documents. |
| Reverse proxy | Caddy or Nginx | TLS termination, CORS limited to the dashboard origin. |

### 4.2 Data layers

| Layer | MySQL database (ADR-016) | Purpose | Examples |
| --- | --- | --- | --- |
| **Raw** | `ledgerbridge_source` | Data exactly as received, with source metadata. Enables reprocessing (DAT-008). | `raw_records` (source, connection, batch, entity type, payload, received_at) |
| **Canonical** | `ledgerbridge_accounting` | Standard, source-independent accounting model, and the client's own planning data (budgets, ADR-026) in separate tables. | ledgers, vouchers, voucher lines, parties; budgets, budget lines |
| **Reporting** | `ledgerbridge_reporting` | Views and aggregates used by dashboards and AI (the semantic layer). The only database the AI user can read. | `v_trial_balance`, `v_pnl_monthly`, `v_receivables_ageing` |
| **System** | `ledgerbridge_system` | Connections, sync runs, validation, users and roles, audit, settings. | `connections`, `sync_runs`, `audit_log` |

The databases with their tables, and the database users with their access (generated from the models):

[![Databases and users](diagrams/schema-databases.png)](diagrams/schema-databases.svg)

The main tables (ER overview; the areas and the planned budget tables are in [diagrams/README.md](diagrams/README.md)):

[![ER overview](diagrams/er-overview.png)](diagrams/er-overview.svg)

### 4.3 Canonical model (initial outline)

To be detailed in `docs/schema.md`.

- **Organization:** `entities`, `branches`, `financial_years`, `currencies`, `exchange_rates`
- **Masters:** `account_groups` (hierarchical), `ledgers`, `parties`, `items`, `units`, `godowns`, `cost_centres`, `projects`, `tax_codes`
- **Transactions:** `vouchers` (header), `voucher_lines` (double-entry lines), `voucher_line_dimensions`, `inventory_lines`, `tax_lines`, `bill_allocations`
- **Dimensions:** `dimensions`, `dimension_values` (user-defined dimensions, DAT-005)
- **Integration:** `sources`, `connections` (credentials encrypted), `sync_runs`, `import_batches`, `record_origins`, `account_mappings`
- **Quality:** `validation_runs`, `validation_issues`
- **Security:** `roles`, `permissions`, `user_roles`, `user_entity_access`, `masking_rules`
- **Audit:** `audit_log`

Every canonical row carries `entity_id`, source origin and timestamps. Amounts use `DECIMAL(20,4)`, never floating point.

### 4.4 Connector framework

Each connector implements:

```text
test_connection() -> status
list_entities() -> companies/entities available in the source
fetch_masters(entity, since_marker) -> raw records + new marker
fetch_transactions(entity, since_marker) -> raw records + new marker
to_canonical(raw_record) -> canonical records
```

The framework handles scheduling, retries, markers (last AlterID, last modified time), logging to `sync_runs` and validation after each run.

In code, the interface is the `Connector` protocol in `data-plane/connectors/base.py`; `fetch_*` return iterators of `SourceRecord` so large sources stream. A registry maps a source code (`tally`, later `file`, `zoho`, ...) to its connector. Nothing outside `connectors/<source>/` knows about a particular source.

The pipeline, all source-independent (M3):

1. **Fetch** (`workers/sync.py`, `workers/fetch.py`): objects changed since each object type's marker, or everything on the first run; chunk by chunk with checkpoints, splitting and source checks when the connector supports it (ADR-022), else as one stream per kind (`fetch_masters`, `fetch_transactions`). Steps 1 to 4 run per entity.
2. **Store raw** (`core/raw_store.py`): payloads are stored unchanged; identical re-deliveries are skipped.
3. **Map:** the connector's `to_canonical()` turns each raw record into plain canonical records (`core/canonical.py`): amounts with the canonical sign, masters referred to by name.
4. **Transform** (`core/transform.py`): upserts on `(connection_id, source_key)`, resolves names within the entity, inherits group hints down the group tree (nature, standard account, ledger kind, party type), and replaces each changed voucher's child rows in one transaction (schema.md 8, rule 7). Stored records can be transformed again without the source (DAT-008): `transform retry` (failed and pending) and `transform rebuild` (every object of the chosen entities). Both only queue an object's latest raw record, mark older failed versions `skipped`, and keep objects deleted in the source deleted.
5. **Deletions:** a separate deletion check run compares the keys from `list_keys()` with the stored rows; keys that are gone become soft deletes. It runs on its own, longer schedule (ADR-018).
6. **Log:** one `sync_runs` row per run; markers advance only when it succeeds.

Run it with `python -m workers.cli sync` (or `./dev.ps1 sync`), and the deletion check with `python -m workers.cli check-deletions` (or `./dev.ps1 sync deletions`). The worker runs both on a schedule (ADR-017, ADR-018).

**Tally:** XML requests over Tally's HTTP interface (default port 9000). The adapter sends only Export requests (TDL collections with explicit fetch lists, targeting a company by name), fetches vouchers month by month, and handles UTF-16 responses and invalid character references emitted by Tally. Incremental sync uses AlterID/MasterID values. Version differences are handled inside the Tally adapter. Historical Tally backups are restored into a Tally instance and extracted through the same adapter.

**Files (CSV/TXT):** upload or watched folder; saved column mappings per file layout.

**Cloud APIs (Zoho, banks):** OAuth where supported; webhooks for near real-time updates, polling as fallback.

### 4.5 Connector agent

- Lightweight service installed on the machine running Tally (or near other on-prem sources).
- Polls the local source at the configured interval and pushes changes to the client deployment over outbound HTTPS with mutual authentication (agent certificate or signed agent token).
- Local queue so data is not lost during network outages.
- If the client deployment runs on the same network as Tally, the agent runs alongside the deployment instead.
- Holds only its own credentials; no long-term storage of data.

### 4.6 Validation

After each sync or import: voucher balance check, trial balance check, ledger closing balance comparison against source-reported figures. Results go to `validation_runs` / `validation_issues` and feed the data-quality dashboard and alerts.

How it works (M4, `core/validation.py`, source-independent):

- **When:** after every successful sync and deletion check, for each entity in the run, inside the same worker job (ADR-019). Also on demand: `python -m workers.cli validate` (`./dev.ps1 validate`).
- **As of a date** (default today): balances count only vouchers dated on or before it. Post-dated vouchers are stored as they are (`is_post_dated` recorded, `is_effective` unchanged) and simply fall outside earlier dates. All reports in M6 also calculate as of a date.
- **Checks:** `voucher_unbalanced`, `tb_unbalanced`, `opening_difference` (warning), `closing_mismatch`, `ledger_missing`, `profit_carrier_mismatch` (schema.md 5.2). Closing balances come from the connector's `closing_balances(entity, as_of)`; a connector without it gets an info issue and no closing checks.
- **Thorough checks (VAL-005 to VAL-008):** `validate`, full syncs and `transform retry` also compare the source's own controls, read through optional connector methods (`connectors.base.SourceControls`): vouchers per month and voucher type (`voucher_count_mismatch`), each stock item's closing quantity (`stock_quantity_mismatch`), each party's bill-wise outstanding (`bills_mismatch`, as of today only: Tally reports bills as outstanding now) and every ledger's balance at each financial year end before the validation date (`year_end_mismatch`). A control the source can't provide gets an info issue (`*_not_supported`); one that fails to read gets an error (`*_unavailable`). Stock values per item aren't compared: they depend on the source's valuation method (info `stock_values_not_compared`; the total closing stock is part of the profit check). Scheduled incremental syncs skip these checks (`validate -Quick` too): they take a request per month.
- **Readable results (OPS-005, ADR-028):** every command names a problem the same way: its plain title, then the technical key and a stable code, e.g. `Balances at year ends [year_end_mismatch, LB-VAL-006]` (`core/problems.py`, generated into `docs/error-catalogue.md`). Validation counts are compared with the entity's previous run of the same kind (`validation_runs.thorough`: a quick run skips the source's controls). `./dev.ps1 report` (`workers/report.py`) reads only the database and gives an overall verdict, sections and each problem's meaning, likely cause (root causes before consequences) and next command; a Markdown copy is saved under `reports/<env>/` (git-ignored).
- **Analysis (VAL-010):** `validate analyse` (`workers/analyse.py`) compares again and tests, for every mismatch, explanations that can be checked automatically: for ledgers (today and at each year end) the opening balance missing or counted twice, a reversed sign, the lines of one voucher type (or of cancelled, optional, deleted or non-posting vouchers) counted differently, post-dated vouchers, the source restarting income and expense ledgers each financial year, and the first year end where a ledger differs; for the profit carrier, unbalanced vouchers, the trial balance, bills and stock quantities their own patterns; plus a census of what the stored vouchers contain that the mapping doesn't read (the connector's `payload_hints`). It reports how many mismatches each explanation fits, with counts and the source's standard names only, so the rule to fix is visible without seeing client data.
- **Root cause (VAL-009):** when raw records of the entity failed to transform, the report names them (per object type, and vouchers that failed for an unknown ledger) and counts the balance and count failures that are likely their consequences, so the first thing to fix is obvious.
- **Profit carriers:** a ledger whose source balance includes the period's computed profit (Tally's *Profit & Loss A/c*) is reconciled instead of compared: source closing − our posted balance must equal our computed profit for the period, adjusted by the change in stock value the source reports.
- **Tolerance:** exact by default; `VALIDATION_TOLERANCE` or `connections.config.validation_tolerance`.
- **Issues:** stored per run. A problem still present in the next run is the same open problem; one that disappears gets `resolved_at` on its earlier rows.

**Alerts (SYN-006, ADR-019):** `core/alerts.py` raises an alert when a sync or deletion check fails, or when validation finds errors, and resolves it when the next run of that kind succeeds or passes. One open alert per connection and kind (per entity for validation), so a failure repeating every 5 minutes doesn't create a new alert each time. Alerts go through channels: the log (counts and codes only, never amounts or names) and in-app (`ledgerbridge_system.alerts`). An email channel plugs into the same interface later.

### 4.7 Budget planning and analysis (BUD-001 to BUD-016, milestone M7b)

Budgets are **user-entered data alongside source data** (ADR-026): they live in their own tables in `ledgerbridge_accounting` (schema.md 4.7) and never in the tables the sync writes.

- **Creation paths:** a source budget importer behind the connector interface (an optional `fetch_budgets(entity)` method; Tally budget masters through a read-only Export request, CON-008); a month-by-account grid in the dashboard; an Excel template downloaded and uploaded through the API (validated row by row before anything is saved); copying last year's actuals from the reporting views with growth percentages. All four produce the same thing: a draft budget version with lines and monthly amounts.
- **Spreading:** a service in `core/budgets` turns yearly amounts into months (equal, or last year's seasonality from `v_actual_monthly`), rounds to the currency's decimals and puts the rounding difference in the last month, so a line's months always sum to its yearly amount.
- **Versions and states:** original and revised versions, each `draft → approved → locked`. Only drafts change; every change is written to the append-only `budget_changes` in the same transaction as the change (BUD-006), plus a summary in `audit_log`.
- **Signs:** budget amounts are stored in the canonical sign (debit positive, schema.md 1), like actuals, so budget and actual compare directly; the dashboard shows natural signs (income and expenses as positive numbers).
- **Analysis:** reporting views in `ledgerbridge_reporting` (schema.md 6) join the current budget version with monthly actuals and last year's actuals at the budget's level, rolled up through the group tree and to standard accounts, per company and consolidated. Period totals (quarter, YTD, full year), variance, favourable or unfavourable by nature and the full-year projection are computed in these views, so the dashboard, the alerts and the AI all use one definition.
- **Alerts:** variance rules (`budget_alert_rules`) are evaluated after each sync and after budget approval, by the M6 rule-based alert engine, and feed "Needs your attention".
- **Permissions:** `budget.view`, `budget.edit`, `budget.approve` (M5), checked on every budget endpoint together with the user's entity access.

### 4.8 Foreign currency (FX-001 to FX-013, data layer in M4b)

The books stay in the base currency; foreign-currency data is kept **alongside** (ADR-037):

- **Capture (transform):** the connector maps each source's currency masters, rate lists, foreign amounts and rates on lines, ledgers' and bills' foreign amounts into canonical fields (schema.md 4.8). The transform writes `fx_transactions` with the voucher's other child rows, in the same transaction, and refreshes `fx_realised` and voucher-derived `exchange_rates` for what it touched.
- **Source-calculated figures:** the source's revaluation of each foreign-currency ledger (Tally: its closing balance at current rates and the calculated "Unadjusted Forex Gain/Loss" of its Ledger Vouchers report) is read through optional connector methods, read-only, and stored in `fx_revaluation_snapshots` at month ends, financial year ends and validation dates. These are figures the source calculated; they are never turned into vouchers or added to a base-currency balance.
- **Validation:** each foreign-currency ledger is checked twice: its base-currency book value (VAL-013) and its balance in its own currency against the source's (FX-007).
- **Reporting:** views in `ledgerbridge_reporting` (schema.md 6) give own-currency balances and ageing, exposure, realised vs unrealised gains and rate history from these tables, so the dashboard, alerts and AI use one definition; `forex.view` and the user's entity access apply.

## 5. AI layer

### 5.1 Approach

Numeric and analytical questions use **text-to-SQL** against the semantic layer, not plain retrieval of data chunks, so totals and comparisons are exact.

1. User asks a question.
2. Relevant schema descriptions and business definitions are retrieved from the vector store (RAG). Embeddings are always computed locally (AI-016).
3. **Data protection gate** (5.5): the question is masked (AI-015) if it will go to an external model.
4. The model generates SQL restricted to semantic-layer views.
5. SQL is validated (single read-only `SELECT`, allowed views only, user's entity filters injected).
6. Query runs locally under a read-only database user with timeout and row limits.
7. The result is explained and formatted. *Who* does this depends on the privacy mode (5.4): in `private` and `schema-only` it never leaves the client environment. The answer shows the SQL and links to source records.

Every model call in steps 2, 4 and 7 goes through the data protection gate and is recorded in the model call log (5.7).

### 5.2 Guardrails

- Dedicated read-only MySQL user (`ai_ro`) with `SELECT` on `ledgerbridge_reporting` only.
- Entity/branch filters from the user's permissions are enforced in SQL, not left to the model.
- **The model has no outbound tools (AI-017).** The model interface offers one capability: proposing a SQL query, which application code validates and runs. There are no tools for HTTP, web search, email, messaging, file writes or uploads, and no plug-in mechanism that could add one. Model output is treated as untrusted text: it's never executed except as validated SQL, and never used as a URL, file path or command.
- **What may be sent is decided by the privacy mode in code**, not by prompt instructions (5.4, 5.5).
- **Outbound network allowlist (SEC-010, 5.6)**, so even a bug can't send data elsewhere.
- **Every model call is logged** with the exact payload sent (AI-018, 5.7).

### 5.3 Model provider abstraction

A single internal interface (`ModelProvider`) with one implementation per provider. The client's privacy mode decides which providers may be configured (5.4). The embedding model is a separate, always-local provider (AI-016).

| Provider option | Data location | Allowed in modes | Notes |
| --- | --- | --- | --- |
| Open-weight model on client hardware or in the deployment (e.g. via Ollama) | Fully local | `private` (required), and as the local formatter in `schema-only` | **Default.** Used for the pilot on client data. Lower quality on complex questions. |
| Claude via AWS Bedrock (client's own account) | Client's cloud agreement | `schema-only`, `full` | Endpoint is the client's account and region. |
| Claude via Google Vertex AI (client's own account) | Client's cloud agreement | `schema-only`, `full` | Endpoint is the client's project and region. |
| Anthropic API (direct) | Anthropic | **None for client data** | **Development and test environment only**, on synthetic data (architecture §13). Never configurable for a client deployment (AI-014). |
| Local embedding model (e.g. a sentence-embedding model served locally) | Fully local | All modes | Embeds the semantic catalog, definitions, ledger names and documents into Qdrant (AI-016). |

No provider path sends data to provider (our) infrastructure.

### 5.4 Privacy modes (AI-011 to AI-014)

The mode is a per-client setting held in the data plane (`ledgerbridge_system.settings`). Only a Client Admin can change it, and the change is audited. The default for every new deployment is `private`.

| Step | `private` (default) | `schema-only` | `full` |
| --- | --- | --- | --- |
| Embeddings (RAG) | local | local | local |
| SQL generation | local model | external model receives **only** the masked question and semantic-layer descriptions | external model receives the masked question and semantic-layer descriptions |
| SQL execution | local | local | local |
| Explaining and formatting results | local model | **local only**, by deterministic templates or the local model. Results are never sent out. | external model, receiving **masked** result rows |
| External endpoint on the allowlist | none | one: the client's Bedrock or Vertex endpoint | one: the client's Bedrock or Vertex endpoint |

The gate (5.5) enforces these columns in code. In `schema-only`, the request builder for an external call can't accept result rows or sample values at all: its input type only has fields for the question and catalog descriptions. So a mistake in prompt code can't leak data.

### 5.5 Data protection gate: masking and pseudonymization (AI-015)

Every payload bound for a model passes through one component (the "gate") before it reaches a provider:

1. **Mode check:** the gate refuses the payload if its content type isn't allowed in the client's mode (e.g. result rows in `schema-only`).
2. **Detection:** finds sensitive values:
   - **party names**: matched against the known party and ledger master (`ledgerbridge_accounting.parties`, party ledgers), not guessed
   - **GSTIN and PAN**: by format and checksum
   - **bank account numbers**: from bank ledgers' details and by pattern
   - **salary amounts**: values from ledgers and views tagged as salary, using the masking rules of ACC-003
3. **Pseudonymization:** each value gets a consistent token for the conversation, e.g. `PARTY_017`, `GSTIN_003`, `PAN_002`, `BANKAC_001`. Salary amounts become `SALARY_AMOUNT_n`, or are dropped where the mode allows no figures. The same value always maps to the same token, so the model can still reason about "the same customer".
4. **Send** through the allowlisted provider (5.6), and log the payload exactly as sent (5.7).
5. **Reverse locally:** tokens in the response are replaced with real values inside the data plane before the user sees the answer.

The token map exists only in memory for the request, or in a short-lived local cache. It's never sent, never logged and never written to the model call log. Role-based masking (ACC-003) is applied first, so a user can't see real values through the AI that they couldn't see directly.

### 5.6 Outbound network allowlist (SEC-010)

The data plane can reach only its configured sources and the one approved AI endpoint:

- **Network level:** data-plane containers sit on an internal Docker network with no default route out. Outbound traffic goes through an egress proxy (or host firewall rules) holding the allowlist: the configured source hosts (e.g. the Tally host), plus the AI endpoint for the client's mode (Bedrock or Vertex in `schema-only` and `full`; nothing in `private`). Local model and embedding services run inside the deployment, so they need no outbound access.
- **Application level:** every outbound HTTP client in the data plane is built by one factory that checks the destination against the same allowlist before connecting. This catches mistakes earlier and logs refusals.
- The allowlist is derived from configuration (connections and the AI mode), not edited by hand. Changes are audited. The local pilot will apply the same allowlist from M8.

### 5.7 Model call log (AI-018)

Every call to any model, local or external, writes one append-only record in the client's database: user, time, mode, provider, endpoint, model, the payload **as sent after masking**, the response **as received**, token counts, duration and outcome. It extends `ledgerbridge_system.ai_query_log` (one row per question) with one row per model call. The exact table is designed in M8, and `docs/schema.md` is updated then. Client Admins can view it. Retention follows AUD-002.

## 6. Frontend

- React + TypeScript, built with Vite.
- TanStack Query for data fetching and caching; Ant Design for tables, filters and forms; Apache ECharts for charts.
- Logs in via the control plane; all data calls go to the client deployment URL from the token.
- Content Security Policy restricts connections to the control plane and that client's deployment (SEC-005).
- Released as a signed bundle; can also be self-hosted by the client (SEC-006).

## 7. Security design summary

| Area | Measure |
| --- | --- |
| Data location | All client data in client environment only. |
| Identity | Argon2id password hashes, MFA, short-lived signed tokens, optional SSO. |
| Authorization | Roles and entity/branch/report permissions enforced in the client deployment. |
| Transport | TLS everywhere; mutual auth for agents. |
| At rest | Encrypted database volumes and backups; encrypted connection credentials (application-level encryption with a client-held key). |
| Sources | Read-only access only. |
| AI | Per-client privacy mode, default `private` (local model). Read-only SQL user with semantic-layer-only access. Masking and pseudonymization before any external call. Local embeddings. No outbound tools. Every model call logged (5.4 to 5.7). |
| Network egress | Allowlist: configured sources plus the one approved AI endpoint; everything else blocked (SEC-010, 5.6). |
| Supply chain | Signed images and bundles, verified on update; checks on every pull request: dependency, image, static and secret scanning (SEC-009, ADR-039). |
| Telemetry | None leaves the client environment. |

## 8. Deployment and updates

- Client deployment ships as Docker images with a Docker Compose configuration for a single server or a single cloud VM. Kubernetes packaging can follow if larger clients need it.
- Configuration via environment variables and a config file; no cloud-specific services required in the core.
- Releases are versioned; updates pull signed images, verify signatures, run database migrations (Alembic) and restart services.
- Automated daily database backups within the client environment.
- Provider support access to a client deployment happens only with explicit, time-limited client permission.

## 9. Technology stack

| Concern | Choice |
| --- | --- |
| Backend language | Python 3.12+ |
| Python packaging | uv (`pyproject.toml`, `uv.lock`) |
| API framework | FastAPI |
| ORM / migrations | SQLAlchemy 2 + Alembic |
| Database | MySQL 8 |
| Background jobs | Celery + Redis |
| Vector store | Qdrant |
| Frontend | React, TypeScript, Vite, TanStack Query, Ant Design, Apache ECharts |
| Auth tokens | JWT (asymmetric signing, JWKS) |
| Packaging | Docker, Docker Compose |
| Testing | pytest (backend), Vitest + Testing Library (frontend), Playwright (end-to-end) |

## 10. Repository structure (proposed)

```text
/control-plane        FastAPI service: auth, licences, client registry
/data-plane
  /api                FastAPI service: reporting, admin, AI endpoints
  /core               canonical model, validation, permissions
  /connectors         one package per source (tally, files, zoho, ...)
  /workers            sync, import, validation, scheduled jobs
  /ai                 text-to-SQL, provider abstraction, guardrails
  /migrations         Alembic migrations
/agent                connector agent
/frontend             React + TypeScript dashboard
/deploy               Docker, Compose files, release scripts
/docs                 requirements, architecture, schema, decisions
```

## 11. Decision log

| ID | Decision | Reason |
| --- | --- | --- |
| ADR-001 | Split into provider control plane and client-hosted data plane. | Provider may store only login credentials (PM-003). |
| ADR-002 | Client's own cloud account is the default deployment target; office server supported. | Managed security, backups and real-time availability; flexibility for strict clients. |
| ADR-003 | Text-to-SQL over a semantic layer for numeric questions; RAG for context and documents. | Exact financial figures; plain retrieval cannot sum or compare reliably. |
| ADR-004 | **Superseded by ADR-015.** ~~Pluggable AI provider; default Claude via client's cloud account; local model option.~~ | Client requires data security; no data to provider infrastructure. |
| ADR-005 | Raw / canonical / reporting data layers. | Reprocessing, lineage and source independence. |
| ADR-006 | Connector agent with outbound-only connections for on-prem sources. | Works when Tally is not on the deployment's network; no inbound firewall rules. |
| ADR-007 | Roles and permissions stored in the client deployment, not the control plane. | Keeps organizational data out of provider infrastructure. |
| ADR-008 | Signed frontend bundle with strict CSP; self-host option. | Prevents a compromised control plane from silently exfiltrating data. |
| ADR-009 | Pilot first on the client's backup data, running the data plane locally. | Proves extraction, model and dashboard on real data before building product infrastructure. |
| ADR-010 | `AUTH_MODE=local` during the pilot; token verification sits behind an interface. | Lets the control plane replace local login later without changing authorization code. |
| ADR-011 | Separate `test` and `pilot` environments with separate databases. | Keeps client data away from AI development tools and external AI APIs. |
| ADR-012 | Each environment runs as its own Docker Compose project (`ledgerbridge-test`, `ledgerbridge-pilot`) with its own volumes, host ports and env file. | Keeps the database names (ADR-016) identical in every environment while keeping data physically separate. |
| ADR-013 | uv manages Python versions and dependencies for the data plane (`pyproject.toml` + `uv.lock`). | Reproducible locked installs and a pinned Python 3.12 independent of the host Python. |
| ADR-014 | One narrow exception to "read-only towards sources" (CON-008): the developer-only seeding tool in `data-plane/devtools/tally_seed` may send Tally **Import** requests, and only to the test company. It refuses to run unless `APP_ENV=test`, exactly one company is loaded and its name matches the target exactly. It is never imported by product code, is excluded from the Docker image (`.dockerignore`), and connectors keep their Export-only client. | The test company needs realistic, repeatable data (bills, GST, cancelled and altered vouchers) to prove extraction and the sign convention; hand entry is slow and not repeatable. |
| ADR-015 | AI data protection by design, replacing ADR-004. Per-client privacy mode: `private` (default, local model only), `schema-only` (external model sees only the masked question and semantic-layer descriptions; SQL and result formatting stay local) or `full` (external model only via the client's own cloud account, everything masked). One data protection gate pseudonymizes party names, GSTIN, PAN, bank accounts and salaries and reverses them locally. Embeddings are always local. Models have no outbound tools. A network allowlist limits egress to configured sources plus one approved AI endpoint. Every model call is logged with its exact payload. | The client answered "ideally no" to external AI (OPEN-007), and accounting data is highly sensitive. Making `private` the default, enforcing what can be sent in code and at the network level rather than in prompts, and logging every payload means a bug or prompt injection can't quietly leak data, while clients who choose an external model still get better SQL from it. |
| ADR-016 | The four MySQL databases are named `ledgerbridge_source` (raw layer), `ledgerbridge_accounting` (canonical), `ledgerbridge_reporting` (semantic layer) and `ledgerbridge_system` (system), replacing `raw`, `core`, `rpt` and `app`. "Raw", "canonical", "reporting" and "system" remain the names of the layers. Code refers to them through constants in `core/models/schemas.py`; migrations use the literal names. **One-time exception:** the rename was made by editing migration 0001 and recreating the test database, which was acceptable only because no pilot or client database existed yet. **After the first release, any rename must be done with a proper migration**, never by editing an applied one. | The short names didn't say what they hold, and generic names like `app` and `core` can clash with other applications' databases when a client hosts us on a shared MySQL server. The prefix groups our databases together in any MySQL tool, and the names read clearly in grants (`ai_ro` can read `ledgerbridge_reporting` only). |
| ADR-017 | Scheduled sync (SYN-001) runs in the Celery worker with Celery Beat embedded (`worker -B`). A tick every `SYNC_TICK_SEC` (60 s) queues an incremental sync for each active connection whose own `sync_interval_sec` (default 300) has passed since its last run. A connection never runs twice at once: a Redis lock per connection plus a check for a `running` row in `sync_runs` (stale after 2 hours). | One small always-on process covers near-real-time sync without a separate scheduler service. Per-connection intervals and the double lock keep slow sources and manual runs (`./dev.ps1 sync`) from overlapping. Embedded Beat suits one worker; a separate Beat process can follow if workers scale out. |
| ADR-018 | Deletions in the source (SYN-003) are found by a **deletion check** that lists every key in the source and soft-deletes stored rows whose key has gone. It runs as its own `sync_runs` row (`run_type = 'deletion_check'`) on its own schedule, every `connections.config.deletion_check_interval_sec` seconds (default `DELETION_CHECK_INTERVAL_SEC` = 3600), queued by the same tick as syncs and under the same per-connection lock. Incremental syncs never list keys. | Listing every key costs about 1.3 KB per Tally voucher on every run, far more than an incremental sync of a few changes, so doing it every 5 minutes doesn't scale to years of books. Deletions are rare and an hour's delay is acceptable for MIS reporting; the interval is configurable per connection and a full sync also checks. |
| ADR-019 | Validation runs after every successful sync and deletion check, as of a date (default today), and alerts are raised on **changes of state** only: one open alert per connection and kind (per entity for validation), resolved automatically when the next run succeeds or passes. Alerts are delivered through channels behind one interface: log and in-app in phase 1a, email later. Until M5, the validation and alert endpoints are read-only and unauthenticated, which is acceptable only because the API binds to 127.0.0.1; M5 protects them with `validation.view`. | The closing-balance check costs one ledger export, cheap enough to run every 5 minutes, and it also catches differences between hourly deletion checks. Alerting on every failing run would bury users in repeats; state changes are what someone has to act on. Channels keep email (and later other routes) a configuration change, not a rewrite. |
| ADR-020 | **Syncs use short transactions, and new connections start paused.** Every insert into a table with a foreign key to `connections` (sync runs, raw records, every canonical row) holds a shared lock on that connection's row until the transaction commits, so syncs never keep a write transaction open while waiting for the source. The raw store writes each batch in one insert-and-commit; the transform commits per batch. "Sync in progress" is the run's `running` row in `sync_runs` (committed at the start) plus the worker's Redis lock, never a database lock. `connect` refuses while a run is in progress and waits at most 10 s for a lock. Connections created by any command are `paused` until `connect --activate`; listing a source's companies never creates or changes a connection. Outside the test environment, CLI and worker errors show only the type and a short message (`core/errors.py`), never SQL or parameters. | The first pilot run failed with MySQL error 1205: listing companies created an active connection, the worker started a full sync at once, and that sync's long transaction blocked `connect` (which was meant to set origin `backup` first), so the data was tagged `live`. |
| ADR-021 | **Entities are identified by their source key, not their name.** `connect` resolves names typed by a person (exactly as the source reports them: no trimming, no case or whitespace folding), or `--all` takes every loaded entity, and stores each entity's key (Tally: company GUID) with its name. Every later command (sync, deletion check, validation, extract) finds entities by key through one shared lookup (`workers/entities.py`); validation after a sync follows the keys of that run. Requests to Tally use the name exactly as Tally currently lists it; if Tally rejects it, the connector looks up the GUID's current name and retries once. `entity-check` explains mismatches by kind (spacing, punctuation, case, suffix) without printing names. | The second pilot attempt fetched 36,473 records and then failed with "2 requested entities are not available": names that `connect` had matched no longer matched later. Keys don't change; the exact cause of the name difference can be seen with `entity-check` without sharing names. |
| ADR-022 | **Large syncs are fetched in chunks, resumably, entity by entity.** A connector that offers `fetch_plan`/`fetch_chunk` (Tally does) is fetched chunk by chunk: the entity record, each master type, then transactions per month (`workers/fetch.py`). Each chunk is stored and committed as soon as it arrives and, in a full sync, checkpointed (`sync_checkpoints`): re-running an interrupted full sync continues after the last completed chunk (`--restart` starts over; checkpoints expire after 7 days). A request that times out (`timeout_sec`, default `TALLY_TIMEOUT_SEC` = 120) is not resent as it is: the source is first checked with a minimal request (short timeout), re-checked after 10, 30 and 90 s if it doesn't answer, and reported as responsive, slow or unresponsive; an unresponsive source stops the run (progress kept). Otherwise the chunk is split (month, half-month, week, day), the pieces fetched, and the whole chunk verified against a keys-only listing, so a piece the source silently leaves empty fails the entity instead of losing data; the month is remembered (`sync_slow_periods`) and later runs request it in pieces directly. Each entity is fetched, transformed, given its markers and validated before the next starts; a failing entity doesn't stop the others (except an unresponsive source), and the run reports each entity's fetched, stored and transformed counts. | The third pilot attempt: after 18 minutes and 121,124 vouchers TallyPrime stopped answering, the client resent the same request twice (2 x 120 s), the run failed, and the second company was never reached. Vouchers already stored had been committed in batches, but the run's counts didn't show it and a re-run had to start from the beginning. |
| ADR-023 | **Nothing unverified is counted as complete.** A chunk is checkpointed only once it is known to be complete: a month fetched in parts must match its keys-only listing, and a month that comes back empty while the entity's months typically have 20 or more records must be confirmed empty by its listing. If a listing doesn't arrive in time or doesn't match, the range is recorded in `sync_unverified_ranges` and the sync stops; recorded ranges are fetched again on every full sync until they verify, whatever their checkpoints say. Whether the source answers requests for **part of a month** is probed once per connection (a month's listing against its halves' listings) and stored (`connections.config.part_month_requests`; `connect --part-month` overrides it). Without that support a slow month is never split: it is retried whole with longer timeouts (300, 600, 1200 s), pausing 60 s first, and the sync stops with a clear message if it still fails. A connection's request timeout is its own `timeout_sec` if set, otherwise the `TALLY_TIMEOUT_SEC` setting; `pause_sec` paces requests. `sync --full --refetch-from DATE` forgets the checkpoints from a date so a damaged range is fetched again. | The fourth pilot attempt: TallyPrime (Educational mode) returned nothing for part-month requests, a split month's listing timed out, the sync only warned ("couldn't verify") and carried on, and the connection still had the 120 s timeout it was created with although `TALLY_TIMEOUT_SEC` had been raised to 600. |
| ADR-024 | **Syncs survive the terminal; runs are never left `running`.** `dev.ps1 sync` starts the sync **in the background inside the api container** (`docker compose exec -d`) with a job id; the sync writes every output line to `ledgerbridge_system.sync_logs` under that id and ends with `[job finished: exit N]`, and `dev.ps1` then follows it with `workers.cli watch` (`./dev.ps1 sync watch` follows again from any terminal; leaving it never stops the sync). A running run updates `sync_runs.heartbeat_at` every `SYNC_HEARTBEAT_SEC` (30 s) from a background thread and records its `pid` and `host`. Ctrl+C or termination (SIGTERM) marks the run **`interrupted`** with its checkpoints kept. A `running` run whose heartbeat is older than `SYNC_STALE_SEC` (300 s), or whose process is known to be gone, is marked `interrupted` automatically before any new run starts and by `status`; `sync abandon` does it by hand after a typed confirmation, sparing runs that still look alive unless forced. **After a timeout** the source check keeps trying, with growing pauses, for up to the connection's timeout, because Tally goes on with an abandoned request. **Undeclared XML prefixes** (e.g. `UDF:` from TDL customisations) are parsed by renaming them internally; the stored payload keeps them unchanged, and their names are remembered in `connections.config.xml_prefixes_seen` and shown in `summary`. | Pilot 2026-10-13: a month with `UDF:` fields failed as invalid XML; checks right after a 600 s timeout found Tally still busy and stopped the sync; `sync full` twice returned to the prompt mid-run while the sync went on unseen; Ctrl+C left a run `running` until it was fixed by hand. |
| ADR-025 | **The accounting layer adapts to any company's data without runtime schema changes.** The raw layer keeps every record exactly as received. Every accounting table that receives source data has an `extra` JSON column: the connector puts there every field its mapping doesn't use (for Tally, by path, prefixed names as Tally wrote them, e.g. `UDF:SALESMAN.LIST/UDF:SALESMAN`; Tally's own bookkeeping fields are left out). The transform counts these fields per entity and object type in a **field catalogue** (`source_fields`: path, prefix, inferred type, record count, first and last seen). A catalogued voucher field becomes a **reporting dimension** only by an explicit command (`promote-field`), which backfills from `extra`; the transform then keeps it current. A field useful for every client becomes a real column through a migration. **Values that don't fit their column** are fitted before writing (`core/fit.py`): the full value goes to `extra._unfit`, the column gets NULL, the value rounded to the column's decimals, or a placeholder for required text, and the record gets a warning (kind, table, column and size, never the value). Only a required amount, quantity or date that can't be stored fails, and only its own record. A batch the database still rejects is written again record by record. MySQL data errors are described by code, kind, table, column and size. The application users keep least privilege: no DDL outside migrations. | Pilot 2026-10-13: one over-long value failed whole batches of 500 ("Transform batch failed: DataError"), and with them the vouchers that referred to the ledgers in them; TDL customisations add fields no fixed schema can foresee. |
| ADR-026 | **User-entered data lives alongside source data, never inside it.** Data the client creates in the platform (first: budgets) goes into its own tables, separate from the tables the sync writes; a sync, `transform rebuild` or deletion check never reads or changes it. Each row says how it was made (`origin`: `manual`, `excel`, `copy`, or the source's own origin for imported source data such as Tally budgets, which keep their `connection_id` and `source_key`) and by whom; changes are audited row by row in an append-only history and summarised in `audit_log`. It refers to source data by stable ids (standard accounts, account groups, ledgers, cost centres, dimension values); if a referenced source object is deleted in the source, the user-entered row stays and is flagged, never deleted. Reporting views combine both kinds of data; the AI reads them only through the semantic layer, with the same protection as source data. Versions with states (draft, approved, locked) replace in-place edits for anything that is approved. | Budgets are the first data the client enters rather than syncs. Keeping it apart means re-syncs and rebuilds can never overwrite a user's work, imported and typed budgets are treated the same, and every change can be explained. |
| ADR-039 | **Automated checks on every pull request, with free tools that need no account.** One GitHub Actions workflow (`.github/workflows/checks.yml`) runs lint and unit tests, integration tests on throwaway MySQL, Redis and Qdrant service containers with recorded Tally responses (never Tally or client data), the `dev.ps1` tests on a Windows runner, pip-audit and npm audit, Semgrep's public rules (metrics off), gitleaks over the whole history and Trivy on the data-plane image. Its "All checks" job is required on `dev` and `main` by branch protection; high-severity findings fail it. The token is read-only; tools run from pinned versions. | 2026-10-19: security foundations before M5; SEC-009. Tools that need an account or a paid plan are added only with the developer's approval. |
| ADR-038 | **Book value of a foreign-currency ledger from the source's own vouchers; the opening difference as the source displays it.** A foreign-currency ledger's book value is its opening plus the total of Tally's own vouchers on it up to the date, from its ledger-voucher collection (read once per ledger and kept for every date checked); its revalued closing balance is information only (supersedes ADR-036's "closing less the calculated line"). The opening difference warning uses the difference line of Tally's own Trial Balance as at the books' beginning (zero when it shows none, as its Balance Sheet then shows no "Diff. in Opening Balances"); the group-total figure is the fallback when the report can't be read. | 2026-10-16 pilot: every voucher of three foreign-currency customers matched ours, Ledger Vouchers showed no calculated line, and validation still compared with the revalued balance; a company not integrated with inventory showed no difference in Tally while its group openings didn't total zero. |
| ADR-037 | **Base currency stays the books; foreign-currency data is stored alongside; source-calculated revaluations are stored as snapshots.** Every statement, balance and validation uses the base-currency amounts, as the source's books do. Foreign amounts, rates and currencies are extra columns and tables (schema.md 4.8) that never change a base figure. The source's own revaluation of a foreign-currency ledger (Tally's "Unadjusted Forex Gain/Loss" and revalued closing balance) is stored per ledger and date in `fx_revaluation_snapshots`, labelled as source-calculated, never posted as a voucher; realised gains come from the source's adjustment journals and, for bills settled at another rate, are calculated here and labelled so. Exchange rates come from the source's rate lists where they exist, else from its vouchers, each with its source. | 2026-10-16: client requirement for balances and dues in the customer's currency, exchange gains and losses and currency exposure; the pilot showed Tally values foreign-currency ledgers at current rates in balances while its books keep the amounts entered (ADR-035, ADR-036). Keeping the base currency as the books keeps every existing check and report unchanged. |
| ADR-036 | **Foreign-currency ledgers one by one; a voucher-by-voucher comparison.** Each foreign-currency ledger's book value is its closing balance (revalued by Tally) less the calculated "Unadjusted Forex Gain/Loss" line of its own Ledger Vouchers report on the To date, read from Tally's report export (read-only); validation compares each ledger with its own (supersedes ADR-035's total from the trial balance). That report's export lists only the To date's month, so it isn't used for vouchers: `validate compare-ledger` lists a ledger's vouchers from Tally's ledger-voucher collection (Child Of the ledger, month by month), matches them with ours by GUID, else date, number and type, and prints counts only; the details go to `reports/<env>/private/` through dev.ps1 (PRIVATE lines of the CLI, never shown). | 2026-10-16 pilot: Ledger Vouchers shows a calculated Unadjusted Forex Gain/Loss line on its To date; two customers differ from Tally's current total from some date on. Test company: the report's export listed only the To date's month; the collection honoured the period and left optional vouchers out. |
| ADR-035 | **Foreign-currency ledgers at the source's book value.** Tally reports a foreign-currency ledger's closing balance, and its group totals, at current rates (the foreign amount times the rate); its trial balance shows the difference to the amounts entered as one line, "Unadjusted Forex Gain/Loss", until a forex gain/loss journal posts it. The connector finds the foreign-currency ledgers (CURRENCYNAME not the base currency's, which is that of the ledgers directly under Primary: Tally exports the rupee sign as "?") and reads that line from Tally's own Trial Balance export; their book value together is their closing balances plus that line. Validation compares the total of ours with it (VAL-013); `validate analyse` counts them as explained when equal. Lines keep their foreign amount (`amount_fc`, from "-$100.00 @ ... = ..." amounts). Not done: Tally's XML import refused foreign amounts in that form and no rate of exchange has been exported yet, so the seed has a dollar customer with a sale entered in rupees only; revaluation by rates of exchange, and amounts per foreign ledger, wait for a forex voucher and a rate entered in TallyPrime. | 2026-10-16 pilot: three foreign-currency customers differed; Tally's Ledger Vouchers equalled ours. On the test company: a dollar customer's closing balance and group total were 0 while Rs 8,200 was entered, and the trial balance showed Unadjusted Forex Gain/Loss Dr 8,200. |
| ADR-034 | **A name identifies one master, as in Tally; deleted masters never take a live one's name.** Tally compares names trimmed, with spaces collapsed and case ignored, and allows one master per name or alias; a voucher naming an alias is stored under the master's name. Our resolution (exact, alias, normalised; core/names.py) gives the same master for Tally's data, so its order stays. Rows deleted in the source are indexed only for names no live row has (`Transformer._by_name`): before, a deleted twin (a master deleted and created again) could take the exact match or make the name ambiguous. Existing data is corrected by `transform rebuild`. | 2026-10-16 pilot: three customers differed while their vouchers matched, as if lines sat on the wrong ledger. On the test company: "Party Lima ", "PARTY LIMA" and "Party  Lima" were each taken for "Party Lima"; a ledger whose alias was another ledger's name was refused; a journal naming an alias came back naming the ledger. |
| ADR-033 | **The source's own stock value and opening difference; effective dates kept, not counted; company numbers kept.** (1) Tally's own group totals for a period are used: its primary groups' openings (with those of ledgers directly under Primary) are its trial balance's, so their total is its difference in opening balances; with accounts integrated with inventory its Stock-in-Hand group holds the stock value it uses (opening and closing). Ledger and item sums are the fallback. (2) Stock ledgers the source reports at its closing stock value are validated against that value at each date (VAL-012); otherwise ledger by ledger. (3) **Proposed for M6 (to approve then):** reports take the stock value from the source, not from a valuation engine: the source's closing stock value (and its stock ledgers' balances) stored as source figures at reliable dates (each month end and year end, and the as-of date of each validation), e.g. a `stock_values` table (entity, as_of, opening_value, closing_value, origin), refreshed by each sync; balance sheet and P&L stock lines read it for the nearest stored date and say which. Rebuilding FIFO or average costing would duplicate the source's valuation rules per company and could never be validated more closely than these figures. (4) `vouchers.effective_date` keeps Tally's EFFECTIVEDATE; balances count by `voucher_date`. (5) Company numbers in output are stored on the connection (`config.company_numbers`) when first given and never change. | 2026-10-15 pilot: two integrated companies reported their Stock-in-Hand ledger at the closing stock value at every date; one company's warning showed an opening difference that Tally's trial balance doesn't; two ledgers differed only at one year end; after a reconnect entity 1 became company 2. On the test company (2026-10-15): the Stock-in-Hand group equals the items' stock value at each date and the primary groups' openings total the trial balance's; Tally refuses vouchers posting to a Stock-in-Hand ledger (integrated); vouchers with an effective date on the other side of a month end count by their date. |
| ADR-032 | **Compare only on dates the source answers reliably.** A `DateRule` (`core/dates.py`) per connector says which days of a month give reliable balances (Tally in Educational mode: 1, 2, 31). Validation runs as of the latest reliable date on or before the date asked for; year ends and the analysis's month ends move to the next reliable date (30 June → 1 July); the books' first day likewise. Both sides are compared as of the date used, and the output names it. The connection setting `educational` (`connect -Educational auto|yes|no`) decides; `auto` asks Tally ($$LicenseInfo:IsEducationalMode) and, when Tally doesn't say, uses every date as before. | 2026-10-15: on the test company (Educational mode) a balance requested for the 30th included later vouchers; the pilot also runs in Educational mode, and validation ran as of today. |
| ADR-031 | **Stock is counted where the source counts it: by godown kind, each entry once.** Godowns carry whose stock they hold (`godowns.holding`, from Tally's ISEXTERNAL / ISINTERNAL): stock at a job worker's godown ("our stock with third party") is left out of item balances, as Tally leaves it out of balances, the Stock Summary and the closing stock value; a principal's stock with us is counted, as Tally counts it. A Material In/Out moves stock at its line's godown; its destination godown moves nothing (Tally's batches show only consumption at the job worker's godown). An inventory entry spread over several godowns becomes one line per godown. A stock journal's entries are read from ALLINVENTORYENTRIES, where Tally lists both sides; its in and out lists are read only when that list is missing. The opening check reports the source's own difference in opening balances: its ledger openings plus opening stock value at the books' beginning; with accounts integrated with inventory, ledgers under the (possibly renamed) Stock-in-Hand group are left out, as Tally's trial balance leaves them out, and its stock values come from the items; without integration those ledgers are the stock. `validate analyse` compares stock godown by godown (Tally's batches per item) and counts job work vouchers. | Pilot 2026-10-15: job work is used case by case and invoices are tracked to notes; analysis needed godown-level figures. Reproducing job work on the test company showed stock journals counted twice since PR #20 and the opening check missing opening stock. |
| ADR-030 | **One run lock per connection that can't outlive its job.** Every run (sync, deletion check, transform), whether started by `dev.ps1` or the worker's schedule, opens through `workers.sync._open_run`: it is refused while the database has a live `running` run, then takes the connection's run lock in Redis (`workers/locks.py`). The lock names the run (`run:<id>`), lives three heartbeats (at least 90 s) and is renewed by the run's heartbeat, so it lapses shortly after its process dies, although Redis keeps its data on disk. It is released whenever the run ends (succeeded, failed, interrupted); the stale-run check, `sync abandon` and the next run clear a lock no live run stands behind. The refusal says whether a running run (id, kind, last sign of life) or only a lock (and its expiry) was found. When Redis can't be reached, runs rely on the database check alone. The worker's separate two-hour lock is gone. | Pilot 2026-10-15: after a shutdown mid-sync, `sync full` was refused ("already has a sync running") although no sync process existed; runs started by `dev.ps1` took no lock, while the worker's lock lived two hours, and nothing told which of the two had refused. |
| ADR-029 | **The source's counting rules are reproduced on the test company and checked against its own reports before they're coded.** Each rule gets synthetic vouchers in the seed (`devtools/tally_seed/data.py`) whose expected figures equal what Tally reports, and recorded fixtures. Found for Tally (2026-10-14): (1) a master's `OPENINGBALANCE`/`OPENINGVALUE` is computed for the requested period (the balance at its start; income and expense ledgers 0; *Profit & Loss A/c* with the profit so far), so ledgers, stock items and opening bills are fetched for a period starting on the books' beginning; (2) a sales, purchase, debit or credit note line with a tracking number never moves stock, whichever came first; the delivery or receipt note (or the rejection, for returns) does: `inventory_lines.stock_quantity` holds what moves stock; (3) optional, memorandum and reversing journal vouchers aren't in Tally's balances (also not in period openings); custom types under Journal and post-dated vouchers (from their date) are. | Pilot 2026-10-14: 593 ledgers differed from the first year end on, 217 by exactly their stored opening; 1,235 stock items differed, 806 by their opening quantity and 455 by sales lines. The master fetch had no period, so it stored the balance at the start of Tally's current period as the opening and then added every voucher since the books began; and stock moved twice for invoices tracked to notes. |
| ADR-028 | **One problem registry with stable codes; one output layout.** Every error and warning is a `Problem` in `core/problems.py` with a code (LB-SYNC, LB-TRF, LB-VAL, LB-CON, LB-SYS; never reused or renumbered), the technical key it replaces, a plain title, meaning, causes, how to investigate and fix, the next command, and the problems it is usually a consequence of. All output (sync, transform, validate, status, summary, report) uses it, and `docs/error-catalogue.md` is generated from it (a test fails when stale). Output stays plain text whose status words carry the meaning; colour is added only when `dev.ps1` asks (`LB_COLOR=1`, terminal supports it, output not redirected; `NO_COLOR` respected), and background jobs never store colour codes. Reports hold counts, dates, codes and labels only, in every environment, so they can be saved and shared. | Pilot 2026-10-14: results were hard to read and reason about: technical check codes, misleading headings (reference matches listed as values that didn't fit), no verdict and no next step, and no way to see whether a re-run made things better. |
| ADR-027 | **References by name resolve by one set of rules, on both sides.** `core/names.py` resolves every reference by name in the transform (a ledger's group, parent groups and other parents, a voucher's type, ledgers, party ledger, cost centres, stock items, godowns, units): exact name; then an alias the target is known by (stored in its `extra._aliases`: alias names, and for Tally the reserved name of a predefined group the user renamed); then a normalisation applied the same way to both sides (XML entities decoded until stable, Unicode NFC, every kind of space as one space, trimmed, case folded, matching Tally's case-insensitive names). Each step accepts a match only when exactly one target fits; otherwise a required reference fails its record (`refers to an unknown ...` or `... matches several ...`) and an optional one is left empty. Alias and normalised matches are recorded per record as warnings (kinds only). Look-alike characters and punctuation are never matched automatically: `transform explain` reports them, with counts and kinds of difference only, together with whether the name is one of the source's predefined names, whether the referenced object is stored at all or failed itself, and (with `-CheckSource`) whether the source lists it and how many objects per master type the source lists against how many are stored. Voucher types inherit their standard type (the source's predefined type, from a fixed list), base type and whether they post to the books from their parent types; lines of vouchers whose type doesn't post (orders, memorandum, delivery notes, ...) are not effective. | Pilot 2026-10-13: 29 ledgers failed for an "unknown group" and with them 369,740 vouchers; 1,443 unbalanced vouchers had the base type "other". Exact matching only, and voucher type kinds read from the direct parent only, made both depend on how a name or type was written rather than what it is. |

New decisions are appended here with the next ADR number.

## 12. Open technical questions

- Exact Tally versions and sample data for testing version compatibility.
- Whether larger clients need Kubernetes packaging in phase 1.
- Local model choice and minimum GPU specification for the fully local AI option.
- Key management approach per cloud (cloud KMS vs client-managed key file for office servers).

## 13. Local pilot mode

The pilot runs the data plane on the developer's Windows machine.

- **Services:** Docker Compose runs MySQL, Redis, Qdrant, the API and workers; the frontend runs with the Vite dev server.
- **Reaching Tally:** TallyPrime runs on the Windows host with its XML server on port 9000. `TALLY_URL` is `http://localhost:9000` for tools run on the host; Compose overrides it to `http://host.docker.internal:9000` inside containers.
- **Companies:** the companies to extract must be loaded (open) in TallyPrime during extraction. The connector targets each company by name in its XML requests, so one run can process several companies.
- **Environments:** two separate configurations, each with its own database:

| Environment | Data | AI provider | Used by Claude Code? |
| --- | --- | --- | --- |
| `test` | LedgerBridge Test Co (developer-created) | Anthropic API (development only, synthetic data). Also used to exercise all three privacy modes. | Yes |
| `pilot` | Client backup companies | Local model (Ollama): privacy mode `private` | **No** — run by the developer only |

- **Environment separation (ADR-012):** each environment is a separate Compose project started from the same `deploy/compose.yaml`: `ledgerbridge-test` with `.env.test`, `ledgerbridge-pilot` with `.env.pilot`. Volumes are scoped per project and host ports differ per environment, so the two never share a database, cache or vector store. `.env.*.example` files are committed; real `.env.*` files are git-ignored. The data plane refuses `AI_PROVIDER=anthropic` when `APP_ENV=pilot` (PIL-005).

- **Auth:** `AUTH_MODE=local` stores users with Argon2id password hashes in `ledgerbridge_system.users` and issues tokens locally. In product mode the data plane instead verifies control-plane tokens via JWKS; authorization code is identical in both modes.

## Change log

| Date | Version | Change |
| --- | --- | --- |
| 2026-10-08 | 0.2 | Pilot mode (Section 13), ADR-009 to ADR-011. |
| 2026-10-09 | 0.3 | Environment separation (ADR-012), uv (ADR-013), connector framework details (Section 4.4), dev-only Tally seeding (ADR-014). |
| 2026-10-09 | 0.4 | AI data protection: Section 5 rewritten around privacy modes (5.4), the data protection gate with masking (5.5), outbound network allowlist (5.6) and model call log (5.7). ADR-015 supersedes ADR-004. Security summary and pilot table updated. Requirements AI-011 to AI-018 and SEC-010. |
| 2026-10-09 | 0.5 | Databases renamed to `ledgerbridge_source`, `ledgerbridge_accounting`, `ledgerbridge_reporting`, `ledgerbridge_system` (ADR-016); data-layers table (4.2) shows each layer's database; AI guardrail names `ai_ro` and its single database. |
| 2026-10-12 | 0.6 | M3: Section 4.4 describes the source-independent sync pipeline (fetch, raw store, map, transform, deletions, log); ADR-017 scheduled sync in the worker. |
| 2026-10-12 | 0.7 | ADR-018: deletion check on its own schedule (default hourly), separate from incremental syncs; Section 4.4 pipeline step 5. |
| 2026-10-12 | 0.8 | M4: Section 4.6 validation (as of a date, checks, profit carriers, tolerance, issue resolution) and alerts; ADR-019. |
| 2026-10-12 | 0.9 | ADR-020: short sync transactions, connections paused until activated, read-only company listing, safe error text (pilot run fixes). |
| 2026-10-12 | 0.10 | ADR-021: entities identified by source key; exact names; one shared lookup. |
| 2026-10-12 | 0.11 | ADR-022: chunked, resumable, entity-by-entity syncs; timeouts lead to a source check and splitting, not a resend. |
| 2026-10-19 | 0.32 | ADR-039: automated checks on every pull request. |
| 2026-10-16 | 0.31 | ADR-038: foreign-currency book value from the source's own vouchers; the opening difference as Tally's trial balance shows it. |
| 2026-10-16 | 0.30 | Section 4.8 Foreign currency; ADR-037: base currency stays the books, foreign-currency data alongside, source-calculated revaluations as snapshots. |
| 2026-10-16 | 0.29 | ADR-036: foreign-currency ledgers one by one; `validate compare-ledger`. |
| 2026-10-16 | 0.28 | ADR-035: foreign-currency ledgers at the source's book value. |
| 2026-10-16 | 0.27 | ADR-034: names as Tally resolves them; deleted masters. |
| 2026-10-15 | 0.26 | ADR-033: the source's own stock value and opening difference; stock ledgers at the stock value; effective dates; company numbers kept; stock values for M6 proposed. |
| 2026-10-15 | 0.25 | ADR-032: reliable dates (Educational mode). |
| 2026-10-15 | 0.24 | ADR-031: stock ledgers with integrated inventory; `validate analyse` ledger profiles. |
| 2026-10-15 | 0.23 | ADR-031: godown kinds and job work, stock journals read once, the source's own opening difference. |
| 2026-10-15 | 0.22 | ADR-030: one run lock per connection, tied to the run's heartbeat. Report: unfinished work before analysis in the next step. |
| 2026-10-14 | 0.21 | ADR-029: the source's counting rules (openings, stock moved once, what counts), reproduced on the test company. |
| 2026-10-14 | 0.20 | ADR-028: problem registry with stable codes, shared output layout, health report (OPS-005); Section 4.6 readable results. |
| 2026-10-14 | 0.19 | Section 4.6: `validate analyse` (VAL-010). |
| 2026-10-13 | 0.18 | Diagrams embedded in Sections 2 and 4.2 (docs/diagrams, generated ER and database diagrams, data flow levels 0 and 1). |
| 2026-10-13 | 0.17 | ADR-027: reference resolution rules, `transform explain`, voucher type tree and effective lines of non-posting voucher types. |
| 2026-10-13 | 0.16 | Budget planning and analysis: Section 4.7, data layers note, ADR-026 (user-entered data alongside source data). |
| 2026-10-13 | 0.15 | Section 4.4: `transform rebuild` re-transforms every stored object (DAT-008); retries and rebuilds only queue an object's latest raw record. |
| 2026-10-13 | 0.14 | ADR-025: `extra` JSON, field catalogue, promotion to dimensions, fitting values to columns, record-by-record retry of rejected batches. Section 4.6: thorough checks against the source's controls (VAL-005 to VAL-008) and root causes (VAL-009). |
| 2026-10-13 | 0.13 | ADR-024: background sync jobs with their output in `sync_logs` and `sync watch`; heartbeats, `interrupted` runs, stale-run detection and `sync abandon`; waiting for a busy source after a timeout; undeclared XML prefixes. |
| 2026-10-13 | 0.12 | ADR-023: unverified chunks never checkpointed; part-month support probed; whole-month retries with longer timeouts; effective timeout and pause; refetch from a date. |
