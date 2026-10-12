# Pilot runbook: loading the client's backup companies (M9)

| Field | Value |
| --- | --- |
| Version | 0.1 |
| Date | 2026-10-12 |
| Who runs it | **The developer only.** Claude Code never runs these steps, never connects to the `pilot` environment and never sees its data (CLAUDE.md, ADR-011). |

This runbook loads the client's two Tally companies into the `pilot` environment, syncs them, validates them against Tally, and shows the results as **counts and pass/fail only**. It's the start of milestone M9 (roadmap.md).

## Rules for this run

- **Client data stays on this machine.** The pilot environment has its own database, ports and env file (`.env.pilot`), separate from `test` (ADR-012).
- **What you may share with Claude Code:** the output of `./dev.ps1 summary -Env pilot`, `./dev.ps1 status -Env pilot`, and the output of `sync`, `validate` and `connect` in the pilot environment. Outside the test environment these print no company, ledger or party names, no amounts and no error messages (only their type), so they're safe to paste.
- **Never share:** `.env.pilot`, anything from the API (`http://127.0.0.1:8010/api/...` returns amounts and names), database contents, Tally files, screenshots of Tally or the dashboard, or company names.
- **AI:** the pilot uses a local model only (`AI_PROVIDER=ollama`); the data plane refuses `anthropic` when `APP_ENV=pilot` (PIL-005). Nothing in this runbook calls an AI model.

## What you need

- Docker Desktop running.
- TallyPrime on this PC with its XML server on port 9000 (F1 > Settings > Connectivity: TallyPrime acts as *Server*, port 9000).
- The client's two companies restored from their backups and **both loaded** in TallyPrime (Alt+F3 > Select Company). Note their exact names as Tally shows them. The connector refers to companies by name, and only reads (it sends Export requests only).
- The test environment can keep running: the pilot uses other ports (MySQL 3317, Redis 6390, Qdrant 6343, API 8010).

## Steps

### 1. Create `.env.pilot` (once)

```powershell
./dev.ps1 init-env -Env pilot
```

This copies `.env.pilot.example` to `.env.pilot` and replaces the five MySQL passwords (root, `app_rw`, `migrator`, `report_ro`, `ai_ro`) with 32 random letters and digits. The values are never printed. It refuses if `.env.pilot` already exists.

- Keep a backup of `.env.pilot` somewhere safe, such as a password manager. The pilot database is created with these passwords; without the file you can't reach it.
- Never commit it (it's git-ignored) and never share it.

### 2. Start the pilot stack

```powershell
./dev.ps1 up -Env pilot
```

This builds and starts MySQL, Redis, Qdrant, the API and the worker as the Docker Compose project `ledgerbridge-pilot`. On the first start, MySQL creates the four databases and the database users from `.env.pilot`. Then the one-off `migrate` container creates the tables. Expect `LedgerBridge (pilot) is up.` and `API readiness: ok`.

### 3. Check that Tally shows both companies

```powershell
./dev.ps1 tally-companies -Env pilot
```

Expect `2 entities in connection 'tally-pilot'`. Names aren't printed in the pilot environment; check them in TallyPrime if needed.

### 4. Create the connection

```powershell
./dev.ps1 connect -Env pilot -Origin backup -Paused -Company "<exact name of company 1>","<exact name of company 2>"
```

- `-Origin backup` tags every row as backup data (IMP-004).
- `-Paused` turns off scheduled syncs. Backup data doesn't change, and it stops the worker from starting a sync while you run the first one by hand. Manual syncs still work.
- Expect `origin backup, paused, 2 entities configured, 2 found in the source`. If it says `1 not found`, the name doesn't exactly match TallyPrime's (spaces, punctuation, capitals) or the company isn't loaded. Fix it and run the command again: it replaces the list.

### 5. Sync and validate

```powershell
./dev.ps1 sync full -Env pilot
```

This runs, in order:
1. A **full sync** of both companies: Tally → `ledgerbridge_source` → `ledgerbridge_accounting`.
2. A **deletion check**.
3. **Validation** of each company as of today:
   - every voucher balances
   - the trial balance balances
   - each ledger's balance equals Tally's own closing balance
   - *Profit & Loss A/c* reconciles with the computed profit

Large companies can take several minutes: vouchers are read one month at a time.

### 6. See the results

```powershell
./dev.ps1 summary -Env pilot
./dev.ps1 status -Env pilot
```

`summary` shows for the connection the last sync and deletion check, plus any raw records that failed to transform. For each company (`entity <id>`) it shows:
- counts of ledgers (and how many are unmapped), parties, vouchers (cancelled, deleted in source) and effective voucher lines
- the latest validation, PASSED or FAILED, with each failed check code and how often it occurred

It also lists open alerts. **This is the output to share.**

## Reading the results

| Line | Meaning | What to do |
| --- | --- | --- |
| `Sync run N (full): succeeded`, `failed: 0` | Everything was read and transformed. | – |
| `raw records that failed to transform: N` (N > 0) | Some Tally objects couldn't be mapped. | Share the count and run `summary`. The reason is stored per record; Claude Code will ask for the error types only. |
| `unmapped ...: N` | Ledgers without a standard account (e.g. under *Indirect Expenses*), by design. Reports will place them under the nearest standard parent account (M6). | Expected. Share the count. |
| `warnings (mapping assumptions): N` | GST ledgers whose duty head Tally left empty, assumed to be Central Tax (schema.md 7.3, an assumption to verify). | Check in TallyPrime that the company's Central Tax (CGST) ledgers number N. Report "matches" or "doesn't match". |
| `validation: ... PASSED` | All checks passed. | – |
| `error: voucher_unbalanced xN` | N vouchers whose lines don't sum to zero after transformation. | Share the count. |
| `error: tb_unbalanced xN` | The trial balance doesn't balance at a year end or today. | Share the count; usually follows another error. |
| `error: closing_mismatch xN` | N ledgers whose balance differs from Tally's. | Share the count. |
| `error: ledger_missing xN` | Ledgers in Tally but not synced, or the other way round. | Share the count; re-run step 5 once. |
| `error: profit_carrier_mismatch x1` | *Profit & Loss A/c* doesn't reconcile with the computed profit. Known points to check: books spanning several financial years, and companies that keep stock without integrated inventory (schema.md 10). | Share it, plus how many financial years the books cover and whether inventory is maintained. |
| `error: closing_unavailable` | Tally couldn't be reached for closing balances. | Check that TallyPrime is running with both companies loaded; run `./dev.ps1 validate -Env pilot`. |
| `warning: opening_difference x1` | The company's opening balances don't total zero (Tally's "Difference in opening balances"). Not a sync error. | Note it. The fix belongs in the client's books. |

## Afterwards

- **Validate again** (e.g. after reloading Tally): `./dev.ps1 validate -Env pilot`.
- **Reload a newer backup:** restore it in TallyPrime, then `./dev.ps1 sync full -Env pilot`. Changes are picked up by AlterID, and deletions by the deletion check.
- **Stop:** `./dev.ps1 down -Env pilot`. The data stays in the pilot volumes.
- **Start over completely:** `./deploy/stack.ps1 -Env pilot down -v` deletes all pilot data. Then `./dev.ps1 up -Env pilot` with the same `.env.pilot`.
- **Never** run `./dev.ps1 test` against pilot (it refuses), and never point `-Env test` at client companies.

## Change log

| Date | Version | Change |
| --- | --- | --- |
| 2026-10-12 | 0.1 | First version, prepared with M4: `init-env`, `connect`, `summary`, name-free CLI output outside test. Not yet run. |
