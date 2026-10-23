# LedgerBridge

Connects to accounting systems (Tally first), stores their data in MySQL, and provides MIS dashboards, reporting and AI querying. See `docs/` for requirements, architecture, schema and roadmap; [docs/codebase-guide.md](docs/codebase-guide.md) explains in plain language what every folder and file is for.

**Knowledge base:** [the rulebook](docs/rules/validation-and-conversion-rules.md) (every rule for converting and validating Tally data), [the schema reference](docs/database/schema-reference.md) (every table and column), [the project history](docs/project-history.md) and the [progress log](docs/progress-log.md). Word and PDF copies are in `docs/export/` (`./dev.ps1 docs-export`).

## Prerequisites

- Docker Desktop
- [uv](https://docs.astral.sh/uv/) (installs Python 3.12 for the data plane)
- Node.js 20+ and npm

## Environments

There are two separate environments, each run as its own Docker Compose project with its own data (architecture.md §13, ADR-011, ADR-012):

| Environment | Env file | Data | Who uses it |
| --- | --- | --- | --- |
| `test` | `.env.test` | LedgerBridge Test Co | Developer and Claude Code |
| `pilot` | `.env.pilot` | Client backup companies | Developer only, never Claude Code |

Create an env file by copying the matching example (`.env.test.example` → `.env.test`) and filling in passwords. Real env files are git-ignored.

## Run locally with `dev.ps1`

`dev.ps1` in the repo root wraps the everyday tasks. It uses the **test** environment unless you pass `-Env pilot`, which is for the developer only. All Docker calls go through `deploy/stack.ps1`, so the right env file is always loaded.

| Command | What it does |
| --- | --- |
| `./dev.ps1 init-env -Env pilot` | Creates `.env.pilot` from `.env.pilot.example` with strong random MySQL passwords (never printed). Refuses if the file exists. Developer only; see [docs/pilot-runbook.md](docs/pilot-runbook.md). |
| `./dev.ps1 up` | Builds and starts MySQL, Redis, Qdrant and the API, waits until they're healthy, applies database migrations (one-off `migrate` container, as the `migrator` user), then prints the dashboard, API health and API docs URLs. It first checks that the ports in `.env.test` are free. |
| `./dev.ps1 status` | Shows the containers, the API's readiness (MySQL, Redis, Qdrant), and for each connection its last sync and last deletion check, when each is next due, the latest validation per company (pass/fail, with a warning when opening balances don't total zero) and open alerts. |
| `./dev.ps1 logs api` | Follows one service's logs (`mysql`, `redis`, `qdrant`, `api`, `worker`); leave out the name for all. Ctrl+C stops. |
| `./dev.ps1 connect -Origin live -Company "A","B" [-Activate \| -Paused]` (or `-All`) | Creates or updates this environment's connection: origin (`live` or `backup`) and the companies it syncs, by exact name or `-All` loaded companies; each is stored by its GUID. **New connections are paused** (the worker doesn't sync them on a schedule; manual syncs work) until `-Activate`; `-Paused` stops scheduled syncs again. Reports how many of the companies were found in Tally. `-TimeoutSec`, `-PauseSec` and `-PartMonth` set the connection's request timeout, pause between requests and part-month support (`status` shows the values in effect). Refuses with a clear message while a sync of the connection is running. |
| `./dev.ps1 report [-Details]` | One health report: overall verdict (OK / ATTENTION NEEDED / FAILED), connection, data loaded, work in progress, validation per company (compared with the previous run), warnings, and each problem's meaning, likely cause and next command. Saved as Markdown under `reports/<env>/` (git-ignored). No names or amounts. Codes: [docs/error-catalogue.md](docs/error-catalogue.md) (OPS-005). |
| `./dev.ps1 summary` | Counts and pass/fail per connection and company: last sync and deletion check, ledgers, unmapped ledgers, vouchers, the latest validation and its failed check codes, open alerts. No names or amounts, in any environment. |
| `./dev.ps1 transform retry [-Company "..."] [-NoValidate]` | Transforms stored records again (those that failed, and any left pending) with the current code, without contacting Tally, then validates the companies it touched. Runs in the background like a sync (DAT-008, ADR-025). |
| `./dev.ps1 transform rebuild [-Company "..."] [-NoValidate]` | Transforms every stored object again (processed, failed and pending), from its latest raw record, with the current code, without contacting Tally: fills `extra` and the field catalogue for data transformed by older code. Objects deleted in Tally stay deleted. Then validates. |
| `./dev.ps1 validate analyse [-Company "..."]` | Tests explanations for every validation mismatch (opening balances, signs, voucher types, year ends, units, stock journals, rounding, foreign currency, bills) and reports how many each explains: counts and Tally's standard names only. Reads Tally's figures (VAL-010). |
| `./dev.ps1 statements [-From YYYY-MM-DD]` | Reads Tally's own Trial Balance, Balance Sheet and Profit and Loss (read-only) at every month end and year end, stores its stock values and statements, builds ours and compares them line by line (ADR-040). Prints counts and statement names only, and when lines differ a summary safe to share (standard names, missing or different, dates, what each difference equals); the lines are in `ledgerbridge_reporting.v_trial_balance`, `v_profit_loss`, `v_balance_sheet` and, ours against Tally's, `v_statement_check`. Runs in the background like a sync. Thorough validation (`validate`, full syncs) checks the as-of date and year ends itself. |
| `./dev.ps1 transform explain [-CheckSource]` | Why references by name didn't resolve (ledger → group, voucher → ledger, ...): kinds of difference, close matches, reserved names, whether the target is stored; with `-CheckSource` also what Tally lists now. Counts and kinds only (ADR-027). |
| `./dev.ps1 fields` / `promote-field -FieldId N -Code C -Name "..."` | The field catalogue: fields Tally sent that have no column (e.g. UDFs), kept per record in `extra`. A catalogued voucher field can become a reporting dimension (ADR-025). |
| `./dev.ps1 sync watch` / `sync abandon` | Syncs run in the background inside the api container; `sync` follows them, and losing the terminal never stops one. `sync watch` follows the latest one again; `sync abandon` (type `abandon` to confirm) marks runs whose process is gone as interrupted, keeping their progress (ADR-024). |
| `./dev.ps1 sync full -Restart` / `-From 2024-03-01` | A full sync continues after the last completed chunk if an earlier one was interrupted; `-Restart` fetches everything again; `-From` fetches again from a date (a damaged range). Each chunk prints a progress line; slow months are split automatically (ADR-022). |
| `./dev.ps1 entity-check` | Read-only diagnostic: are the connection's companies in Tally, and if not, how do the names differ (spacing, punctuation, case, suffix); also selects each company once and checks whether Tally then lists names differently. Never prints names. |
| `./dev.ps1 reset -Env pilot` | Stops the environment's stack and deletes only its own data volumes (MySQL, Redis, Qdrant) after you type `delete pilot`. Keeps `.env.pilot`. For the test environment it needs `-Force`. |
| `./dev.ps1 tally-companies` | Lists the companies loaded in TallyPrime. Runs inside the API container. Only reads: never creates or changes a connection. |
| `./dev.ps1 extract -Company "LedgerBridge Test Co"` | Full extraction of one company into `ledgerbridge_source.raw_records`, logged in `ledgerbridge_system.sync_runs`. |
| `./dev.ps1 sync -Company "LedgerBridge Test Co"` | Fetches what changed in Tally since the last sync (everything the first time; add `full` to force it) and transforms it into the accounting tables. Prints counts, the ledgers without a standard account and any mapping assumptions (warnings). `sync full` also runs a deletion check; `sync deletions` runs only the deletion check, which finds vouchers and masters deleted in Tally. The `worker` container syncs every 5 minutes and checks for deletions every hour on its own. |
| `./dev.ps1 validate -Company "LedgerBridge Test Co"` | Checks the synced books as of today: every voucher balances, the trial balance balances, and each ledger's balance equals Tally's own closing balance (*Profit & Loss A/c* is reconciled with the computed profit). Prints counts, check codes and pass/fail only. Every sync also validates afterwards; failures raise an alert. Details with amounts: `http://127.0.0.1:8001/api/validation/status`, `/api/validation/runs/{id}`, `/api/alerts`. |
| `./dev.ps1 seed-test-data` | Fills **LedgerBridge Test Co** in TallyPrime with repeatable test data: ledgers, GST sales and purchases, bills, a cancelled voucher, two altered vouchers, a deleted voucher, and more. Safe to re-run: only missing items are created. `seed-test-data create-only` skips the alterations, cancellation and deletion, so you can sync the vouchers before they change. The deleted voucher leaves an empty stock group, *lb-seed DEL-1 deleted*, so re-runs don't create it again. Test environment only; it refuses unless that company is the only one loaded (ADR-014). Prints the Trial Balance you should then see in TallyPrime. |
| `./dev.ps1 diagrams` | Regenerates the ER and database diagrams in `docs/diagrams/` from the models, then draws every diagram as SVG and PNG with the mermaid-cli Docker image (no database or Tally needed). See [docs/diagrams/README.md](docs/diagrams/README.md). |
| `./dev.ps1 docs-export` | Word and PDF copies of the rulebook, schema reference and project history in `docs/export/`, with diagrams, made by the official pandoc Docker image (run `diagrams` first). |
| `./dev.ps1 test` | Backend lint, unit tests and, if the stack is up, integration tests; then frontend lint and tests. **Test environment only.** The migration test resets the test database tables. |
| `./dev.ps1 down` | Stops and removes the containers. Data volumes are kept. |
| `./dev.ps1 up -Env pilot` | The same commands against `.env.pilot` (developer only; `test` refuses pilot). Outside the test environment the commands print no company, ledger or party names and no error messages, only counts and pass/fail, and `trial-balance` refuses to run. The steps are in [docs/pilot-runbook.md](docs/pilot-runbook.md). |

First time:

```powershell
Copy-Item .env.test.example .env.test   # then set the five MySQL passwords
./dev.ps1 up
cd frontend; npm install; npm run dev    # dashboard on http://localhost:5175
```

The dashboard dev server always uses port 5175, and fails rather than switching ports, because the API only accepts browser calls from `FRONTEND_ORIGIN`. For pilot, run `npm run dev -- --port 5174`.

The test API listens on **http://127.0.0.1:8001** (`/health/ready`, `/docs`). For lower-level Docker commands, use `./deploy/stack.ps1 -Env test <docker compose args>`. See [docs/learning/docker.md](docs/learning/docker.md) for how the Docker setup works.

## Automated checks

Every pull request runs [.github/workflows/checks.yml](.github/workflows/checks.yml) on GitHub (SEC-009, ADR-039). Nothing in it touches Tally or client data: the integration tests replay responses recorded from LedgerBridge Test Co on a throwaway MySQL. Every tool is free and needs no account.

| Job | What it checks | Fails when |
| --- | --- | --- |
| Python lint and unit tests | `ruff check` (including its security rules), `ruff format --check`, `pytest` | Any finding or failing test |
| Frontend lint, tests and build | `oxlint`, `vitest`, `tsc` and `vite build` | Any finding, failing test or build error |
| Integration tests | Migrations, MySQL users' grants and syncs on MySQL 8.4, Redis and Qdrant service containers | Any failing test |
| dev.ps1 tests (Windows PowerShell) | On a Windows machine: the docker compose arguments of every `dev.ps1` command, and the refusals of `reset` and `sync abandon` (Linux skips these) | Any failing or skipped test |
| Dependency vulnerabilities | `pip-audit` on `uv.lock`, `npm audit` on `package-lock.json` | Python: any known vulnerability; npm: high or critical |
| Static security analysis | Semgrep's public rules on all code, Dockerfiles and workflows | A high-severity (ERROR) finding |
| Secret scanning | gitleaks over every commit in the history | Any secret found |
| Container image vulnerabilities | Trivy on the data-plane image (third-party images listed for information only) | A high or critical vulnerability that has a fix |
| **All checks** | That every job above passed | Any job failed or was skipped |

**Reading the results:**

- **Where:** in the PR, the checks box at the bottom of the "Conversation" tab lists each job with a tick or a cross; "Details" opens its log. All runs are under the repository's **Actions** tab. From a terminal: `gh pr checks <number>` and `gh run view <run-id> --log-failed`.
- **What you need:** **"All checks" is required on `dev` and `main`** (branch protection), so the merge button stays blocked until it is green.
- **What a failure looks like, by job:**
  - **Ruff and tests:** the file, line and rule, or the failing test.
  - **pip-audit:** the package, version, advisory ID and the version that fixes it.
  - **npm audit:** a table of packages and advisories.
  - **Semgrep:** each finding as file, line, rule and a link to the rule's explanation.
  - **gitleaks:** the commit, file and line, with the secret itself redacted.
  - **Trivy:** a table of packages, CVEs, severity and fixed version.
- **What to do:** fix the cause: upgrade the package, change the code, or remove the secret and rotate it. A justified exception needs a comment saying why (see [docs/security/security-guide.md](docs/security/security-guide.md)).

Security documents: [threat model](docs/security/threat-model.md) and [security guide](docs/security/security-guide.md).

## Databases

MySQL holds four databases, one per layer (ADR-016): `ledgerbridge_source` (data as received), `ledgerbridge_accounting` (canonical model), `ledgerbridge_reporting` (semantic layer, the only one the AI can read) and `ledgerbridge_system` (connections, sync, users, audit). Each MySQL user has only the rights it needs: see `docs/schema.md` Section 2.1.

## Repository layout

```text
/control-plane   auth, MFA, licences (placeholder until Phase 1b)
/data-plane      API, core, connectors, workers, AI, migrations
/agent           connector agent (placeholder until Phase 1b)
/frontend        React + TypeScript dashboard
/deploy          Docker Compose, MySQL init script and stack script
dev.ps1          developer commands (see the table above)
/docs            requirements, architecture, schema, roadmap
```
