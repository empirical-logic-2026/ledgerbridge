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
| `./dev.ps1 up` | Builds and starts MySQL, Redis, Qdrant and the API, waits until they're healthy, applies database migrations, then prints the dashboard, API health and API docs URLs. It first checks that the ports in `.env.test` are free. |
| `./dev.ps1 status` | Shows the containers and the API's readiness (MySQL, Redis, Qdrant). |
| `./dev.ps1 logs api` | Follows one service's logs (`mysql`, `redis`, `qdrant`, `api`, `worker`); leave out the name for all. Ctrl+C stops. |
| `./dev.ps1 tally-companies` | Lists the companies loaded in TallyPrime. Runs inside the API container. |
| `./dev.ps1 extract -Company "LedgerBridge Test Co"` | Full extraction of one company into `raw.raw_records`, logged in `app.sync_runs`. |
| `./dev.ps1 test` | Backend lint, unit tests and, if the stack is up, integration tests; then frontend lint and tests. **Test environment only.** The migration test resets the test database tables. |
| `./dev.ps1 down` | Stops and removes the containers. Data volumes are kept. |
| `./dev.ps1 up -Env pilot` | The same commands against `.env.pilot` (developer only; `test` refuses pilot). |

First time:

```powershell
Copy-Item .env.test.example .env.test   # then set the two MySQL passwords
./dev.ps1 up
cd frontend; npm install; npm run dev    # dashboard on http://localhost:5175
```

The dashboard dev server always uses port 5175, and fails rather than switching ports, because the API only accepts browser calls from `FRONTEND_ORIGIN`. For pilot, run `npm run dev -- --port 5174`.

The test API listens on **http://127.0.0.1:8001** (`/health/ready`, `/docs`). For lower-level Docker commands, use `./deploy/stack.ps1 -Env test <docker compose args>`. See [docs/learning/docker.md](docs/learning/docker.md) for how the Docker setup works.

## Repository layout

```text
/control-plane   auth, MFA, licences (placeholder until Phase 1b)
/data-plane      API, core, connectors, workers, AI, migrations
/agent           connector agent (placeholder until Phase 1b)
/frontend        React + TypeScript dashboard
/deploy          Docker Compose, MySQL init script and stack script
dev.ps1          developer commands (up, down, status, test, logs, tally-companies, extract)
/docs            requirements, architecture, schema, roadmap
```
