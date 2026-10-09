# Roadmap: Phase 1a Local Pilot

| Field | Value |
| --- | --- |
| Version | 0.2 |
| Date | 2026-10-09 |
| Current milestone | **M0** |

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

**Done when:** a script lists the companies loaded in TallyPrime and pulls groups, ledgers and vouchers for a chosen company from the test company into `raw.raw_records`; the debit/credit sign convention is confirmed and documented.

> Plan milestone M1 (Tally proof of concept) per architecture.md Sections 4.4 and 13 and schema.md Sections 3 and 7. Build the start of `data-plane/connectors/tally`: an HTTP client for Tally's XML interface at TALLY_URL, a request to list loaded companies, and requests to fetch groups, ledgers, voucher types and vouchers for a named company, storing results unchanged in raw.raw_records. Create only the tables this milestone needs via Alembic. Add a CLI command to run it. Write tests using recorded XML fixtures from the test company (I will provide them; never use client data). Include a check that confirms how Tally signs debit and credit amounts. Show me the plan first.

**Your part:** load LedgerBridge Test Co in TallyPrime with the XML server enabled, and save sample XML responses as fixtures when Claude Code asks.

## M2 — Database foundation

**Done when:** Alembic migrations create the `raw`, `core`, `rpt` and `app` schemas and all phase 1a tables from schema.md; database users from schema.md Section 2.1 are created; standard accounts are seeded.

> Plan milestone M2: implement the full schema from docs/schema.md as SQLAlchemy models and Alembic migrations, including the four schemas, source-tracking columns, indexes, unique keys, database users and grants from Section 2.1, and a seed for a default standard chart of accounts. Follow every convention in schema.md Section 1. Add tests that run migrations on an empty database. Show me the plan first.

## M3 — Tally connector: full and incremental sync

**Done when:** the test company is fully transformed from raw to canonical tables; re-running only fetches changes (AlterID); altered, cancelled and deleted vouchers are handled; several companies can be synced in one run; each run is logged in `app.sync_runs`.

> Plan milestone M3: complete the Tally connector per the connector interface in architecture.md Section 4.4 and the mapping in schema.md Section 7. Implement transformation from raw.raw_records into the core tables, idempotent upserts on (connection_id, source_key), incremental sync with AlterID markers in app.sync_markers, soft deletes, multi-company runs, origin tagging (live or backup, configurable per connection), and sync logging. Keep all Tally-specific logic inside connectors/tally; the transform framework must be source-independent. Test with test-company fixtures. Show me the plan first.

## M4 — Validation

**Done when:** after every sync, voucher balance, trial balance and ledger closing-balance checks run; results are stored and viewable via an API endpoint.

> Plan milestone M4: implement validation per requirements VAL-001 to VAL-003 and schema.md Section 5.2. Checks: every voucher's lines sum to zero, trial balance balances per entity and period, and ledger closing balances match the closing balances reported by the source (fetch Tally's closing balances through the connector). Store results in app.validation_runs and app.validation_issues and expose them via the API. Show me the plan first.

**Your part (outside Claude Code):** run M3 and M4 against the `pilot` environment with the client's two companies. Share only pass/fail results and error messages, never figures or names.

## M5 — Local login and access control

**Done when:** users can log in locally; roles, entity access and permissions are enforced on every API endpoint; audit log records logins and data access.

> Plan milestone M5: implement AUTH_MODE=local per architecture.md Section 13 and ADR-010, with token verification behind an interface so control-plane tokens can replace it later. Implement roles, permissions, user_entity_access and audit logging per schema.md Sections 5.3 and 5.4, enforced in the data plane on every endpoint (requirements ACC-001, ACC-002, ACC-004, AUD-001). Show me the plan first.

## M6 — Reporting layer

**Done when:** the `rpt` views and aggregate tables from schema.md Section 6 exist and refresh after sync; API endpoints serve trial balance, P&L, balance sheet, cash flow, receivables and payables ageing, KPIs, per entity and consolidated, with drill-down to vouchers.

> Plan milestone M6: implement the rpt schema from docs/schema.md Section 6, incremental refresh of aggregate tables after each sync, the semantic_catalog with descriptions of every view and column, and API endpoints for requirements RPT-001 to RPT-004 and RPT-006 to RPT-008, all respecting the user's entity access. Show me the plan first.

## M7 — Dashboard

**Done when:** the React app supports login, entity and consolidated selection, period filters, MIS overview with health indicators, all statements from M6, ageing, drill-down to voucher detail, and a data-quality page.

> Read docs/requirements.md Section 4.8 and the M6 API. Plan milestone M7: build the React dashboard with login, an entity/consolidated switcher, period and dimension filters, an MIS overview with KPI cards flagged good/bad, pages for trial balance, P&L, balance sheet, cash flow, receivables and payables ageing, drill-down from any figure to vouchers, and a data-quality page from M4. Use Ant Design and ECharts, TanStack Query, and generated API types. Show me the plan first.

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
> - **Local embedding model**: embed rpt.semantic_catalog, business definitions and ledger names into Qdrant.
> - **One data protection gate** that every model payload goes through:
>   - mode checks; in `schema-only` the external request type cannot carry result rows or sample values
>   - pseudonymization of party names (matched against the party master), GSTIN, PAN, bank account numbers and salary amounts, with a token map kept only in memory, never sent or logged
>   - local reversal of tokens in responses
> - **The text-to-SQL pipeline**:
>   - SQL generation restricted to rpt views
>   - SQL validation
>   - execution as the ai_ro user with entity filters injected in code, plus timeouts and row limits
>   - result formatting by local templates or the local model in `private` and `schema-only`
>   - answers that show the SQL and link to source records
> - **No outbound tools for the model**: the only capability is proposing SQL; model output is treated as untrusted text.
> - **Outbound network allowlist**, derived from configuration: Docker egress restricted to configured sources plus the one approved AI endpoint, and an application-level check in a single HTTP client factory. Refusals are logged.
> - **Model call log**: one append-only row per model call with the exact payload sent (after masking), the response, provider, endpoint, model, mode, user and token counts, plus app.ai_query_log per question. Design the table and update docs/schema.md in the same change.
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
