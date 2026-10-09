# Requirements: Accounting Data Integration & Analytics Platform

| Field | Value |
| --- | --- |
| Version | 0.4 (Draft) |
| Date | 2026-10-08 |
| Status | Draft for review. Requirements may be added or changed in any phase (see Section 10). |
| Related | `docs/architecture.md`, `CLAUDE.md` |

---

## 1. Purpose and vision

The platform connects to any accounting system or upstream data source, captures its data into a structured MySQL database, and provides dashboards, MIS reporting, AI-driven insights and natural-language querying on top of it.

The long-term vision (from client requirements) is for the platform to:

1. Act as an API connector to any transactional accounting system or upstream data-generating system.
2. Capture all key schema and data from those systems into a database.
3. Provide an analytics and AI layer with reporting, insights and predictive modelling.
4. Reconcile upstream and downstream systems.
5. Design a recommended chart of accounts from a business-model description, to fast-track new accounting implementations.
6. Provide OCR-based document scanning to automate accounting entries.

**Problems to solve:**

- Give a clear indication of business health.
- Flag good and bad performance in reporting.
- Become the CXO's go-to system for strategic and tactical decisions.
- Replace manual MIS preparation and manually built dashboards.

## 2. Product model and data sovereignty

- **PM-001** The platform is a product used by multiple client organizations.
- **PM-002** Each client organization may have multiple entities (companies), branches and data sources.
- **PM-003 (Core principle)** The platform provider stores **only** user login credentials, user-to-client mapping and licence information. No client accounting data, uploaded files, query results, reports, AI conversations or usage analytics are stored on provider infrastructure.
- **PM-004** All client data is stored and processed in a **client deployment** running in an environment the client owns: by default the client's own cloud account, or alternatively a client office server.
- **PM-005** Client data must never transit through provider servers. After login, the user's browser communicates directly with the client deployment.
- **PM-006** Each client's data is physically isolated from every other client's data.

### 2.1 Delivery approach: pilot first, built for all books

- **PIL-001** The first deliverable is a **local pilot** on the developer machine using the client's Tally backup data (two companies) restored into TallyPrime.
- **PIL-002** The pilot implements the data plane only. Control plane, licensing, connector agent and deployment packaging are deferred; a simple local login replaces control-plane login during the pilot.
- **PIL-003** Everything built for the pilot must be **generic**: no code specific to these companies, to backup data, or to Tally outside the Tally connector. The same code must later work for live Tally, other accounting books (Zoho, CSV/TXT and others) and other clients.
- **PIL-004** Backup data is loaded through the standard connector path (Tally XML interface), tagged `origin = backup`.
- **PIL-005** Client data is never read by AI development tools (Claude Code). Development and AI testing use a test company. AI querying on client data uses a local model unless the client approves another provider.

## 3. Users and roles

| Role | Description |
| --- | --- |
| Platform Admin (provider) | Manages client organizations, licences and client admin accounts. Has **no** access to client data. |
| Client Admin | Manages users, roles, entity access and data source connections within their organization. |
| Management / CXO | Views dashboards, MIS, consolidated views, insights; uses AI querying. |
| Finance Manager | Full reporting and analysis across assigned entities. |
| Accountant | Reporting and data validation for assigned entities. |
| Viewer / Auditor | Read-only access to assigned reports and audit logs. |

Roles are configurable; the list above is the default set.

## 4. Functional requirements

Priority: **P1** = phase 1, **P2** = phase 2, **P3+** = later phases.

### 4.1 Authentication and licensing (provider control plane)

| ID | Requirement | Priority |
| --- | --- | --- |
| AUTH-001 | Users log in through the provider control plane with email and password. | P1 |
| AUTH-002 | Passwords are stored only as salted one-way hashes (e.g. Argon2id). | P1 |
| AUTH-003 | Multi-factor authentication is supported and can be enforced per client. | P1 |
| AUTH-004 | Optional sign-in with Microsoft Entra ID or Google Workspace. | P2 |
| AUTH-005 | After login, the user receives a short-lived signed token identifying the user and their client, plus the address of that client's deployment. | P1 |
| AUTH-006 | The control plane verifies the client's licence is active before issuing a token. | P1 |
| AUTH-007 | Password reset, account lockout after repeated failures, and session expiry are supported. | P1 |

### 4.2 Access control and authorization (client deployment)

| ID | Requirement | Priority |
| --- | --- | --- |
| ACC-001 | Roles and permissions are stored and enforced inside the client deployment, not on the control plane. | P1 |
| ACC-002 | Access can be restricted by entity, branch, report and feature (e.g. AI querying). | P1 |
| ACC-003 | Sensitive fields (e.g. salaries, bank account numbers, party names) can be masked per role. | P2 |
| ACC-004 | Client Admins manage users' roles and access through the dashboard. | P1 |

### 4.3 Data source connectors

| ID | Requirement | Priority |
| --- | --- | --- |
| CON-001 | A pluggable connector framework: each source is an adapter implementing a standard interface (test connection, list entities, fetch masters, fetch transactions incrementally, map to the canonical model). | P1 |
| CON-002 | Tally connector, version-agnostic across TallyPrime and Tally.ERP 9, using Tally's XML/HTTP interface. | P1 |
| CON-003 | File connector for CSV and TXT data files, via upload or watched folder, with a column-mapping screen. | P1 |
| CON-004 | Zoho Books connector via its API. | P2 |
| CON-005 | Bank statement and banking report connector (CSV, Excel, PDF statements; bank APIs where available). | P2 |
| CON-006 | Generic database connector to read upstream/ERP systems with read-only credentials. | P2 |
| CON-007 | Additional accounting platform connectors (e.g. QuickBooks, Busy, Xero) added on demand. | P3+ |
| CON-008 | All connectors are read-only towards source systems; the platform never writes back. | P1 |
| CON-009 | Connection credentials are stored encrypted inside the client deployment only. | P1 |
| CON-010 | Client Admins can add, test, edit, pause and remove connections from the dashboard. | P1 |
| CON-011 | Ledger and account mapping screen to map source chart of accounts to the canonical/standard structure, with AI-suggested mappings confirmed by a user. | P2 |

### 4.4 Data synchronization

| ID | Requirement | Priority |
| --- | --- | --- |
| SYN-001 | Near real-time sync. Target: changes visible within 5 minutes (interval configurable per connection). | P1 |
| SYN-002 | Incremental sync: only new or changed records are fetched (Tally AlterID/MasterID; API change filters or webhooks for cloud sources). | P1 |
| SYN-003 | Deletions and alterations in source systems are detected and reflected. | P1 |
| SYN-004 | A connector agent can run on the machine hosting Tally or other on-premise sources and push data outbound to the client deployment; it queues data locally if the connection drops. | P1 |
| SYN-005 | Every sync run is logged (start, end, records, errors). | P1 |
| SYN-006 | Sync failures and validation failures trigger alerts to configured users (email; in-app). | P1 |

### 4.5 Historical and backup data import

| ID | Requirement | Priority |
| --- | --- | --- |
| IMP-001 | Import historical data from company inception. | P1 |
| IMP-002 | Supported backup sources: Tally data (restored into a Tally instance and extracted via the Tally connector), TXT files, and data dumps. Zoho historical export. | P1 (Zoho: P2) |
| IMP-003 | Backup imports can be one-time or recurring. | P1 |
| IMP-004 | Every record keeps its origin (source system, connection, import batch, timestamp). | P1 |
| IMP-005 | Overlap between backup and live data is resolved by configurable rules. **Proposed default:** live source data wins for periods available live; backup data fills periods not available live. (Assumption, to confirm: see Open items.) | P1 |
| IMP-006 | Imported data passes the same validation as live data (Section 4.7). | P1 |

### 4.6 Data model and storage

| ID | Requirement | Priority |
| --- | --- | --- |
| DAT-001 | MySQL 8 is the primary database, located in the client deployment. | P1 |
| DAT-002 | Three data layers: raw (as received), canonical (standardized accounting model), reporting (views and aggregates). | P1 |
| DAT-003 | The canonical model is source-independent: data from any source is represented the same way. | P1 |
| DAT-004 | Supports multiple entities, branches and consolidated views. | P1 |
| DAT-005 | Flexible reporting dimensions so reporting is not restricted: entity, branch, cost centre, project, product/item, party, ledger group, period, currency, and user-defined dimensions. | P1 |
| DAT-006 | Configurable financial year per entity. | P1 |
| DAT-007 | Multi-currency amounts with base-currency conversion. | P2 |
| DAT-008 | Raw data can be reprocessed into the canonical layer when mapping rules change, without re-fetching from the source. | P1 |

### 4.7 Validation and reconciliation

| ID | Requirement | Priority |
| --- | --- | --- |
| VAL-001 | After each sync/import: every voucher balances (debits = credits); trial balance balances. | P1 |
| VAL-002 | Closing balances per ledger match the source system's own figures; mismatches are flagged. | P1 |
| VAL-003 | A data-quality dashboard shows validation status per entity and source. | P1 |
| VAL-004 | Reconciliation between upstream and downstream systems (e.g. sales system vs accounting, bank vs books). | P3+ |

### 4.8 Reporting and dashboards

| ID | Requirement | Priority |
| --- | --- | --- |
| RPT-001 | MIS dashboard for management, replacing manual MIS preparation. | P1 |
| RPT-002 | Business health indicators with good/bad flags (configurable thresholds). | P1 |
| RPT-003 | Standard statements: Profit & Loss, Balance Sheet, Cash Flow, Trial Balance. | P1 |
| RPT-004 | Receivables and payables with ageing. | P1 |
| RPT-005 | GST reports, stock/inventory reports, sales and expense analysis. | P2 |
| RPT-006 | Entity-level and consolidated reporting. | P1 |
| RPT-007 | Drill-down from any figure to underlying vouchers. | P1 |
| RPT-008 | Filters across all dimensions in DAT-005; period comparisons (MoM, YoY, vs budget where available). | P1 |
| RPT-009 | Export to Excel and PDF. | P2 |
| RPT-010 | Scheduled reports by email, generated inside the client deployment. | P2 |
| RPT-011 | Over time, "all reports" requested by the client will be delivered; the phase 1 report set is listed in RPT-001 to RPT-004 and RPT-006 to RPT-008, pending confirmation. | — |

### 4.9 AI layer

| ID | Requirement | Priority |
| --- | --- | --- |
| AI-001 | Natural-language questions answered by generating read-only SQL against a curated semantic layer (text-to-SQL), executing it, and explaining the result. | P1 |
| AI-002 | Every AI answer shows the query used and allows drill-down to source records. | P1 |
| AI-003 | AI database access is read-only, limited to the semantic layer, with row limits and timeouts. | P1 |
| AI-004 | Respects the user's access rights (ACC-002) and masking rules (ACC-003). | P1 |
| AI-005 | **Withdrawn (2026-10-09), replaced by AI-011 to AI-014.** ~~Pluggable model provider configured per client. Default: model accessed through the client's own cloud account (e.g. Claude via AWS Bedrock or Google Vertex AI). Option: open-weight model hosted on client hardware. No client data is sent to provider infrastructure.~~ | — |
| AI-006 | **Withdrawn (2026-10-09), replaced by AI-015.** ~~Sensitive fields can be masked before any data is sent to the model.~~ | — |
| AI-007 | Automated insights and alerts (anomalies, threshold breaches, trend changes). | P2 |
| AI-008 | AI-generated reports and commentary on MIS. | P2 |
| AI-009 | Predictive modelling (cash flow, revenue, expense forecasts). | P3+ |
| AI-010 | Retrieval (RAG) over schema documentation, business definitions and uploaded documents to improve answers. Embeddings are always computed locally (AI-016). | P2 |

#### 4.9.1 AI data protection

No AI feature may send client data anywhere the client hasn't approved. These requirements apply to every AI feature, current and future (AI-001 to AI-010).

| ID | Requirement | Priority |
| --- | --- | --- |
| AI-011 | **AI privacy mode, set per client:** `private` (**default**), `schema-only` or `full`. Only a Client Admin can change it, and every change is recorded in the audit log (AUD-001). A deployment uses exactly one model provider per mode (AI-014, SEC-010). | P1 |
| AI-012 | **`private` mode:** every model call (SQL generation, explanation, formatting, embeddings) uses a model running inside the client deployment or on client hardware. Nothing related to AI leaves the client environment. | P1 |
| AI-013 | **`schema-only` mode:** the external model receives **only** the user's question (masked under AI-015) and semantic-layer descriptions (view and column names, their descriptions, business definitions). It never receives query results, data rows, sample values, ledger or party names, or any figures from the books. The generated SQL is validated and run locally (AI-003). Results are **never** sent to the external model; they're formatted locally, by deterministic templates or a local model. | P1 |
| AI-014 | **`full` mode:** an external model reached **only through the client's own cloud account** under the client's agreement (e.g. Claude via AWS Bedrock or Google Vertex AI). Everything sent, including any result data, is masked first (AI-015). A provider's public API reached outside the client's own account is not allowed for client data. | P1 |
| AI-015 | **Masking and pseudonymization:** before anything is sent to an external model (`schema-only` and `full`), party names, GSTINs, PANs, bank account numbers and salary amounts are replaced with consistent placeholder tokens (e.g. `PARTY_017`). The mapping between tokens and real values stays in the client deployment and is never sent. Responses are converted back locally before the user sees them. Masking also applies the role rules of ACC-003. | P1 |
| AI-016 | **Local embedding model for RAG:** embeddings of the semantic catalog, business definitions, ledger names and documents are computed by a model running locally, in every privacy mode, and stored only in the client's vector store. | P1 |
| AI-017 | **No outbound tools for the AI:** models get no tools or functions that can send, store or publish data (no web access, HTTP calls, email, messaging, file writes or uploads). The only action a model can trigger is a validated, read-only query against the semantic layer, run by application code (AI-003). | P1 |
| AI-018 | **Audit of every model call:** for every call to any model, local or external, the client's audit log records user, time, privacy mode, provider, endpoint, model, the exact payload as sent (after masking), the response as received, token counts and outcome. Stored only in the client deployment, append-only (AUD-002), visible to Client Admins. Token mappings (AI-015) are never written to it. | P1 |

### 4.10 Future modules

| ID | Requirement | Priority |
| --- | --- | --- |
| FUT-001 | Chart-of-accounts designer: generates a recommended chart of accounts from a business-model description. | P3+ |
| FUT-002 | OCR document scanning (invoices, bills, receipts) to extract data and propose accounting entries for user approval. | P3+ |
| FUT-003 | Fast-track setup toolkit for companies implementing a new accounting system. | P3+ |

### 4.11 Audit

| ID | Requirement | Priority |
| --- | --- | --- |
| AUD-001 | Audit log of logins, report views, AI queries, exports, connection changes and permission changes, stored inside the client deployment. | P1 |
| AUD-002 | Audit logs are read-only and retained per client-configured policy. | P1 |

## 5. Non-functional requirements

### 5.1 Security

- **SEC-001** Encryption in transit (TLS 1.2+) for all connections, including agent to deployment.
- **SEC-002** Encryption at rest for databases, backups and stored files in the client deployment.
- **SEC-003** Secrets (connection credentials, keys) stored encrypted, never in source code or logs.
- **SEC-004** Release builds (container images, frontend bundle) are signed; client deployments verify signatures before updating.
- **SEC-005** The dashboard enforces a Content Security Policy allowing it to contact only the control plane (for login) and that client's own deployment.
- **SEC-006** Clients may self-host the dashboard frontend if they require full control.
- **SEC-007** No telemetry, usage analytics or crash reports containing client data are sent to the provider.
- **SEC-008** Principle of least privilege for all service accounts and database users.
- **SEC-009** Dependency and container vulnerability scanning in the build pipeline.
- **SEC-010** **Outbound network allowlist for the data plane:** the data plane may connect out only to its configured sources (e.g. Tally, Zoho, banks) and to the **one** AI endpoint approved for the client's privacy mode (none in `private` mode, AI-011). Everything else is blocked. The allowlist is enforced at the network level (container egress rules) and checked again in application code. Changes to it are audited.

### 5.2 Performance (initial targets, to validate)

- **PER-001** Dashboard pages load within 3 seconds for typical date ranges.
- **PER-002** AI query answers within 15 seconds for typical questions.
- **PER-003** Sync latency within 5 minutes (SYN-001).
- **PER-004** Handles at least 10 years of history and 50 entities per client deployment without redesign.

### 5.3 Reliability and operations

- **OPS-001** Client deployment installs from a single packaged release (Docker-based).
- **OPS-002** Automated daily database backups inside the client environment.
- **OPS-003** Versioned releases with database migrations that run automatically on update.
- **OPS-004** Health monitoring visible to the Client Admin locally.

### 5.4 Maintainability

- **MNT-001** One codebase serves all clients; client-specific behaviour is configuration, not code forks.
- **MNT-002** New connectors can be added without changing the core data model or other connectors.
- **MNT-003** Automated tests for connectors, data transformations, validation and access control.

## 6. Phase plan

| Phase | Scope |
| --- | --- |
| **Phase 1a: Local pilot** | Repo scaffold; Tally connector (multi-company, incremental); import of the client's backup data; canonical data model; validation against Tally; local login and role-based access; reporting views; MIS dashboard, health indicators, core statements, receivables/payables, entity and consolidated views, drill-down; natural-language querying (text-to-SQL + RAG); audit log. See `docs/roadmap.md`. |
| **Phase 1b: Product foundation** | Control plane (login, MFA, licences); client deployment package; connector framework; Tally connector and agent; CSV/TXT connector; historical import; canonical data model; validation; MIS dashboard, health indicators, core statements, receivables/payables, entity and consolidated views, drill-down; role-based access; natural-language querying; audit log. |
| **Phase 2: Expansion** | Zoho Books, banking and database connectors; account mapping with AI suggestions; GST, stock, sales and expense reports; exports and scheduled reports; field masking; AI insights, alerts and commentary; RAG over documents; SSO; multi-currency. |
| **Phase 3: Intelligence** | Predictive modelling; upstream/downstream reconciliation; additional platform connectors. |
| **Phase 4: Automation** | OCR document scanning; chart-of-accounts designer; implementation fast-track toolkit. |

## 7. Open items

Open items are deferred. Development proceeds on the current requirements and assumptions; each item is raised with the client when the related feature is built.

| ID | Item | Status |
| --- | --- | --- |
| OPEN-001 | Who verifies that platform figures match the books, and must every figure match the source exactly? (Q15) | Deferred: ask when feature is built |
| OPEN-002 | What must the first version do to be considered successful? (Q16) | Deferred: ask when feature is built |
| OPEN-003 | Confirm the phase 1 report set (client answered "all reports"). | Deferred: ask when feature is built |
| OPEN-004 | Confirm overlap rule for backup vs live data (IMP-005). | Deferred: ask when feature is built |
| OPEN-005 | Which specific upstream systems must be supported, and in which order? | Deferred: ask when feature is built |
| OPEN-006 | 10 to 20 real example questions users will ask the AI (needed to design and test the semantic layer). | Deferred: ask when feature is built |
| OPEN-007 | ~~Confirm acceptance of AI via the client's own cloud account as the default~~. **Partly resolved 2026-10-09:** the default is now `private` (local model, AI-011), matching the client's "ideally no" to external AI. Still open: whether the client wants `schema-only` or `full` at all, and the local model's minimum hardware. | Open: ask when M8 is built |

## 8. Assumptions

- Tally versions in scope support the XML/HTTP interface (TallyPrime and Tally.ERP 9).
- "Real time" means near real-time (minutes), since Tally does not push change events.
- Clients can provide a cloud account or a server to host their deployment.
- Clients are primarily India-based (GST, April–March financial year as default), with configuration for other regions.

## 9. Glossary

- **Control plane:** provider-hosted service for login and licences only.
- **Client deployment (data plane):** the client-hosted system holding all client data and processing.
- **Connector agent:** small service installed near an on-premise source (e.g. Tally) that pushes data to the client deployment.
- **Canonical model:** the standardized, source-independent accounting data model.
- **Semantic layer:** curated database views with business definitions, used by reports and the AI.
- **AI privacy mode:** a per-client setting (`private`, `schema-only`, `full`) that fixes which model may be used and what it may receive (AI-011).
- **Pseudonymization:** replacing sensitive values with consistent placeholder tokens before sending, with the token-to-value mapping kept locally so answers can be converted back (AI-015).

## 10. Change management

Requirements can be added or changed in any phase. For each change:

1. Add or edit the requirement in this file with a new ID (never reuse IDs; mark removed ones as `Withdrawn`).
2. If it affects design, update `docs/architecture.md` and add a decision record entry.
3. Record the change in the change log below.
4. Implement it in Claude Code by referencing the requirement ID.

### Change log

| Date | Version | Change |
| --- | --- | --- |
| 2026-10-08 | 0.1 | Initial draft from client answers and architecture decisions. |
| 2026-10-08 | 0.2 | Open items deferred until related features are built. |
| 2026-10-08 | 0.3 | Added pilot-first delivery approach (Section 2.1) and Phase 1a. |
| 2026-10-09 | 0.4 | AI data protection (Section 4.9.1): AI-011 to AI-018 (privacy modes with `private` as default, `schema-only`, `full`; masking; local embeddings; no outbound tools; audit of every model call) and SEC-010 (outbound network allowlist). AI-005 and AI-006 withdrawn and replaced. OPEN-007 partly resolved. See ADR-015. |
