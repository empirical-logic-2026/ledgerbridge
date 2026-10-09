# Architecture: Accounting Data Integration & Analytics Platform

| Field | Value |
| --- | --- |
| Version | 0.4 (Draft) |
| Date | 2026-10-08 |
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

| Layer | Purpose | Examples |
| --- | --- | --- |
| **Raw** | Data exactly as received, with source metadata. Enables reprocessing (DAT-008). | `raw_records` (source, connection, batch, entity type, payload JSON, received_at) |
| **Canonical** | Standard, source-independent accounting model. | ledgers, vouchers, voucher lines, parties |
| **Reporting** | Views and aggregates used by dashboards and AI (the semantic layer). | `v_trial_balance`, `v_pnl_monthly`, `v_receivables_ageing` |

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

In code, the interface is the `Connector` protocol in `data-plane/connectors/base.py`; `fetch_*` return iterators of `RawRecord` so large sources stream. A registry maps a source code (`tally`, later `file`, `zoho`, ...) to its connector. Storing raw records (`core/raw_store.py`) and running an extraction (`workers/extract.py`, `python -m workers.cli`) are source-independent; nothing outside `connectors/<source>/` knows about a particular source.

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

- Dedicated read-only MySQL user with access only to reporting views.
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

The mode is a per-client setting held in the data plane (`app.settings`). Only a Client Admin can change it, and the change is audited. The default for every new deployment is `private`.

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
   - **party names**: matched against the known party and ledger master (`core.parties`, party ledgers), not guessed
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

Every call to any model, local or external, writes one append-only record in the client's database: user, time, mode, provider, endpoint, model, the payload **as sent after masking**, the response **as received**, token counts, duration and outcome. It extends `app.ai_query_log` (one row per question) with one row per model call. The exact table is designed in M8, and `docs/schema.md` is updated then. Client Admins can view it. Retention follows AUD-002.

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
| Supply chain | Signed images and bundles, verified on update; dependency and image scanning in CI. |
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
| ADR-012 | Each environment runs as its own Docker Compose project (`ledgerbridge-test`, `ledgerbridge-pilot`) with its own volumes, host ports and env file. | Keeps the schema names `raw`, `core`, `rpt`, `app` identical in every environment while keeping data physically separate. |
| ADR-013 | uv manages Python versions and dependencies for the data plane (`pyproject.toml` + `uv.lock`). | Reproducible locked installs and a pinned Python 3.12 independent of the host Python. |
| ADR-014 | One narrow exception to "read-only towards sources" (CON-008): the developer-only seeding tool in `data-plane/devtools/tally_seed` may send Tally **Import** requests, and only to the test company. It refuses to run unless `APP_ENV=test`, exactly one company is loaded and its name matches the target exactly. It is never imported by product code, is excluded from the Docker image (`.dockerignore`), and connectors keep their Export-only client. | The test company needs realistic, repeatable data (bills, GST, cancelled and altered vouchers) to prove extraction and the sign convention; hand entry is slow and not repeatable. |
| ADR-015 | AI data protection by design, replacing ADR-004. Per-client privacy mode: `private` (default, local model only), `schema-only` (external model sees only the masked question and semantic-layer descriptions; SQL and result formatting stay local) or `full` (external model only via the client's own cloud account, everything masked). One data protection gate pseudonymizes party names, GSTIN, PAN, bank accounts and salaries and reverses them locally. Embeddings are always local. Models have no outbound tools. A network allowlist limits egress to configured sources plus one approved AI endpoint. Every model call is logged with its exact payload. | The client answered "ideally no" to external AI (OPEN-007), and accounting data is highly sensitive. Making `private` the default, enforcing what can be sent in code and at the network level rather than in prompts, and logging every payload means a bug or prompt injection can't quietly leak data, while clients who choose an external model still get better SQL from it. |

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

- **Auth:** `AUTH_MODE=local` stores users with Argon2id password hashes in `app.users` and issues tokens locally. In product mode the data plane instead verifies control-plane tokens via JWKS; authorization code is identical in both modes.

## Change log

| Date | Version | Change |
| --- | --- | --- |
| 2026-10-08 | 0.2 | Pilot mode (Section 13), ADR-009 to ADR-011. |
| 2026-10-09 | 0.3 | Environment separation (ADR-012), uv (ADR-013), connector framework details (Section 4.4), dev-only Tally seeding (ADR-014). |
| 2026-10-09 | 0.4 | AI data protection: Section 5 rewritten around privacy modes (5.4), the data protection gate with masking (5.5), outbound network allowlist (5.6) and model call log (5.7). ADR-015 supersedes ADR-004. Security summary and pilot table updated. Requirements AI-011 to AI-018 and SEC-010. |
