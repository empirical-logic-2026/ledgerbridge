# Codebase guide

| Field | Value |
| --- | --- |
| Version | 0.3 |
| Date | 2026-10-13 |
| For | Anyone who wants to find their way around the repository without being a developer |
| Related | [requirements.md](requirements.md) (what to build), [architecture.md](architecture.md) (how it is built, with the decision log), [schema.md](schema.md) (the database), [roadmap.md](roadmap.md) (milestones), [learning/docker.md](learning/docker.md) (the Docker setup), [pilot-runbook.md](pilot-runbook.md) (running the pilot) |

This guide explains what is where and what each part is for. It doesn't repeat the design: for *why* things are built the way they are, follow the links to the documents above. Section 5 explains the technical words.

---

## 1. Overview

LedgerBridge reads a company's accounting data from its accounting software (Tally first), keeps it in a MySQL database run by the client, checks that it matches the books exactly, and will show it in dashboards and answer questions about it in plain language. The repository has these main parts:

- **`data-plane/`** is the heart of the project, and everything built so far lives here. It runs on the client's side and holds all of the client's data. It contains:
  - the **connectors**, which read from sources such as Tally;
  - the **workers**, which fetch, transform and check data, on demand or on a schedule;
  - the **core**, with the database tables, the transform and the validation checks;
  - the **API**, which the dashboard will call;
  - the **migrations**, which create and change the database tables.
- **`frontend/`** is the dashboard that people will use in the browser (React). So far it is a small starting page; the real pages come in milestone M7 ([roadmap.md](roadmap.md)).
- **`control-plane/`** will be the service the provider hosts for logins and licences. It must never see client data. For now it is only a README: it comes after the pilot.
- **`agent/`** will be a small program installed next to Tally at a client's office, sending changes to the data plane. Also only a README for now; during the pilot the data plane talks to Tally directly.
- **`deploy/`** holds what runs the system in Docker: the list of containers, the database's first-start script, and helper scripts. [learning/docker.md](learning/docker.md) explains it in detail.
- **`docs/`** holds the project's documents: requirements, architecture, database design, roadmap, dashboard design, the pilot runbook, the Docker guide and this guide.
- **Scripts:** there is no separate scripts folder. The everyday commands are in **`dev.ps1`** at the top of the repository (a PowerShell script); the lower-level Docker scripts are in `deploy/`.

**How they fit together.** A developer types a command such as `./dev.ps1 sync full`. `dev.ps1` asks Docker to run the matching Python command inside the **api** container. That command uses a **connector** to read from Tally, stores what it receives in the database **unchanged** (the raw layer), then **transforms** it into standard accounting tables, then **validates** the result against Tally's own figures. A separate **worker** container does the same on a schedule. Later, the **API** serves the results to the **dashboard**, and the AI answers questions from a read-only reporting layer of the database. The four MySQL databases and why they are separate are described in [schema.md](schema.md) Section 2 and [architecture.md](architecture.md) Section 4.2.

**In pictures** ([diagrams/README.md](diagrams/README.md) explains each one and has the rest: the ER diagrams per area and the planned budget tables). Click an image to open it at full size.

LedgerBridge and the outside world (dashed = planned):

[![Data flow level 0](diagrams/dataflow-context.png)](diagrams/dataflow-context.svg)

Inside the data plane:

[![Data flow level 1](diagrams/dataflow-level1.png)](diagrams/dataflow-level1.svg)

The four databases and who may read them:

[![Databases and users](diagrams/schema-databases.png)](diagrams/schema-databases.svg)

The main tables:

[![ER overview](diagrams/er-overview.png)](diagrams/er-overview.svg)

## 2. Folder by folder

### 2.1 The tree

Generated and third-party folders (`.venv`, `node_modules`, `dist`, `__pycache__`, `.pytest_cache`, `.ruff_cache`) are left out.

```text
ledgerbridge/
├── CLAUDE.md, README.md, dev.ps1
├── .env.test.example, .env.pilot.example, .gitignore, .gitattributes
├── agent/                      README only (Phase 1b)
├── control-plane/              README only (Phase 1b)
├── data-plane/
│   ├── Dockerfile, .dockerignore, pyproject.toml, uv.lock, .python-version, alembic.ini
│   ├── ai/                     placeholder for the AI layer (M8)
│   ├── api/                    the web API
│   ├── connectors/
│   │   ├── base.py, registry.py
│   │   └── tally/              everything that knows about Tally
│   ├── core/
│   │   └── models/             the database tables, as Python classes
│   ├── devtools/               developer tools, never in the product
│   │   ├── diagrams.py         generates the diagrams from the models
│   │   ├── error_catalogue.py  generates docs/error-catalogue.md from the problem registry
│   │   └── tally_seed/         fills the test company in TallyPrime (test only)
│   ├── migrations/
│   │   └── versions/           one file per database change, 0001 to 0016
│   ├── tests/
│   │   ├── connectors/tally/   tests of the Tally connector
│   │   ├── devtools/           tests of the seeder and the diagrams
│   │   └── fixtures/tally/     recorded Tally answers from the test company
│   └── workers/                the commands and background jobs
├── deploy/
│   ├── compose.yaml, stack.ps1, new-env.ps1
│   └── mysql/init/             the database's first-start script
├── docs/
│   ├── error-catalogue.md      every error and warning code (generated)
│   ├── design/                 dashboard design and mockup
│   ├── diagrams/               ER, database and data flow diagrams (source and images)
│   └── learning/               the Docker guide
├── reports/                    saved health reports, per environment (git-ignored)
└── frontend/
    ├── index.html, package.json, vite.config.ts, tsconfig*.json, .oxlintrc.json
    ├── public/
    └── src/
        ├── api/
        └── components/
```

### 2.2 Top level

| File | What it is and what it's for |
| --- | --- |
| `README.md` | The front page of the project: what it is, how to start it, and a table of everyday `dev.ps1` commands. |
| `CLAUDE.md` | Instructions for Claude Code (the AI assistant that writes much of the code): project rules, commands, security and client-data rules, the git workflow. Also a good summary of the rules for people. |
| `dev.ps1` | The everyday command script (PowerShell): `up`, `down`, `status`, `sync`, `validate`, `transform`, `summary`, `test` and more. Each command either runs Docker through `deploy/stack.ps1` or a Python command inside a container. Run `./dev.ps1 help` for the list. |
| `.env.test.example`, `.env.pilot.example` | Templates for the settings of each environment (database users and ports, Tally address, timeouts). The real files, `.env.test` and `.env.pilot`, hold passwords and are never committed. |
| `.gitignore` | Which files git must never track (env files, generated folders). |
| `.gitattributes` | Keeps shell scripts with Linux line endings, because they run inside Linux containers. |

### 2.3 `data-plane/`: the client-side system

**Project files**

| File | What it is and what it's for |
| --- | --- |
| `Dockerfile` | The recipe for the container image that runs the API, the worker and the migrations. |
| `.dockerignore` | What stays out of that image (for example `devtools/` and the tests). |
| `pyproject.toml`, `uv.lock`, `.python-version` | The Python version, the libraries the project uses (exact versions in `uv.lock`), and the settings for the code checker (ruff) and the test runner (pytest). |
| `alembic.ini` | Settings for Alembic, the tool that runs the database migrations. |

**`api/`: the web API** (FastAPI). The dashboard and other programs will call it over HTTP.

| File | What it is and what it's for |
| --- | --- |
| `main.py` | Creates the API application and plugs in its parts. |
| `health.py` | `/health` and `/health/ready`: is the API up, and can it reach MySQL, Redis and Qdrant? `dev.ps1 up` and `status` use it. |
| `validation.py` | Endpoints that return validation results and alerts. |
| `deps.py` | Shared helpers, e.g. a database session per request. |

**`ai/`**: an empty package that will hold the AI layer (text-to-SQL, model providers, guardrails) in milestone M8 ([architecture.md](architecture.md) Section 5).

**`connectors/`: reading from sources.** Each source gets its own package; everything specific to Tally stays inside `connectors/tally/`.

| File | What it is and what it's for |
| --- | --- |
| `base.py` | The **standard connector interface** every source must offer (list companies, fetch masters and transactions, map to the standard model, and optional extras such as closing balances), plus the shared data types. |
| `registry.py` | The list of available sources ("tally" → the Tally connector), so a new source can be added without touching the others. |
| `tally/client.py` | Sends requests to Tally over HTTP and decodes its answers (UTF-8 or UTF-16). Knows about timeouts and retries. |
| `tally/envelopes.py` | Builds the XML requests Tally understands (which objects, which fields, which dates). **Export requests only**: the platform never writes to Tally. |
| `tally/parser.py` | Reads Tally's XML answers into individual objects (one voucher, one ledger), cleans characters Tally sends that aren't valid XML, and handles custom fields with prefixes such as `UDF:`. |
| `tally/connector.py` | The Tally connector itself: puts client, requests and parser together to implement the interface in `base.py` (list companies, fetch month by month, list keys, closing balances, voucher counts, stock, bills). |
| `tally/mapping.py` | Turns one Tally object into the standard accounting record: groups, ledgers, voucher types, vouchers and their lines, with Tally's signs and reserved names. All Tally knowledge about meaning lives here. |
| `tally/signs.py` | Rules for reading debit and credit from Tally's XML, and a check that confirms them on real data. |
| `tally/fixtures.py` | Plays back recorded Tally answers in tests, so tests run without Tally. |
| `tally/tools.py` | Developer tools for the test company only: record fixtures, run the sign check. |

**`core/`: the source-independent heart.** Nothing here knows about Tally.

| File | What it is and what it's for |
| --- | --- |
| `config.py` | All settings (database users, ports, Tally address, timeouts, tolerances), read from the environment's `.env` file. |
| `db.py` | Opens database connections, one kind per database user (app, migrator, report, AI), each with only the rights it needs. |
| `models/` | The database tables as Python classes, one file per database: `source.py` (raw layer), `accounting.py` (the standard accounting model), `system.py` (connections, sync runs, validation, users, alerts, settings); `base.py` (shared column types and the source-tracking columns); `schemas.py` (the four database names). The tables are described for people in [schema.md](schema.md). |
| `canonical.py` | The standard ("canonical") records every connector produces: company, group, ledger, voucher, voucher line and so on. |
| `raw_store.py` | Stores what a source sends, unchanged, in the raw records table, skipping copies that haven't changed. |
| `transform.py` | Turns raw records into the accounting tables: in batches, in the right order (groups before ledgers before vouchers), updating rather than duplicating, replacing a voucher's lines as a whole, and failing only the record at fault. |
| `fit.py` | Checks every value against its column before writing; a value that doesn't fit is kept in full in the row's `extra` field and reported, never cut short. |
| `names.py` | The rules for finding what a name refers to (exact name, alias, then a normalised comparison), used by the transform. |
| `naming.py` | Describes how two names differ without showing them (used by the company check `entity-check`). |
| `validation.py` | The checks: every voucher balances, the trial balance balances, every ledger matches Tally's closing balance, plus voucher counts, stock quantities, bills and year-end balances; and the "root cause" explanation. |
| `alerts.py` | Raises and resolves alerts when syncs or checks fail. |
| `errors.py` | Writes errors briefly and safely, never with SQL statements or values from the books. |
| `dates.py` | Which dates a source answers reliably (Tally's Educational mode: the 1st, 2nd and 31st), and how validation moves its dates to them. |
| `problems.py` | Every error and warning the system reports, with its plain name, stable code (LB-SYNC, LB-TRF, LB-VAL, LB-CON, LB-SYS), meaning, causes, how to investigate and fix it, and the next command. All output and the error catalogue come from it. |

**`workers/`: commands and background jobs.**

| File | What it is and what it's for |
| --- | --- |
| `cli.py` | The command line behind almost every `dev.ps1` command (`python -m workers.cli ...`): `connect`, `sync`, `validate`, `status`, `summary`, `watch`, `abandon`, `transform-retry`/`-rebuild`/`-explain`, `fields`, `promote-field` and more. It also decides what may be printed: outside the test environment, no names or amounts. |
| `sync.py` | Runs a sync: company by company, fetch, store, transform, then hand over to validation; records each run. Also the deletion check and the transform-only runs (retry, rebuild). |
| `fetch.py` | Fetches one company piece by piece ("chunks", usually a month of vouchers), saves progress so an interrupted sync can resume, and copes with a slow or busy Tally. |
| `extract.py` | Finding or creating a connection, and the older "raw records only" extraction. |
| `entities.py` | Which companies a connection works with (found by their key, not their name), and the shared way to name them in output: `entity <id> (company <n>)`. |
| `validate.py` | Runs validation after syncs and on demand, gathers Tally's own figures through the connector, and raises alerts. |
| `celery_app.py` | The scheduled worker: every minute it checks which connections are due for a sync or a deletion check and starts them. |
| `locks.py` | The connection's run lock (Redis): taken when a run opens, renewed by its heartbeat, released when it ends, cleared when orphaned, so it can't outlive its job. |
| `runs.py` | Keeps track of running syncs (heartbeats), marks interrupted ones, and stores the output of background jobs so `sync watch` can follow them. |
| `failures.py` | Groups the reasons records failed, for `summary`, without values. |
| `fields.py` | The catalogue of extra fields (e.g. Tally custom fields) and turning one into a reporting dimension. |
| `references.py` | The `transform explain` diagnostic: why names didn't resolve, in counts and kinds only. |
| `report.py` | The health report (`./dev.ps1 report`): overall verdict, sections, problems with meaning, likely cause and next step; and the validation layout every command shares, compared with the previous run. Counts and codes only. |
| `style.py` | Colours status words (green, yellow, red) when `dev.ps1` says the terminal supports it; plain text otherwise. |
| `compare.py` | `validate compare-ledger`: one ledger's vouchers in the source against ours, voucher by voucher; counts printed, details only as private lines for a local file. |
| `analyse.py` | The `validate analyse` diagnostic: tests explanations for every validation mismatch (ledgers, year ends, profit carrier, unbalanced vouchers, trial balance, bills, stock) and counts which fit. |

**`migrations/`: database changes.**

| File | What it is and what it's for |
| --- | --- |
| `env.py`, `script.py.mako` | Alembic's setup and the template for new migration files. |
| `versions/0001_...py` to `versions/0012_...py` | One file per change to the database, applied in order: 0001 raw records and sync runs, 0002 the accounting and system tables, 0003 the standard chart of accounts, then later additions (tax types, deletion checks, validation dates and alerts, sync checkpoints, unverified ranges, run liveness and job logs, the `extra` fields and field catalogue, voucher types' standard type and whether they move stock). An applied migration is never edited; a change is always a new file. [schema.md](schema.md) Section 3 lists them. |

**`devtools/error_catalogue.py`: the error catalogue.** Writes `docs/error-catalogue.md` from `core/problems.py`, so the documented codes always match what the commands print (also run by `./dev.ps1 diagrams`; a test fails when it is stale). Development only.

**`devtools/diagrams.py`: the diagrams.** Writes the Mermaid sources of the ER diagrams and the database diagram in `docs/diagrams/` from the database models, so they always match the code (`./dev.ps1 diagrams`, which also draws the images). Development only.

**`devtools/tally_seed/`: filling the test company.** Development only, never part of the product, and it may only write to the company "LedgerBridge Test Co" (it checks this before doing anything). `data.py` holds the synthetic ledgers and vouchers, including the cases that reproduce Tally's counting rules (openings, delivery and receipt notes with tracked invoices, optional, memorandum, reversing and post-dated vouchers; schema.md 7.5); `requests.py` builds Tally's import requests; `seed.py` works out what is missing and imports it; `__main__.py` is the command (`./dev.ps1 seed-test-data`).

**`tests/`: automatic checks.**

| Files | What they cover |
| --- | --- |
| `conftest.py` | Shared test setup: an in-memory database standing in for MySQL, the recorded Tally answers, the test company's name. |
| `sim_tally.py` | A simulated Tally for tests: large companies, slow months, timeouts, custom fields, values that don't fit, names written differently. |
| `fixtures/tally/` | Real answers recorded from the test company (`*.xml`) and `manifest.json`, which says which request each file answers. Test company data only. |
| `fixtures/tally/rules/` | Answers recorded from the test company that prove Tally's counting rules: ledger and stock item openings fetched for different periods, and tracked notes and invoices. |
| `test_counting_rules.py` | Tally's counting rules (schema.md 7.5): openings fetched at the books' beginning, stock moved once for tracked invoices, and the seed matching Tally's own figures. |
| `test_dates.py` | Reliable dates in Educational mode: validation as of the latest reliable date, year and month ends moved forward, detection and the connection setting. |
| `test_compare_ledger.py` | `validate compare-ledger`: matching, counts without numbers or amounts, private lines only with `--private`. |
| `test_forex.py` | Foreign-currency ledgers at Tally's book value (its trial balance's Unadjusted Forex Gain/Loss), foreign amounts on lines; on responses recorded from the test company. |
| `test_line_attribution.py` | Which ledger a voucher line belongs to: names as Tally compares them, deleted ledgers with a live twin, ledger lines in lists not read; on fixtures recorded from the test company. |
| `test_stock_ledger_and_dates.py` | Stock ledgers at the source's stock value, Tally's own group totals (stock value, opening difference) and effective dates; on fixtures recorded from the test company. |
| `test_job_work.py` | Job work and godowns as Tally counts them, stock journals read once, Tally's own opening difference; on fixtures recorded from the test company. |
| `test_dev_script_args.py`, `test_run_lock.py` | The docker compose arguments each `dev.ps1` command builds (with a stand-in for `deploy/stack.ps1`); the run lock: released however a run ends, lapsing after a shutdown, cleared when orphaned, refusals that say what they found. |
| `connectors/tally/test_*.py` | The Tally connector: requests, parser, mapping, signs, recorded fixtures. |
| `devtools/test_tally_seed.py`, `devtools/test_diagrams.py` | The seeder and its safety checks; that the diagrams match the models and are drawn. |
| `test_sync.py`, `test_large_sync.py`, `test_extract.py`, `test_raw_store.py`, `test_entity_lookup.py` | Syncing: small and large, resuming, finding companies, storing raw records. |
| `test_validation.py`, `test_standard_accounts.py` | Validation checks and the standard chart of accounts. |
| `test_retransform.py`, `test_references.py`, `test_pilot_robustness.py` | Problems found during the pilot: transform retry and rebuild, safe error messages, values that don't fit, names that differ, custom fields, background jobs and interrupted runs. |
| `test_cli.py`, `test_celery.py`, `test_config.py`, `test_errors.py`, `test_health.py`, `test_naming.py` | The command line (including that pilot output holds no names), the scheduler, settings, error messages, the health endpoints, name comparisons. |
| `test_scripts.py`, `test_text_files.py` | `dev.ps1` and the other scripts, and that every text file is free of invisible characters. |
| `*_integration.py` | Tests that need the test database running (`./dev.ps1 test` runs them): migrations, database users and rights, syncing into MySQL, locks, readiness, the `dev.ps1` safety prompts. |

### 2.4 `deploy/`: running it in Docker

| File | What it is and what it's for |
| --- | --- |
| `compose.yaml` | The list of containers and how they connect: **mysql** (the database), **redis** (the worker's message queue), **qdrant** (the vector store for the AI, M8), **api**, **worker** (the scheduled jobs), and **migrate** (a one-off container that applies database migrations). |
| `stack.ps1` | Runs `docker compose` for one environment (test or pilot), each with its own project name, settings file and data volumes. `dev.ps1` goes through it. |
| `new-env.ps1` | Creates an environment's `.env` file with strong random passwords (`./dev.ps1 init-env`). |
| `mysql/init/01-schemas.sh` | Runs once, when the database starts for the first time: creates the four databases and the database users with their rights. |

The Docker guide, [learning/docker.md](learning/docker.md), explains each of these file by file.

### 2.5 `docs/`: the documents

| File | What it is |
| --- | --- |
| [requirements.md](requirements.md) | What the platform must do, with requirement IDs (e.g. `CON-002`, `VAL-005`, `BUD-001`). |
| [architecture.md](architecture.md) | How it is built, and the decision log (ADR-001 onwards: why each important choice was made). |
| [schema.md](schema.md) | The database design: every table, the Tally mapping, the processing rules, the migrations. |
| [roadmap.md](roadmap.md) | The milestones (M0 to M9, plus M7b), each with "done when" and the prompt that starts it. |
| [error-catalogue.md](error-catalogue.md) | Every error and warning code: what it means, common causes, how to investigate, how to fix (generated from `core/problems.py`). |
| [pilot-runbook.md](pilot-runbook.md) | Step by step for running the pilot on client data (the developer runs it, never Claude Code), and how to read the output. |
| [design/dashboard.md](design/dashboard.md), `design/dashboard-mockup.png` | The dashboard design: the approved home page and the proposed Budget page. |
| [learning/docker.md](learning/docker.md) | Docker explained for this project, file by file. |
| [diagrams/README.md](diagrams/README.md), `diagrams/*.mmd`, `*.svg`, `*.png` | The diagrams: ER diagrams (generated from the models), the databases and users, the data flow, the planned budget tables; each as Mermaid source and as images. |
| `diagrams/mermaid-config.json` | How the images are drawn. |
| `codebase-guide.md` | This guide. |

### 2.6 `frontend/`: the dashboard

| File | What it is and what it's for |
| --- | --- |
| `package.json`, `package-lock.json` | The JavaScript libraries (React, Ant Design, ECharts, TanStack Query) and the commands `npm run dev`, `lint`, `test`, `build`. |
| `index.html`, `public/favicon.svg` | The page that loads the app, and its icon. |
| `src/main.tsx`, `src/App.tsx` | Start the app; `App.tsx` is the current starting page: the API's health and a sample chart. |
| `src/api/client.ts` | How the dashboard calls the API. |
| `src/components/EChart.tsx` | A reusable chart component. |
| `src/index.css`, `src/test-setup.ts`, `src/App.test.tsx` | Styles, and the dashboard's test setup and test. |
| `vite.config.ts`, `tsconfig*.json`, `.oxlintrc.json`, `.env.example`, `.gitignore` | Build, TypeScript and code-check settings, and the API address setting. |

### 2.7 `control-plane/` and `agent/`

Each holds only a `README.md` describing what will be built after the pilot (Phase 1b): the provider's login and licence service, and the agent next to Tally.

## 3. How the main flows move through the code

### (a) Sync: from Tally into raw records

1. `workers/cli.py` (command `sync`) finds the connection and creates the Tally connector through `connectors/registry.py`.
2. `workers/sync.py` (`run_sync`) opens a run in `sync_runs`, works out which companies to sync (`workers/entities.py`), and handles them one by one.
3. `workers/fetch.py` (`ChunkFetcher`) asks the connector for a plan (the company record, each kind of master, then vouchers month by month) and fetches each piece, saving a checkpoint after each so an interrupted sync can resume. It splits or retries slow pieces and checks whether Tally is still answering.
4. `connectors/tally/connector.py` builds each request with `connectors/tally/envelopes.py`, sends it with `connectors/tally/client.py`, and reads the answer with `connectors/tally/parser.py`.
5. `core/raw_store.py` stores each object unchanged in `ledgerbridge_source.raw_records` (table defined in `core/models/source.py`), skipping copies that haven't changed.

### (b) Transform: raw records into the accounting tables

1. Still inside the sync (`workers/sync.py`), or on its own with `transform retry` / `rebuild` (`run_transform`), `core/transform.py` (`Transformer`) reads the waiting raw records in batches, object type by object type.
2. For each record the connector's mapping, `connectors/tally/mapping.py`, produces standard records (`core/canonical.py`).
3. The transform finds what names refer to (`core/names.py`), fits every value to its column (`core/fit.py`), and writes the rows to the tables in `core/models/accounting.py`, updating existing rows rather than duplicating them. A record that can't be written is marked failed with a short reason (`core/errors.py`).

### (c) Validation against Tally

1. After each company's transform, `workers/validate.py` asks the connector for Tally's own figures: closing balances, and in a thorough check also voucher counts, stock quantities, bills and year-end balances (`connectors/tally/connector.py`).
2. `core/validation.py` compares them with the accounting tables and stores the results in `validation_runs` and `validation_issues` (`core/models/system.py`).
3. `core/alerts.py` raises or resolves an alert; `workers/cli.py` prints the outcome; `api/validation.py` serves it to the dashboard.

### (d) The scheduled worker

1. The **worker** container (`deploy/compose.yaml`) runs Celery with its scheduler, set up in `workers/celery_app.py`.
2. Every minute `sync_tick` looks at each active connection and starts a sync or a deletion check when it is due; a lock keeps two runs of one connection from overlapping.
3. The job itself is the same code as the command line: `workers/sync.py`, then `workers/validate.py`.

### (e) A `dev.ps1` command, from the terminal to the code

Take `./dev.ps1 sync full`:

1. `dev.ps1` reads the command, checks the environment file, and builds the Python command `python -m workers.cli sync --full ...`.
2. It runs that command inside the **api** container through `deploy/stack.ps1` (which calls `docker compose` with `deploy/compose.yaml`), in the background (`exec -d`), with a job id.
3. `workers/cli.py` runs the sync (flows a to c) and writes its output to the database (`workers/runs.py`).
4. `dev.ps1` then runs `python -m workers.cli watch` to show that output as it arrives.

Short commands (`status`, `summary`, `report`, `validate`, `fields`) run the same way, but in the foreground. `report` runs twice: once as Markdown, which `dev.ps1` saves under `reports/<env>/`, then as text for the screen. When the terminal shows colours, `dev.ps1` adds `-e LB_COLOR=1` and the status words are coloured. `./dev.ps1 test` runs the tests on the computer itself, not in a container.

### (f) Database migrations

1. A change to the tables is written in `core/models/` and as a new file in `migrations/versions/`, and described in [schema.md](schema.md).
2. `./dev.ps1 up` starts the one-off **migrate** container (`deploy/compose.yaml`), which runs `alembic upgrade head` as the `migrator` database user; `migrations/env.py` connects through `core/db.py`.
3. Alembic applies every migration not applied yet, in order, and records the latest in the database.

## 4. Where to look

| Question | Where |
| --- | --- |
| Where is the Tally connection code? | `data-plane/connectors/tally/`: `client.py` (talking to Tally), `envelopes.py` (requests), `parser.py` (answers), `connector.py` (putting it together), `mapping.py` (what Tally's data means). |
| Where are the database tables defined? | `data-plane/core/models/` in code; [schema.md](schema.md) for people; `data-plane/migrations/versions/` for the changes that create them. |
| What does an error or warning code mean? | [error-catalogue.md](error-catalogue.md); the codes live in `data-plane/core/problems.py`. |
| Where is the health report? | `data-plane/workers/report.py` (`./dev.ps1 report`). |
| Where are the validation checks? | `data-plane/core/validation.py`; run by `data-plane/workers/validate.py`; described in [schema.md](schema.md) Section 5.2. Why they differ: `data-plane/workers/analyse.py` (`./dev.ps1 validate analyse`). |
| Where are the environment settings? | `.env.test` / `.env.pilot` (not in git; templates `.env.*.example`), read by `data-plane/core/config.py`. |
| Where are the tests? | `data-plane/tests/` (Python) and `frontend/src/App.test.tsx`; recorded Tally answers in `data-plane/tests/fixtures/tally/`. |
| Where is a `dev.ps1` command implemented? | The command's block in `dev.ps1`, which calls `python -m workers.cli <command>`, implemented in `data-plane/workers/cli.py`. |
| Where is the scheduled sync? | `data-plane/workers/celery_app.py`. |
| Where is the transform? | `data-plane/core/transform.py`, with `core/names.py` and `core/fit.py`. |
| Where are the Docker containers defined? | `deploy/compose.yaml` and `data-plane/Dockerfile`; explained in [learning/docker.md](learning/docker.md). |
| What may be printed outside the test environment? | `data-plane/workers/cli.py` (`_show_names`) and `data-plane/core/errors.py`. |
| Where is the test company's data? | `data-plane/devtools/tally_seed/data.py`. |
| Is there a picture of the tables or the flow? | [diagrams/README.md](diagrams/README.md); regenerate with `./dev.ps1 diagrams`. |
| Where is a design decision explained? | [architecture.md](architecture.md) Section 11 (the ADRs). |
| What is planned next? | [roadmap.md](roadmap.md). |

## 5. Glossary

| Term | Meaning |
| --- | --- |
| **Alias** | Another name something is known by, e.g. the original name of a Tally group the user renamed. |
| **Alembic** | The tool that applies migrations to the database. |
| **API** | The part other programs (like the dashboard) call over the web to get data. |
| **Canonical model** | The standard, source-independent way the accounting data is stored, the same whatever the source (Tally, later others). |
| **Checkpoint** | A note that one piece of a sync was fetched and stored, so an interrupted sync can continue from there instead of starting over. |
| **Chunk** | One piece of a sync: the company record, one kind of master, or one month of vouchers. |
| **CLI (command line)** | Commands typed in a terminal; here mostly `python -m workers.cli ...`, usually started through `dev.ps1`. |
| **Connection** | One configured source: which Tally, which companies, and its settings. |
| **Connector** | The code that knows how to read one kind of source, behind a standard interface. |
| **Container** | A small, self-contained running copy of a program with everything it needs, started by Docker. |
| **Control plane / data plane** | The provider-hosted login and licence service (never sees client data) and the client-hosted system that holds and processes all data. |
| **Deletion check** | A run that lists what still exists in Tally and marks as deleted what has gone. |
| **Docker / Docker Compose** | The tool that runs the containers, and its file listing which containers to run together. |
| **ER diagram** | Entity-relationship diagram: a picture of the tables, their keys and how they refer to each other. |
| **Entity** | One company in LedgerBridge (one Tally company), with an id. |
| **Environment** | A separate set of containers, settings and data: `test` (the test company) and `pilot` (client data). |
| **`extra`** | A field on accounting rows holding everything the source sent that has no column of its own, and values that didn't fit their column. |
| **Fixture** | A recorded Tally answer used by tests instead of the real Tally. |
| **Ledger, group, voucher** | Accounting terms: an account; a heading accounts are grouped under; one transaction (with its lines). |
| **Master** | A Tally record that other records refer to: groups, ledgers, voucher types, stock items, cost centres. |
| **Migration** | A file that changes the database's structure in a controlled, recorded step. |
| **Raw record** | One object from the source, stored exactly as received, before any transformation. |
| **Reporting layer** | Database views made for dashboards and the AI; the only part the AI can read. |
| **Sync** | Fetching what changed in the source, storing it and transforming it. A **full** sync fetches everything. |
| **Transform** | Turning raw records into rows of the accounting tables. **Retry** does it again for failed records; **rebuild** for every record. |
| **Validation** | Checking the accounting tables against the books' own figures: balances, counts, stock, bills. |
| **Worker** | The container that runs background jobs on a schedule (Celery, with Redis as its message queue). |

## Change log

| Date | Version | Change |
| --- | --- | --- |
| 2026-10-16 | 0.12 | `workers/compare.py`, `tests/test_compare_ledger.py`. |
| 2026-10-16 | 0.11 | `tests/test_forex.py`. |
| 2026-10-16 | 0.10 | `tests/test_line_attribution.py`. |
| 2026-10-15 | 0.9 | Migration 0016; `tests/test_stock_ledger_and_dates.py`. |
| 2026-10-15 | 0.8 | `core/dates.py`, `tests/test_dates.py`. |
| 2026-10-15 | 0.7 | Migration 0015; job work in the seed; `tests/test_job_work.py`. |
| 2026-10-15 | 0.6 | `workers/locks.py`; `tests/test_dev_script_args.py` (each dev.ps1 command's docker arguments), `tests/test_run_lock.py`. |
| 2026-10-14 | 0.5 | Migration 0014; the seed reproduces Tally's counting rules; `tests/test_counting_rules.py` and `tests/fixtures/tally/rules/`. |
| 2026-10-14 | 0.4 | `core/problems.py`, `workers/report.py`, `workers/style.py`, `devtools/error_catalogue.py`, `docs/error-catalogue.md`, `reports/`; migration 0013. |
| 2026-10-14 | 0.3 | `workers/analyse.py` (`validate analyse`); migration 0012. |
| 2026-10-13 | 0.2 | Diagrams embedded (Section 1); `devtools/diagrams.py`, `docs/diagrams/` and their test. |
| 2026-10-13 | 0.1 | First version, from the repository as of migration 0011. |
