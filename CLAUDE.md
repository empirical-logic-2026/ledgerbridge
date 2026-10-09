# CLAUDE.md

Guidance for Claude Code working in this repository.

## Project summary

A multi-client platform that connects to accounting systems (Tally first, then Zoho, banks, CSV/TXT, upstream systems), stores their data in MySQL, and provides MIS dashboards, reporting and AI-driven natural-language querying.

Read these before any non-trivial task:

- `docs/requirements.md` — what to build. Requirements have IDs (e.g. `CON-002`). Reference them.
- `docs/architecture.md` — how it is built, including the decision log (ADRs).
- `docs/schema.md` — the MySQL design. Schema changes must match it.
- `docs/roadmap.md` — milestone order and the current milestone.

## Current focus: local pilot (Phase 1a)

We are building a local pilot that loads Tally backup data into MySQL and serves dashboards and AI querying. **Build everything generically** (requirements PIL-003): nothing may be specific to particular companies, to backup data, or to Tally outside `data-plane/connectors/tally`. The same code must later work for live Tally, other accounting platforms and other clients. Control plane, agent and packaging are deferred; use `AUTH_MODE=local`.

## The one rule that must never be broken

The provider-hosted **control plane** (`/control-plane`) stores **only** user login credentials, user-to-client mapping and licence data. It must **never** store, log, cache, proxy or receive client accounting data, files, query results, reports, AI prompts or usage analytics. All of that lives in the client-hosted **data plane** (`/data-plane`). If a task seems to require breaking this rule, stop and ask.

## Repository structure

```text
/control-plane   auth, MFA, licences, client registry (FastAPI)
/data-plane/api  reporting, admin, AI endpoints (FastAPI)
/data-plane/core canonical model, validation, permissions
/data-plane/connectors   one package per source
/data-plane/workers      sync, import, validation, scheduled jobs
/data-plane/ai           text-to-SQL, provider abstraction, guardrails
/data-plane/migrations   Alembic migrations
/agent           connector agent for on-prem sources
/frontend        React + TypeScript dashboard
/deploy          Docker and release configuration
/docs            requirements, architecture, schema, decisions
```

## Stack

Python 3.12+, FastAPI, SQLAlchemy 2, Alembic, MySQL 8, Celery + Redis, Qdrant, React + TypeScript + Vite, TanStack Query, Ant Design, Apache ECharts, Docker Compose. Do not introduce new frameworks or major libraries without asking.

## Commands

<!-- Fill in as the project is scaffolded. -->

```bash
# Backend (run in data-plane/)
uv sync
uv run ruff check . && uv run ruff format --check .
uv run python -m pytest                  # unit tests
uv run python -m pytest -m integration   # needs the test stack running
# Use `python -m pytest`, not `pytest`: Windows Application Control blocks .venv\Scripts\*.exe launchers here.
# uv itself is installed in the user's Python, so call it as `python -m uv` if `uv` is not on PATH.

# Frontend (run in frontend/)
npm install
npm run dev
npm run lint
npm test -- --run
npm run build

# Developer commands (PowerShell, repo root; default -Env test; needs .env.test)
./dev.ps1 up                     # build, start, wait healthy, migrate (as migrator), print URLs (API on 8001)
./dev.ps1 status | down | test | logs <service> | tally-companies
./dev.ps1 seed-test-data         # idempotent seed of LedgerBridge Test Co in TallyPrime (ADR-014)
./dev.ps1 extract -Company "LedgerBridge Test Co"

# Lower level: any docker compose command for one environment
./deploy/stack.ps1 -Env test up -d --build
./deploy/stack.ps1 -Env test down

# Database migrations: always as the `migrator` user (schema.md 2.1)
./deploy/stack.ps1 -Env test run --rm migrate          # in the one-off container (dev.ps1 up does this)
uv run python -m alembic upgrade head                   # from data-plane/ on the host; uses MYSQL_MIGRATOR_* from .env.test
uv run python -m alembic check                          # models and migrations must match

# Extraction (run in data-plane/; source-independent CLI)
uv run python -m workers.cli entities --connection tally-test --source tally
uv run python -m workers.cli extract --connection tally-test --entity "LedgerBridge Test Co"

# Tally developer tools (test company only)
uv run python -m connectors.tally.tools capture-fixtures --company "LedgerBridge Test Co"
uv run python -m connectors.tally.tools sign-check --company "LedgerBridge Test Co"
uv run python -m connectors.tally.tools sign-check --fixtures
```

Claude Code only ever uses `-Env test` (with both `dev.ps1` and `deploy/stack.ps1`). Never create `.env.pilot` or run `-Env pilot`.

## Working process

1. For any task larger than a small fix, start in plan mode: read the relevant docs and requirement IDs, propose a plan, and wait for approval before writing code.
2. Work in small, scoped steps. Do not modify areas outside the task.
3. When a requirement or design changes, update `docs/requirements.md` / `docs/architecture.md` first (including the change log or ADR list), then the code.
4. Reference requirement IDs in commit messages and PR descriptions, e.g. `CON-002: Tally ledger sync`.
5. Write or update tests with every change.

## Docker changes (developer is learning Docker)

Whenever a change touches anything Docker-related (Dockerfiles, `.dockerignore`, `deploy/compose.yaml`, volumes, ports, env files, MySQL init scripts, Docker commands in `deploy/stack.ps1` or other scripts):

- Update `docs/learning/docker.md` in the same change, so it keeps explaining the actual setup file by file, with commands to see it working. Add a change log entry.
- End the summary to the developer with a short **"Docker explained"** section: what changed and why, in plain language.

## Coding conventions

- Python: type hints everywhere, Pydantic models for API input/output, `ruff` for linting and formatting.
- TypeScript: strict mode, no `any` without justification, shared API types generated from the backend OpenAPI schema.
- Money: `DECIMAL(20,4)` in MySQL and `Decimal` in Python. Never use floats for amounts.
- Every canonical table row carries `entity_id`, source origin and timestamps.
- Database schema changes only via Alembic migrations, and `docs/schema.md` is updated in the same change. Never edit an applied migration (ADR-016).
- MySQL databases are `ledgerbridge_source`, `ledgerbridge_accounting`, `ledgerbridge_reporting`, `ledgerbridge_system` (ADR-016). Refer to them through `core/models/schemas.py` in code; migrations use literal names.
- Connectors implement the standard connector interface (architecture Section 4.4) and live in their own package.

## Security rules

- Connectors are read-only towards source systems. Never write back to Tally or any source.
  - Only exception (ADR-014): `data-plane/devtools/tally_seed`, run via `./dev.ps1 seed-test-data`, may import into **LedgerBridge Test Co only**, with its guards (`APP_ENV=test`, only that company loaded, exact name match). Product code must never import from `devtools/`.
- Never log secrets, credentials, tokens or accounting data values.
- Connection credentials are stored encrypted; never in code, config committed to git, or logs.
- AI-generated SQL must pass validation (single read-only SELECT on allowed semantic-layer views) and run under the read-only database user, with the user's entity filters enforced in code.
- Authorization is checked in the data plane on every request; never trust client-side checks.
- No telemetry or external calls from the data plane except to configured sources and the client's configured AI provider.

## Client data rules

- Work only with the `test` environment (LedgerBridge Test Co). Never use, read or connect to the `pilot` environment, its database, or any folder containing client Tally data.
- Never ask for, open or print client data. If debugging needs real data, ask the developer for error messages or counts only.
- Test fixtures must be synthetic or taken from the test company.

## When unsure

Ask rather than guess, especially about accounting rules, data ownership, or anything touching the control plane / data plane boundary.


## Git workflow

- Branches: `main` (production, release merges only), `dev` (integration), `feature/<milestone>-<name>` (work).
- Never commit to or push `main` or `dev` directly. Work only on the current feature branch.
- Commit in small logical steps with messages starting with the milestone or requirement ID, e.g. `M1: add Tally company list request`.
- Never commit secrets, `.env` files, client data or generated folders.
- Don't merge, rebase shared branches or force push; the developer handles pull requests and merges.