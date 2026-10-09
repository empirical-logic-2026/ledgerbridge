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

## Run locally (test)

```powershell
# Stack: MySQL, Redis, Qdrant and the API (add --profile workers for the Celery worker)
./deploy/stack.ps1 -Env test up -d --build
curl http://localhost:8000/health/ready

# Backend
cd data-plane
uv sync
uv run python -m pytest

# Frontend
cd frontend
npm install
npm run dev   # http://localhost:5173
```

## Repository layout

```text
/control-plane   auth, MFA, licences (placeholder until Phase 1b)
/data-plane      API, core, connectors, workers, AI, migrations
/agent           connector agent (placeholder until Phase 1b)
/frontend        React + TypeScript dashboard
/deploy          Docker Compose and stack script
/docs            requirements, architecture, schema, roadmap
```
