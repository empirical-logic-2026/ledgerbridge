# Pilot runbook: loading the client's backup companies (M9)

| Field | Value |
| --- | --- |
| Version | 0.3 |
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

### 0. If an earlier attempt left data: reset

The first pilot attempt (2026-10-12) may have synced data tagged `live` before it failed. Start from an empty pilot database:

```powershell
./dev.ps1 reset -Env pilot
```

This stops the pilot stack and deletes **only the pilot volumes**: `ledgerbridge-pilot_mysql-data`, `_redis-data` and `_qdrant-data`. It lists them first and asks you to type `delete pilot`. `.env.pilot` is kept, so the next `up` recreates the databases with the same passwords. Skip this step on a first run.

### 1. Create `.env.pilot` (once)

```powershell
./dev.ps1 init-env -Env pilot
```

This copies `.env.pilot.example` to `.env.pilot` and replaces the five MySQL passwords (root, `app_rw`, `migrator`, `report_ro`, `ai_ro`) with 32 random letters and digits. The values are never printed. It refuses if `.env.pilot` already exists; after a reset, keep using the existing file.

- Keep a backup of `.env.pilot` somewhere safe, such as a password manager. The pilot database is created with these passwords; without the file you can't reach it.
- Never commit it (it's git-ignored) and never share it.

### 2. Start the pilot stack

```powershell
./dev.ps1 up -Env pilot
```

This builds and starts MySQL, Redis, Qdrant, the API and the worker as the Docker Compose project `ledgerbridge-pilot`. On the first start, MySQL creates the four databases and the database users from `.env.pilot`. Then the one-off `migrate` container creates the tables. Expect `LedgerBridge (pilot) is up.` and `API readiness: ok`.

Nothing syncs yet: there's no connection, and the worker only syncs connections that have been explicitly activated.

### 3. Create the connection, before anything else that touches Tally

```powershell
./dev.ps1 connect -Env pilot -Origin backup -All
```

- `-All` takes **every company currently loaded in TallyPrime**, so load only the two client companies. Nothing has to be typed, and nothing has to match. The connection stores each company's GUID (Tally's permanent identifier), and every later command finds the companies by GUID, even if Tally later shows a name slightly differently.
- Instead of `-All` you can name them: `-Company "<exact name 1>","<exact name 2>"`. Names must match exactly as Tally shows them, spaces included.
- `-Origin backup` tags every row as backup data (IMP-004). The connection must exist with this origin **before the first sync**, otherwise the data would be tagged `live`.
- **The connection stays paused:** the worker never syncs it on a schedule. New connections always start paused, and only `-Activate` changes that. Backup data doesn't change, so there's no reason to activate it. Manual syncs still work.
- Expect `origin backup, paused, 2 entities configured, 2 found in the source (2 loaded there)`. With `-Company`, `1 not found` means a name doesn't exactly match; run step 4 to see how it differs, or use `-All`. Running `connect` again replaces the list.
- If it says `Refused: sync run N ... is running`, a sync is in progress. Wait for it, then run `connect` again. It never hangs.

### 4. Check the companies: `entity-check`

```powershell
./dev.ps1 entity-check -Env pilot
```

A read-only diagnostic that prints no names. It shows:
- **each company Tally lists:** the length of its name and anything unusual about it, such as a leading, trailing or repeated space, or characters outside plain ASCII (named by Unicode, e.g. `U+2013 EN DASH`);
- **each configured company:** found by GUID, or not found, and then how its stored name differs from the closest one Tally lists (e.g. `spacing around hyphens`, `repeated spaces`, `a bracketed suffix such as '(from 1-Apr-23)'`);
- **a selection check:** each company is selected once, exactly as a sync does, and Tally's company list is read again. If Tally then shows a name differently, it says how.

It ends with `Result: no problems found` or `N problem(s) found`. **Share its output** if anything is found. `./dev.ps1 tally-companies -Env pilot` just counts the loaded companies.

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

Large companies can take several minutes: vouchers are read one month at a time. Progress lines with the time appear as it goes (`[10:42:01] entity 1 of 2: 15,000 records received so far`). It ends with one line such as:

```text
Result: full succeeded; deletion_check succeeded; validation passed
```

The sync and the validation are reported separately. A sync that fetched and transformed everything stays `succeeded` even if validation then fails or can't run (`validation failed`, with the reason on the line above).

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
| `EntityLookupError: N of M configured entities are not available in the source` | Tally doesn't list a configured company (by GUID). | Check that both companies are loaded; run `./dev.ps1 entity-check -Env pilot` and share its output. |
| `error: voucher_unbalanced xN` | N vouchers whose lines don't sum to zero after transformation. | Share the count. |
| `error: tb_unbalanced xN` | The trial balance doesn't balance at a year end or today. | Share the count; usually follows another error. |
| `error: closing_mismatch xN` | N ledgers whose balance differs from Tally's. | Share the count. |
| `error: ledger_missing xN` | Ledgers in Tally but not synced, or the other way round. | Share the count; re-run step 5 once. |
| `error: profit_carrier_mismatch x1` | *Profit & Loss A/c* doesn't reconcile with the computed profit. Known points to check: books spanning several financial years, and companies that keep stock without integrated inventory (schema.md 10). | Share it, plus how many financial years the books cover and whether inventory is maintained. |
| `error: <ErrorType>: <short message>` from any command | Something failed unexpectedly. Outside the test environment you see only the error type and a short message (for database errors, the MySQL code), never SQL or values. | Share that line as it is. |
| `error: closing_unavailable` | Tally couldn't be reached for closing balances. | Check that TallyPrime is running with both companies loaded; run `./dev.ps1 validate -Env pilot`. |
| `warning: opening_difference x1` | The company's opening balances don't total zero (Tally's "Difference in opening balances"). Not a sync error. | Note it. The fix belongs in the client's books. |

## Afterwards

- **Validate again** (e.g. after reloading Tally): `./dev.ps1 validate -Env pilot`.
- **Reload a newer backup:** restore it in TallyPrime, then `./dev.ps1 sync full -Env pilot`. Changes are picked up by AlterID, and deletions by the deletion check.
- **Stop:** `./dev.ps1 down -Env pilot`. The data stays in the pilot volumes.
- **Start over completely:** `./dev.ps1 reset -Env pilot` (step 0) deletes all pilot data and keeps `.env.pilot`. Then continue from step 2.
- **Never** run `./dev.ps1 test` against pilot (it refuses), and never point `-Env test` at client companies.

## Change log

| Date | Version | Change |
| --- | --- | --- |
| 2026-10-12 | 0.3 | Second attempt: "entities not available" after a successful fetch. `connect -All`; companies stored and found by GUID; `entity-check`; progress lines and a `Result:` line; sync and validation reported separately. |
| 2026-10-12 | 0.2 | After the first attempt failed (MySQL 1205 lock wait on the connection): step 0 `reset -Env pilot`; `connect` before anything that could sync; new connections stay paused unless `-Activate`; `tally-companies` only reads; errors show type and a short message only. |
| 2026-10-12 | 0.1 | First version, prepared with M4: `init-env`, `connect`, `summary`, name-free CLI output outside test. Not yet run. |
