# Roadmap: Phase 1a Local Pilot

| Field | Value |
| --- | --- |
| Version | 0.5 |
| Date | 2026-10-09 |
| Current milestone | **M3** |

Goal: load the client's Tally backup data (two companies) into MySQL and deliver dashboards and AI querying, with every part built generically so it later works for live Tally, other accounting books and other clients (PIL-001 to PIL-005).

## How to use this with Claude Code

1. Update "Current milestone" above before starting each milestone.
2. Start Claude Code in **plan mode** and paste the milestone prompt.
3. Review the plan, adjust, then approve.
4. Check the "Done when" list yourself, commit with the milestone ID in the message (e.g. `M1: Tally proof of concept`), and move on.
5. If requirements change, update the docs first, then continue.

---

## M0 — Repository scaffold

**Done when:** `docker compose up` starts MySQL, Redis and Qdrant; backend tests run; frontend dev server opens; `.env.test.example` and `.env.pilot.example` exist.

> Read CLAUDE.md and all files in docs/. Plan milestone M0: scaffold the repository structure from architecture.md Section 10. Include Docker Compose for MySQL 8, Redis and Qdrant; Python project setup for data-plane (FastAPI, SQLAlchemy 2, Alembic, Celery, ruff, pytest); a React + TypeScript + Vite frontend skeleton with TanStack Query, Ant Design and ECharts; and environment handling for the `test` and `pilot` environments described in architecture.md Section 13 (example env files only, no secrets). Leave control-plane and agent as empty placeholders with a README. No business logic yet. Show me the plan before writing files.

## M1 — Tally proof of concept

**Done when:** a script lists the companies loaded in TallyPrime and pulls groups, ledgers and vouchers for a chosen company from the test company into `ledgerbridge_source.raw_records`; the debit/credit sign convention is confirmed and documented.

> Plan milestone M1 (Tally proof of concept) per architecture.md Sections 4.4 and 13 and schema.md Sections 3 and 7. Build the start of `data-plane/connectors/tally`: an HTTP client for Tally's XML interface at TALLY_URL, a request to list loaded companies, and requests to fetch groups, ledgers, voucher types and vouchers for a named company, storing results unchanged in ledgerbridge_source.raw_records. Create only the tables this milestone needs via Alembic. Add a CLI command to run it. Write tests using recorded XML fixtures from the test company (I will provide them; never use client data). Include a check that confirms how Tally signs debit and credit amounts. Show me the plan first.

**Your part:** load LedgerBridge Test Co in TallyPrime with the XML server enabled, and save sample XML responses as fixtures when Claude Code asks.

## M2 — Database foundation

**Done when:** Alembic migrations create every phase 1a table from schema.md in the four databases `ledgerbridge_source`, `ledgerbridge_accounting`, `ledgerbridge_reporting` (empty until M6) and `ledgerbridge_system` (ADR-016); the database users from schema.md Section 2.1 exist with their grants (`ai_ro` reads `ledgerbridge_reporting` only); migrations run as `migrator` in a one-off container; standard accounts are seeded.

> Plan milestone M2: implement the full schema from docs/schema.md as SQLAlchemy models and Alembic migrations, including the four databases named in ADR-016, source-tracking columns, indexes, unique keys, database users and grants from Section 2.1, and a seed for a default standard chart of accounts. Follow every convention in schema.md Section 1. Add tests that run migrations on an empty database. Show me the plan first.

## M3 — Tally connector: full and incremental sync

**Done when:** the test company is fully transformed from raw to canonical tables; re-running only fetches changes (AlterID); altered, cancelled and deleted vouchers are handled; several companies can be synced in one run; each run is logged in `ledgerbridge_system.sync_runs`.

> Plan milestone M3: complete the Tally connector per the connector interface in architecture.md Section 4.4 and the mapping in schema.md Section 7. Implement transformation from ledgerbridge_source.raw_records into the ledgerbridge_accounting tables (replacing a voucher's child rows as a whole in one transaction, schema.md Section 8 rule 7), idempotent upserts on (connection_id, source_key), incremental sync with AlterID markers in ledgerbridge_system.sync_markers, soft deletes, multi-company runs, origin tagging (live or backup, configurable per connection), and sync logging. Keep all Tally-specific logic inside connectors/tally; the transform framework must be source-independent. Test with test-company fixtures. Show me the plan first.

## M4 — Validation

**Done when:** after every sync, voucher balance, trial balance and ledger closing-balance checks run; results are stored and viewable via an API endpoint.

> Plan milestone M4: implement validation per requirements VAL-001 to VAL-003 and schema.md Section 5.2. Checks: every voucher's lines sum to zero, trial balance balances per entity and period, and ledger closing balances match the closing balances reported by the source (fetch Tally's closing balances through the connector). Store results in ledgerbridge_system.validation_runs and ledgerbridge_system.validation_issues and expose them via the API. Show me the plan first.

**Your part (outside Claude Code):** run M3 and M4 against the `pilot` environment with the client's two companies. Share only pass/fail results and error messages, never figures or names.

## M5 — Local login and access control

**Done when:** users can log in locally; roles, entity access and permissions are enforced on every API endpoint; audit log records logins and data access.

> Plan milestone M5: implement AUTH_MODE=local per architecture.md Section 13 and ADR-010, with token verification behind an interface so control-plane tokens can replace it later. Implement roles, permissions, user_entity_access and audit logging per schema.md Sections 5.3 and 5.4, enforced in the data plane on every endpoint (requirements ACC-001, ACC-002, ACC-004, AUD-001). Show me the plan first.

## M6 — Reporting layer

**Done when:** the `ledgerbridge_reporting` views and aggregate tables from schema.md Section 6 exist and refresh after sync; API endpoints serve trial balance, P&L, balance sheet, cash flow, receivables and payables ageing, KPIs, per entity and consolidated, with drill-down to vouchers; and the API serves everything the dashboard home page needs (docs/design/dashboard.md Section 4):
- a business health score (0 to 100 with a label) from a formula documented in docs/schema.md and approved before it is built
- cash cover in months, with its definition documented
- simple rule-based alerts with severity, message and suggested action, with configurable rules and thresholds
- a recent-events feed for the LIVE ticker (new vouchers, payments, bank balance and GST payable changes, data-check results), written after each sync

> Plan milestone M6: implement the ledgerbridge_reporting database objects from docs/schema.md Section 6, incremental refresh of aggregate tables after each sync, the semantic_catalog with descriptions of every view and column, and API endpoints for requirements RPT-001 to RPT-004 and RPT-006 to RPT-008, all respecting the user's entity access. Also provide the data for the dashboard home page in docs/design/dashboard.md Section 4: propose a business health score formula (components, weights, label bands) and a cash-cover definition for my approval and document them in docs/schema.md; rule-based alerts with severity, message and suggested action; a recent-events feed written after each sync for the LIVE ticker; and the last-sync status per connection. Update docs/schema.md for any new tables or views in the same change. Show me the plan first.

## M7 — Dashboard

**Done when:** the React app supports login, entity and consolidated selection, period filters, MIS overview with health indicators, all statements from M6, ageing, drill-down to voucher detail, and a data-quality page; and the home page matches the approved design in docs/design/dashboard.md and dashboard-mockup.png in layout, wording and visual style (top bar with company and period switchers and sync status, LIVE ticker, plain-language sidebar, greeting, five KPI cards, sales vs expenses chart, "Needs your attention" panel, "Ask a question" panel), with real data from the M6 API in place of the sample figures.

> Read docs/requirements.md Section 4.8, docs/design/dashboard.md with docs/design/dashboard-mockup.png, and the M6 API. Plan milestone M7: build the React dashboard with login, an entity/consolidated switcher, period and dimension filters, an MIS overview with KPI cards flagged good/bad, pages for trial balance, P&L, balance sheet, cash flow, receivables and payables ageing, drill-down from any figure to vouchers, and a data-quality page from M4. The home page must match the approved design element by element: layout, the exact wording, colours as Ant Design theme tokens, Indian number format (L / Cr), and the suggested question chips as listed in dashboard.md (no forecast chip until forecasting exists). Settle the open points in dashboard.md Section 6 in the plan. Use Ant Design and ECharts, TanStack Query, and generated API types. Show me the plan first.

## M8 — AI querying (text-to-SQL + RAG)

**Done when:**
- users ask questions in plain language and get correct answers with the SQL shown
- the guardrails from architecture.md Section 5.2 are enforced
- all three privacy modes work, and `private` is the default:
  - `private` sends nothing outside the deployment
  - `schema-only` sends only the masked question and semantic-layer descriptions, with results formatted locally
  - `full` masks everything it sends
- masking and pseudonymization are reversed locally before the user sees the answer
- embeddings are computed locally
- the model has no outbound tools
- the outbound allowlist blocks everything except configured sources and the one approved AI endpoint
- every model call is logged with its exact payload
- the pilot runs in `private` mode with Ollama

> Plan milestone M8 per architecture.md Section 5 (including 5.4 to 5.7) and ADR-015, and requirements AI-001 to AI-004, AI-010 to AI-018 and SEC-010 (AI-005 and AI-006 are withdrawn). Build:
> - **AI privacy mode** as a per-client setting in the data plane (`private` default, `schema-only`, `full`), changeable only by a Client Admin and audited.
> - **Provider abstraction**: Ollama as the local model; Anthropic API for the test environment only, on synthetic data; Bedrock and Vertex interfaces for client cloud accounts, where configured. Each provider is allowed only in its permitted modes.
> - **Local embedding model**: embed ledgerbridge_reporting.semantic_catalog, business definitions and ledger names into Qdrant.
> - **One data protection gate** that every model payload goes through:
>   - mode checks; in `schema-only` the external request type cannot carry result rows or sample values
>   - pseudonymization of party names (matched against the party master), GSTIN, PAN, bank account numbers and salary amounts, with a token map kept only in memory, never sent or logged
>   - local reversal of tokens in responses
> - **The text-to-SQL pipeline**:
>   - SQL generation restricted to ledgerbridge_reporting views
>   - SQL validation
>   - execution as the ai_ro user with entity filters injected in code, plus timeouts and row limits
>   - result formatting by local templates or the local model in `private` and `schema-only`
>   - answers that show the SQL and link to source records
> - **No outbound tools for the model**: the only capability is proposing SQL; model output is treated as untrusted text.
> - **Outbound network allowlist**, derived from configuration: Docker egress restricted to configured sources plus the one approved AI endpoint, and an application-level check in a single HTTP client factory. Refusals are logged.
> - **Model call log**: one append-only row per model call with the exact payload sent (after masking), the response, provider, endpoint, model, mode, user and token counts, plus ledgerbridge_system.ai_query_log per question. Design the table and update docs/schema.md in the same change.
> - **Dashboard**: a chat panel, and an admin view of the model call log.
>
> **Tests:**
> - an evaluation set of 20 questions with expected answers from the test company, run in every mode
> - leak tests asserting that no result rows, figures or unmasked names, GSTINs, PANs, bank account numbers or salaries reach an external request in `schema-only` and `full`
> - a test that egress outside the allowlist is blocked
>
> Show me the plan first.

## M9 — Pilot run on client data (developer only)

**Done when:** both client companies are loaded in the `pilot` environment, validation passes against Tally, dashboards show both companies and the consolidated view, and AI querying works with the local model.

This milestone is run by the developer, not Claude Code. Fix any problems by describing errors to Claude Code without sharing client data.

---

## After the pilot (Phase 1b)

Control plane with login and licences; CSV/TXT connector; connector agent; client deployment packaging and signed releases; then Phase 2 features from requirements.md Section 6.

## Change log

| Date | Version | Change |
| --- | --- | --- |
| 2026-10-08 | 0.1 | Initial pilot roadmap. |
| 2026-10-09 | 0.2 | M8 "Done when" and prompt updated for AI data protection: privacy modes, masking, local embeddings, no outbound tools, egress allowlist, model call log (AI-011 to AI-018, SEC-010, ADR-015). |
| 2026-10-09 | 0.3 | Current milestone M2. Database names `ledgerbridge_source`, `ledgerbridge_accounting`, `ledgerbridge_reporting`, `ledgerbridge_system` (ADR-016) in M2 to M8; M2 "Done when" adds users, grants and the `migrate` container; M3 prompt references the child-row replacement rule. |
| 2026-10-12 | 0.4 | Current milestone M3. |
| 2026-10-12 | 0.5 | Approved dashboard home page design (docs/design/dashboard.md, dashboard-mockup.png). M6 adds the home page data: business health score formula, cash cover in months, rule-based alerts, recent-events feed. M7 "Done when" and prompt require matching the design; forecast question chip deferred until forecasting (AI-009, phase 3). |
