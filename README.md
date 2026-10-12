# LedgerBridge

Connects to accounting systems (Tally first), stores their data in MySQL, and provides MIS dashboards, reporting and AI querying. See `docs/` for requirements, architecture, schema and roadmap.

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
| `./dev.ps1 connect -Origin backup -Paused -Company "A","B"` | Creates or updates this environment's connection: origin (`live` or `backup`), the exact companies it syncs, and whether the worker syncs it on a schedule (`-Paused`: no). Reports how many of the companies were found in Tally. |
| `./dev.ps1 summary` | Counts and pass/fail per connection and company: last sync and deletion check, ledgers, unmapped ledgers, vouchers, the latest validation and its failed check codes, open alerts. No names or amounts, in any environment. |
| `./dev.ps1 tally-companies` | Lists the companies loaded in TallyPrime. Runs inside the API container. |
| `./dev.ps1 extract -Company "LedgerBridge Test Co"` | Full extraction of one company into `ledgerbridge_source.raw_records`, logged in `ledgerbridge_system.sync_runs`. |
| `./dev.ps1 sync -Company "LedgerBridge Test Co"` | Fetches what changed in Tally since the last sync (everything the first time; add `full` to force it) and transforms it into the accounting tables. Prints counts, the ledgers without a standard account and any mapping assumptions (warnings). `sync full` also runs a deletion check; `sync deletions` runs only the deletion check, which finds vouchers and masters deleted in Tally. The `worker` container syncs every 5 minutes and checks for deletions every hour on its own. |
| `./dev.ps1 validate -Company "LedgerBridge Test Co"` | Checks the synced books as of today: every voucher balances, the trial balance balances, and each ledger's balance equals Tally's own closing balance (*Profit & Loss A/c* is reconciled with the computed profit). Prints counts, check codes and pass/fail only. Every sync also validates afterwards; failures raise an alert. Details with amounts: `http://127.0.0.1:8001/api/validation/status`, `/api/validation/runs/{id}`, `/api/alerts`. |
| `./dev.ps1 seed-test-data` | Fills **LedgerBridge Test Co** in TallyPrime with repeatable test data: ledgers, GST sales and purchases, bills, a cancelled voucher, two altered vouchers, a deleted voucher, and more. Safe to re-run: only missing items are created. `seed-test-data create-only` skips the alterations, cancellation and deletion, so you can sync the vouchers before they change. The deleted voucher leaves an empty stock group, *lb-seed DEL-1 deleted*, so re-runs don't create it again. Test environment only; it refuses unless that company is the only one loaded (ADR-014). Prints the Trial Balance you should then see in TallyPrime. |
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
