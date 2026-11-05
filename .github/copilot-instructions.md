# LedgerBridge: context for GitHub Copilot

## What this project is
LedgerBridge copies accounting data from TallyPrime (read-only, XML over HTTP on port 9000), converts it into clean accounting tables, validates figures against Tally, and serves the dashboard from the client-hosted data plane. Read `CLAUDE.md` and the relevant architecture, schema, dashboard, and validation documentation before making non-trivial changes.

## Environments and safety
- `test` contains synthetic data; `pilot` contains client data.
- Never read `.env.pilot`, pilot databases, pilot backups, private reports, or client raw payloads.
- Never run `./dev.ps1 up -Env pilot` or any other pilot command while migrations in `data-plane/migrations/versions/` are uncommitted. First ensure the migration files are committed and form a reviewed history based on the current `dev` branch.
- Do not run pilot migrations, syncs, resets, or deployments. The developer runs pilot operations.
- Never discard, reset, stash, overwrite, or commit existing user changes unless explicitly asked.

## Development
- Use the existing Python, FastAPI, SQLAlchemy, Alembic, React, TypeScript, Vite, Ant Design, and ECharts stack. Ask before adding dependencies.
- Add or update tests with code changes and run the narrowest relevant checks.
- MySQL schema changes require a new Alembic migration and matching `docs/schema.md` updates; never edit an applied migration.
- Preserve canonical debit-positive accounting signs, exact Decimal money, source read-only behavior, and validation against Tally.
- Follow `CLAUDE.md` for repository conventions and end change reports with What changed, Why, Security impact, and Code walkthrough.
