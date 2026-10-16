# Requirements: Accounting Data Integration & Analytics Platform

| Field | Value |
| --- | --- |
| Version | 0.20 (Draft) |
| Date | 2026-10-16 |
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

Budget permissions (BUD-013) are granted per role: by default Management / CXO and Finance Manager have `budget.view`, `budget.edit` and `budget.approve`; Accountant has `budget.view` and `budget.edit`; Viewer / Auditor has `budget.view`.

Foreign-currency permission (FX-012): by default Management / CXO, Finance Manager and Accountant have `forex.view`; Viewer / Auditor has it too, read-only like everything they see.

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
| SYN-006 | Sync failures and validation failures trigger alerts to configured users (email; in-app). Phase 1a delivers the log and in-app channels; email follows (architecture ADR-019). | P1 |

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
| DAT-009 | Fields a source sends that have no column in the canonical model (e.g. Tally user-defined fields from TDL customisations) are kept per record, catalogued per entity and object type, and can be promoted to reporting dimensions by an explicit command, without schema changes at run time. | P1 |
| DAT-011 | References by name (a ledger's group, a voucher's ledgers, cost centres, stock items, voucher types) resolve by defined rules: exact name first, then a known alias (e.g. a renamed reserved group's reserved name), then a defined normalisation applied to both sides (XML entities, Unicode NFC, spaces, case), each accepted only if exactly one candidate fits; otherwise the record fails with a clear reason. Normalised matches are reported as warnings (counts only), and a diagnostic explains references that don't resolve without showing names or values. | P1 |
| DAT-012 | Figures follow the source's own counting rules, verified against the source's own reports on the test company: opening balances and opening quantities are the masters' openings at the books' beginning (never a balance at a later period's start); a stock movement recorded twice (a delivery or receipt note and the invoice tracked to it) moves stock once, where the source moves it; vouchers that the source keeps out of the books (optional, memorandum, reversing journals) don't count, while custom types derive their behaviour from the source's standard type; stock held at a job worker's location counts as the source counts it (Tally: not in stock balances), and the source's own difference in opening balances, as its trial balance from the books' beginning shows it, is what the opening check reports; a voucher's effective date is kept but balances count by the voucher's date, as the source does. | P1 |
| DAT-010 | A value that doesn't fit its column (too long, out of range, invalid date or characters) never fails other records: it is kept in full, never truncated, and flagged. Problems are reported by kind, table, column and size, never the value. | P1 |

### 4.7 Validation and reconciliation

| ID | Requirement | Priority |
| --- | --- | --- |
| VAL-001 | After each sync/import: every voucher balances (debits = credits); trial balance balances. | P1 |
| VAL-002 | Closing balances per ledger match the source system's own figures; mismatches are flagged. | P1 |
| VAL-003 | A data-quality dashboard shows validation status per entity and source. | P1 |
| VAL-004 | Reconciliation between upstream and downstream systems (e.g. sales system vs accounting, bank vs books). | P3+ |
| VAL-005 | The number of vouchers per month and voucher type matches the source's own count. | P1 |
| VAL-006 | Each stock item's closing quantity matches the source's. | P1 |
| VAL-007 | Each party's bill-wise outstanding matches the source's. | P1 |
| VAL-008 | Ledger closing balances match the source at every financial year end, not only the validation date. | P1 |
| VAL-010 | An analysis of validation mismatches tests explanations that can be checked automatically (opening balances, signs, voucher types counted differently, cancelled, optional and post-dated vouchers, financial year boundaries, units, stock journals, tracked notes, rounding, foreign currency, bills), alone and in pairs, and reports how many mismatches each explains; differing ledgers are broken down by primary group and whether the opening explains them, and unexplained ones by the first month (of the first financial year) where they differ and the voucher types that month; each differing ledger gets an anonymous profile (where it sits, kind, nature, renamed reserved group, stored opening against the source's, voucher types posting to it, when and whether by a constant amount, what the difference equals); for a ledger that matches at one date and differs at the next, the dates are narrowed (on reliable dates) to when it starts to differ and when it matches again, with the vouchers posting to it then by kind, voucher type and effective date, and whether one voucher's line, lines or total equal the difference; whether two ledgers' differences cancel out; which lines of any voucher in that window equal the difference, the kind of ledger they are on here and how the name was matched (exact, alias, normalised, a name several ledgers share, a ledger deleted in the source); the stored vouchers naming the ledger and ledger lines in lists not read; stock ledgers at the source's stock value count as explained, as in validation; the opening difference per primary group. Counts and the source's standard names only. | P1 |
| VAL-013 | Each ledger kept in a foreign currency is compared, on its own, with the source's book value (its vouchers only, as the source's ledger vouchers show them without a calculated revaluation line), not with its closing balance revalued at current exchange rates; a note says so. Each voucher line keeps its foreign currency amount. | P1 |
| VAL-014 | One ledger's vouchers in the source can be compared with ours voucher by voucher on demand (`validate compare-ledger`): matched by the source's key, else by date, number and type; printed as counts by voucher type and month and kinds only; the details (dates, voucher numbers, amounts) go to a local, git-ignored file for the developer and are never printed. | P1 |
| VAL-012 | Stock ledgers (Tally: under Stock-in-Hand) that the source reports at its closing stock value, not at their own opening and postings, are compared with that value as of each date validated; otherwise ledger by ledger. A note says which. | P1 |
| VAL-011 | Validation and its analysis compare figures only on dates the source answers reliably (Tally in Educational mode: the 1st, 2nd and 31st of a month): "as of" moves back to the latest reliable date, month and year ends forward to the next one; the output shows the dates used. The mode is detected where the source says, or set on the connection. | P1 |
| VAL-009 | Validation results name the root cause: records that failed to transform, and how many other failures are likely their consequences. | P1 |

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
| RPT-008 | Filters across all dimensions in DAT-005; period comparisons (MoM, YoY, vs budget where available; budgets in Section 4.12). | P1 |
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

### 4.12 Budget planning and analysis

Budgets are data the client enters or imports, kept alongside the data synced from the books and never mixed with it (ADR-026). Amounts follow the money rules of the rest of the platform (DECIMAL, exact). Everything here respects the user's entity access (ACC-002).

**Creating budgets**

| ID | Requirement | Priority |
| --- | --- | --- |
| BUD-001 | Budgets are kept **per entity and financial year**. A consolidated budget is the sum of the companies' budgets by standard account; a budget can also be entered directly for the consolidated group, by standard account. | P1 |
| BUD-002 | A budget can be created four ways: **importing the source's own budgets** (Tally budgets, through the read-only connector); **entering it in a month-by-account grid**; **uploading an Excel template** downloaded from the platform (accounts as rows, months as columns), with every row checked and errors reported by row and column; **copying last year's actuals** with a growth percentage, overall or per account. | P1 |
| BUD-003 | A yearly amount can be **spread to months** equally or by **last year's seasonality** (each month's share of last year's actual for that account, falling back to equal when last year has no usable pattern). Months can then be edited one by one. The monthly amounts of a line always **sum exactly to its yearly amount**; rounding differences go to the last month. | P1 |
| BUD-004 | A budget line is set at one **level**: standard account (RPT-006), account group as kept in the source (e.g. a Tally group), or optionally ledger; and optionally per **cost centre** and per **custom dimension** (DAT-005, including fields promoted under DAT-009). | P1 |
| BUD-005 | **Versions:** each budget has an *original* version and any number of *revised* versions, each with a state: **draft**, **approved** or **locked**. Only drafts can be changed. Approving needs `budget.approve`; by default the approver must not be the last person who edited it. A locked version can't be changed or unlocked except by a Client Admin, recorded in the audit log. Analysis uses the latest approved or locked version unless the user picks another. | P1 |
| BUD-006 | **Every change is audited:** who, when, which line and month, old and new amount, and how (grid edit, spread, import, upload, copy, approval, lock). The history is append-only and visible on the budget. | P1 |

**Analysing budgets**

| ID | Requirement | Priority |
| --- | --- | --- |
| BUD-007 | **Budget vs actual vs last year** for any month, quarter, year to date or full year, per company and consolidated, at the budget's level and rolled up (e.g. ledgers to groups to standard accounts). Actuals follow the reporting rules (as of a date, effective vouchers only). | P1 |
| BUD-008 | **Variance** in amount and percentage (variance ÷ budget; shown as "n/a" when the budget is zero), marked **favourable or unfavourable by the account's nature**: for income, actual above budget is favourable; for expenses, actual below budget is favourable; balance-sheet lines show the variance without a judgement. | P1 |
| BUD-009 | **Full-year projection:** actual year to date plus the budget for the remaining months, compared with the full-year budget. | P1 |
| BUD-010 | **Drill-down** from any actual figure to its vouchers (RPT-007), and from any budget figure to its lines and change history. | P1 |
| BUD-011 | **Variance alerts:** configurable rules (percentage and amount thresholds, unfavourable only by default, per account or for all, by month, quarter or year to date) raise alerts that appear in "Needs your attention" on the home page, with a suggested action. | P1 |
| BUD-012 | **Interactive graphs**, all driven by the same filters (financial year, month range, company or consolidated, cost centre, account): monthly budget vs actual bars with last year as a line; cumulative year-to-date lines (budget, actual, last year); a variance waterfall from budgeted to actual profit; an account-by-month variance heatmap. Every point drills down (BUD-010). | P1 |

**Access and AI**

| ID | Requirement | Priority |
| --- | --- | --- |
| BUD-013 | Permissions `budget.view` (see budgets and analysis), `budget.edit` (create and change drafts, import, upload, copy) and `budget.approve` (approve and lock), checked in the data plane on every request (ACC-001). | P1 |
| BUD-014 | **AI questions about budgets** (AI-001), e.g. "Which expenses are over budget this quarter?", "What is the projected full-year profit against budget?". Budget figures get the same protection as actuals (AI-011 to AI-018): in `schema-only` mode they never leave the deployment. | P1 |
| BUD-015 | Importing source budgets is **read-only** towards the source (CON-008); imported budgets keep their source key and origin, and a re-import updates the draft it created without touching user edits made in later versions. | P1 |
| BUD-016 | Budgets can be exported to Excel in the same template layout (RPT-009). | P2 |

### 4.13 Foreign currency

The books stay in the **base currency** (INR): base amounts are the source of truth for every statement, balance and validation. Foreign-currency information is kept **alongside** them, in its own columns and tables, for three uses: customer and supplier balances and dues in their own currency; exchange gains and losses, realised and unrealised; and currency exposure for management. Nothing here changes a base-currency figure. Figures the source calculates (its revaluation at current rates, its unadjusted gain or loss, its rate lists) are stored as **source figures with the date they apply to**, never as vouchers (ADR-037). Everything here respects the user's entity access (ACC-002).

**Data**

| ID | Requirement | Priority |
| --- | --- | --- |
| FX-001 | Every foreign-currency voucher line keeps its **currency, foreign amount, exchange rate and base amount** (the base amount is the books' figure; the rate as the source wrote it, else base ÷ foreign). Ledgers kept in a foreign currency keep their currency and their opening balance in it; bill allocations keep their foreign amount. Base-currency lines keep none of these. | P1 |
| FX-002 | A **foreign-currency transactions** table holds every foreign-currency entry: date, voucher, voucher type, ledger, party, currency, foreign amount, rate, base amount and whether it counts in the books. It is filled by the transform and replaced with its voucher, like the voucher's other child rows. | P1 |
| FX-003 | **Exchange-rate history** per currency and date: from the source's own rate lists where they exist (Tally: the currency's standard, buying and selling rates), otherwise from the rates on its vouchers (per currency and date, weighted by foreign amount). Each rate records **where it came from** (the source's list and which kind, or vouchers and how many). | P1 |
| FX-004 | **Revaluation snapshots:** the source's own calculated unrealised gain or loss per foreign-currency ledger (Tally: the "Unadjusted Forex Gain/Loss" line of its Ledger Vouchers report) at each month end, financial year end and validation date, with the ledger's foreign balance, book value and revalued value as the source shows them. Stored as source figures; **never** posted as vouchers or added to any base-currency balance. | P1 |
| FX-005 | **Realised gains and losses** from (a) forex adjustment journals: lines posted to the ledgers set as forex gain/loss ledgers per entity (the source's own posted figures); and (b) bills settled at a different rate from the one they were raised at: the base amount of the settlement less the base amount of the settled part at the bill's original rate (calculated here). Each records its method, voucher, party, currency and date. | P1 |
| FX-006 | **Balances in the original currency** per ledger and party **at any date**: the opening in that currency plus the foreign amounts of counted lines dated on or before it, like base-currency balances (as of a date). | P1 |

**Validation**

| ID | Requirement | Priority |
| --- | --- | --- |
| FX-007 | Each foreign-currency ledger's **balance in its own currency** is compared with the source's own (Tally: the foreign part of its closing balance), in addition to the base-currency book value (VAL-013). A difference is a validation failure, counted and coded like the others. | P1 |

**Reports**

| ID | Requirement | Priority |
| --- | --- | --- |
| FX-008 | **Party balances and ageing in their own currency:** per customer and supplier, the balance and outstanding bills by ageing bucket in the currency they are kept in, with the base-currency book value beside them. | P1 |
| FX-009 | **Currency exposure** per currency: open receivables, payables and net position in the currency, with base-currency equivalents at book value and at the latest rate (showing that rate's date and source), per company and consolidated. | P1 |
| FX-010 | **Realised vs unrealised gains and losses** by period, currency and party: realised from FX-005, unrealised from the latest revaluation snapshot in the period (FX-004), with drill-down to vouchers or to the snapshot. | P1 |
| FX-011 | **Exchange-rate history** per currency, with each rate's source (FX-003). | P1 |

**Access and AI**

| ID | Requirement | Priority |
| --- | --- | --- |
| FX-012 | Permission **`forex.view`** for every foreign-currency report and API, checked in the data plane on every request together with the user's entity access (ACC-001, ACC-002). | P1 |
| FX-013 | **AI questions about currencies** (AI-001), e.g. "What is our net USD exposure today?", "Which customers owe us in euros, and how old are their bills?", "What were realised and unrealised exchange gains last quarter?". Foreign-currency figures get the same protection as other figures (AI-011 to AI-018). | P1 |

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
- **OPS-005** Operational output is easy to read and act on: one health report with an overall verdict (OK, ATTENTION NEEDED, FAILED), sections (connection, data loaded, work in progress with the exact resume command, validation per company, warnings) and, for every problem, what it means, its likely cause (root causes separated from their consequences) and the next step as an exact command. Every error and warning has a plain-language name and a stable code (LB-SYNC, LB-TRF, LB-VAL, LB-CON, LB-SYS) documented in an error catalogue; all commands use the same names, codes and layout; validation counts are compared with the previous run; status is coloured in the terminal with a plain fallback; each report is saved as a dated Markdown file that holds no names, values or amounts.

### 5.4 Maintainability

- **MNT-001** One codebase serves all clients; client-specific behaviour is configuration, not code forks.
- **MNT-002** New connectors can be added without changing the core data model or other connectors.
- **MNT-003** Automated tests for connectors, data transformations, validation and access control.

## 6. Phase plan

| Phase | Scope |
| --- | --- |
| **Phase 1a: Local pilot** | Repo scaffold; Tally connector (multi-company, incremental); import of the client's backup data; canonical data model; validation against Tally; local login and role-based access; reporting views; MIS dashboard, health indicators, core statements, receivables/payables, entity and consolidated views, drill-down; budget planning and analysis (Section 4.12, milestone M7b); natural-language querying (text-to-SQL + RAG), including budgets; audit log. See `docs/roadmap.md`. |
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
| 2026-10-12 | 0.5 | SYN-006: phase 1a alerts go to the log and in-app; email later (M4, ADR-019). |
| 2026-10-16 | 0.20 | Section 4.13 Foreign currency (FX-001 to FX-013): foreign-currency data kept alongside the base-currency books, revaluation snapshots, realised and unrealised gains, exposure, `forex.view` (ADR-037). |
| 2026-10-16 | 0.19 | VAL-013 per ledger; VAL-014: `validate compare-ledger`. |
| 2026-10-16 | 0.18 | VAL-013: foreign-currency ledgers at the source's book value. |
| 2026-10-16 | 0.17 | VAL-010: line attribution, cancelling pairs, unread lists, opening difference by primary group; stock ledgers at the stock value explained as in validation. |
| 2026-10-15 | 0.16 | VAL-012: stock ledgers at the source's stock value; DAT-012: the trial balance's opening difference, effective dates; VAL-010: narrowed dates and single vouchers. |
| 2026-10-15 | 0.15 | VAL-011: reliable dates (Educational mode). |
| 2026-10-15 | 0.14 | VAL-010: ledger profiles test the books' first day, special vouchers, lines around a year end, opening bills and closing stock values; the opening difference is explained. |
| 2026-10-15 | 0.13 | VAL-010: anonymous ledger profiles; DAT-012: stock ledgers with integrated inventory. |
| 2026-10-15 | 0.12 | DAT-012: job work godowns and the source's own opening difference; VAL-010: godown-level stock and job work in the analysis. |
| 2026-10-14 | 0.11 | DAT-012: the source's counting rules (openings at the books' beginning, stock moved once, what counts in the books); VAL-010 extended (pairs, primary groups, first month). |
| 2026-10-14 | 0.10 | OPS-005: readable health report, stable error codes and error catalogue, shared output layout. |
| 2026-10-14 | 0.9 | VAL-010: analysis of validation mismatches (`validate analyse`). |
| 2026-10-13 | 0.8 | DAT-011: rules for resolving references by name, and a diagnostic for those that don't resolve (ADR-027). |
| 2026-10-13 | 0.7 | Budget planning and analysis (Section 4.12): BUD-001 to BUD-016; default budget permissions per role (Section 3); RPT-008 points to budgets; phase 1a includes budgets (milestone M7b). ADR-026. |
| 2026-10-13 | 0.6 | DAT-009 and DAT-010 (custom fields kept and catalogued; values that don't fit never fail other records), VAL-005 to VAL-009 (voucher counts, stock quantities, bill-wise outstanding, year-end balances, root causes). ADR-025. |
