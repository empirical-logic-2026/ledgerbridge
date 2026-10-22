# Pilot runbook: loading the client's backup companies (M9)

| Field | Value |
| --- | --- |
| Version | 0.5 |
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

**The sync runs in the background, inside the api container.** `sync full` starts it, prints `Started sync job <id>`, then follows its progress until the `Result:` line. Closing the window, losing the terminal or pressing Ctrl+C **only stops the following, never the sync**. To follow it again, from any PowerShell window:

```powershell
./dev.ps1 sync watch -Env pilot
```

It prints the job's output from the start, then new lines as they come, and ends with `Sync job finished (exit N)`.

**If a run is stuck as running:**
- A sync that is stopped with Ctrl+C in its own process, or terminated, marks its run `interrupted` and keeps its checkpoints. The next `sync full` continues from there.
- A sync killed without warning (e.g. `./dev.ps1 down -Env pilot`, Docker stopping, or a crash) can't do that. Its run is detected automatically instead: once it has sent no heartbeat for 5 minutes (`SYNC_STALE_SEC`), the next sync or `status` marks it `interrupted`. Its checkpoints are kept too.
- **"already has a sync running" / "its run lock is held":** the refusal says which it found. A running run shows its id and last sign of life: follow it with `sync watch`. Only a lock means another process is starting a run; the lock expires within the time shown. A run's lock is tied to its heartbeat, so after a shutdown it lapses within about 90 seconds, and the stale-run check clears it as soon as the run is marked `interrupted`.
- **By hand:** `./dev.ps1 sync abandon -Env pilot` asks you to type `abandon`, then marks the connection's running runs `interrupted` and clears the connection's run lock. It leaves alone a run that still sends heartbeats, i.e. one that is really still running; add `-Force` only if you're sure it isn't. Never edit `sync_runs` in the database again.

Large companies take a while. Each company is fetched chunk by chunk (the company record, each master type, then vouchers month by month), and each chunk is stored as soon as it arrives. Every chunk prints a line:

```text
[10:42:01] entity 1 of 2: voucher 2023-04-01..2023-04-30: 812 received, 812 stored, 0 unchanged (chunk 14 of 96)
```

Each company is then transformed and validated **before the next one starts**, so a problem with one doesn't hold up the other.

**If Tally is slow or stops answering:**
- **A request takes longer than the timeout** (120 s by default). The sync doesn't resend it. It first checks with a tiny request whether Tally answers at all, and says so: `responsive, so the request was too large`, `slow, but responding`, or no answer. If there's no answer, Tally is probably **still busy with the request that timed out** (it works on one request at a time and finishes it even though the sync gave up on it). The sync says so, and keeps checking, after 10, 30, 90 s and then every 90 s, **for up to the connection's timeout** (e.g. 1800 s with `-TimeoutSec 1800`). When Tally answers it says how long it took to become free.
- **Tally answers:** the month is fetched in smaller parts (half-months, then weeks, then days). The month is then checked against Tally's own list of its vouchers, and remembered as slow, so later runs split it straight away.
- **Tally never answers within that time:** the run stops with `the source appears UNRESPONSIVE`. Everything fetched so far is stored. Restart TallyPrime if needed, then **run `./dev.ps1 sync full -Env pilot` again: it continues after the last completed chunk** (`resuming: N of M chunks were completed by an earlier attempt`).
- **To start over** instead: `./dev.ps1 sync full -Env pilot -Restart`.
- **Longer timeout:** `./dev.ps1 connect -Env pilot -Origin backup -All -TimeoutSec 600`.
- **Where the timeout comes from:** a connection uses **its own** timeout if one was ever set on it, otherwise `TALLY_TIMEOUT_SEC` from `.env.pilot`. Connections created before 2026-10-13 stored the 120 s default, so for them **changing `.env.pilot` has no effect**: use `connect -TimeoutSec`. `status` and `summary` show the timeout in effect and where it comes from.
- **Parts of a month:** TallyPrime in Educational mode can't answer requests for part of a month. The sync checks this once and remembers it, or you can set it with `connect -PartMonth unsupported`. When parts aren't supported, a slow month is never split. It is retried **whole** with longer timeouts (300, then 600, then 1200 s), with a 60 s pause before each attempt. If it still fails, the sync stops with a clear message.
- **Easing the load on Tally:** `connect -PauseSec 2` pauses 2 s between requests.
- **Nothing unverified counts as done:** a month that can't be proven complete (its listing is too slow, or it comes back empty while other months are full and Tally lists vouchers for it) **stops the sync**. It's recorded as UNVERIFIED (shown in `summary`) and fetched again on the next `sync full`.
- **Re-fetch from a date** (e.g. a damaged range): `./dev.ps1 sync full -Env pilot -From 2024-03-01`. This continues an interrupted full sync but fetches again every month from that date; earlier completed months are kept.

At the end each company gets a line that keeps fetched, stored and transformed apart, for example:

```text
entity 1 of 2: SUCCEEDED: fetched 128,227 in 96 chunks (40 done by an earlier attempt, 3 split); stored 128,227 new or changed, 0 unchanged; transformed 128,226, 0 failed
```

The run ends with one line such as:

```text
Result: full succeeded; deletion_check succeeded; validation passed
```

The sync and the validation are reported separately. A sync that fetched and transformed everything stays `succeeded` even if validation then fails or can't run (`validation failed`, with the reason on the line above).

### 6. See the results

```powershell
./dev.ps1 report -Env pilot            # verdict, sections, problems and next steps
./dev.ps1 report -Env pilot -Details   # every section expanded
./dev.ps1 summary -Env pilot
./dev.ps1 status -Env pilot
```

**`report` is the place to start.** At the top: **Overall: OK / ATTENTION NEEDED / FAILED** and the next step as an exact command. Then sections: connection, data loaded (records stored, converted, failed to convert), work in progress (a running job, an unfinished full sync or records waiting, each with its command), validation per company and warnings. Under *Problems and next steps* each problem shows where and how many, **What this means**, **Likely cause** (a root cause says how many other problems follow from it; a consequence names its root cause: fix that first) and **Next step**. Validation counts say whether they are better, worse or unchanged since the previous run. Status words are green, yellow or red when the terminal supports it (`-NoColor` turns colours off).

Each `report` also saves the full report as Markdown under `reports/pilot/report-<date>-<time>.md` (git-ignored). It holds counts, dates and codes only, never names, values or amounts: **share that file.**

**Every problem has a plain name and a stable code**, the same in every command, e.g. `Balances at year ends [year_end_mismatch, LB-VAL-006]`. [error-catalogue.md](error-catalogue.md) explains each code: what it means, common causes, how to investigate and how to fix it.

**Companies are always named the same way:** `entity <id> (company <n>)`, in sync progress, transform, validation, `status` and `summary`. `entity <id>` is the company's id in the database; `company <n>` is its number on the connection, given once (synced companies in the order first synced, then the configured ones) and kept: `connect` with the companies in another order doesn't change it. A company that hasn't been transformed yet shows as `company <n> (no entity yet)`, and the sync says when it becomes `entity <id> (company <n>)`.

`summary` shows for the connection the last sync and deletion check, plus any raw records that failed to transform:
- **why records failed to convert [LB-TRF-001]**, grouped by object type and kind of error, with counts and a short message without values (e.g. `ledger x2,170: DataError: MySQL 1406 too long: parties.phone (values up to 61 characters)`);
- records **converted with a note**, under one heading per kind: **Values kept aside (didn't fit their column) [LB-TRF-003]** (e.g. `voucher x12: too long: vouchers.voucher_number (length 300, column allows 255)`; the full value is kept), **References matched flexibly [LB-TRF-004]** (after normalisation or by alias) and **Ambiguous references left empty [LB-TRF-005]**.

For each company (`entity <id> (company <n>)`) it shows:
- counts of ledgers (and how many are unmapped), parties, vouchers (cancelled, deleted in source) and effective voucher lines
- how many fields with no column were found (e.g. Tally UDFs), by prefix (`fields with no column, kept in extra: 15 (by prefix: UDF 3, none 12)`)
- the latest validation, PASSED or FAILED, with each problem's plain name, code and count, compared with the previous run

It also lists open alerts. **This is the output to share.**

If Tally's data has **custom fields** (TDL customisations export them with prefixes such as `UDF:`), `summary` shows the prefix names, e.g. `XML prefixes seen in the source's data: UDF`. Each record keeps them (`extra`), and they are counted in a field catalogue: `./dev.ps1 fields -Env pilot` lists them by id, object type, prefix, kind and number of records (field names only in the test environment). A voucher field useful for reports can become a reporting dimension: `./dev.ps1 promote-field -Env pilot -FieldId <id> -Code SALESMAN -Name "Salesman"`.

### 7. Records that failed to transform: `transform explain`, `retry`, `rebuild`

**First, find out why references didn't resolve** (no names or values in the output):

```powershell
./dev.ps1 transform explain -Env pilot                # reads only the database
./dev.ps1 transform explain -Env pilot -CheckSource   # also asks Tally (read-only): have the companies loaded
```

For each kind of reference (ledger → group, voucher → ledger, cost centre, stock item, voucher type) it says how many failed records there are and, per name that didn't resolve:
- whether it **resolves now** (by alias, or after normalisation, with the kinds of difference: spaces, case, XML entities, Unicode): a `rebuild` then fixes those records;
- whether it matches **several** targets (ambiguous);
- otherwise whether a **close match** exists (look-alike characters, punctuation, other small differences), whether it is a **Tally reserved name**, and whether the referenced object is **stored** at all (or failed itself);
- with `-CheckSource`: whether Tally **lists** it now, and per master type how many objects Tally lists against how many are stored (`listed but not stored` above 0 means our requests missed some).

Share that output as it is.

Raw records are kept exactly as Tally sent them, so records that failed to transform (e.g. with older code) can be transformed again **without Tally**:

```powershell
./dev.ps1 transform retry -Env pilot                         # every company
./dev.ps1 transform retry -Env pilot -Company "<exact name>" # one company
```

To transform **every** stored record again with the current code (records transformed by older code then get the new `extra` fields and field catalogue too), use `rebuild`, also without Tally:

```powershell
./dev.ps1 transform rebuild -Env pilot                         # every company
./dev.ps1 transform rebuild -Env pilot -Company "<exact name>" # one company
```

Each object is rebuilt from its latest raw record, rows are updated in place (no duplicates), a voucher's lines are replaced, and objects deleted in Tally stay deleted. `retry` and `rebuild` both run in the background like a sync (follow them again with `./dev.ps1 sync watch -Env pilot`), prints progress per object type every 10,000 records, and ends with a `Result:` line. Afterwards it **validates** the companies it touched, which reads Tally's own figures: have TallyPrime running with the companies loaded, or add `-NoValidate` and run `./dev.ps1 validate -Env pilot` later.

**One bad value no longer fails a batch:** a value too long for its column (or out of range, an invalid date, invalid characters) is kept in full in the record's `extra` and reported as a warning in `summary`. Only a record whose amounts, quantities or date can't be stored at all fails, alone, and `summary` says why.

**Validation proves more** (in `validate`, full syncs and `transform retry`): besides voucher balance, trial balance and closing balances, it compares with Tally the number of vouchers per month and voucher type, each stock item's closing quantity, each party's bill-wise outstanding (as of today), and every ledger's balance at each financial year end. `./dev.ps1 validate -Env pilot -Quick` skips these extra comparisons.

When records failed to transform, the validation output starts the explanation with the **root cause**, e.g.:

```text
  ROOT CAUSE: 1,016 ledgers in the source are missing here (2,170 ledger records failed to transform)
  ROOT CAUSE: 238,392 vouchers failed to transform because they refer to a ledger that is missing
  ROOT CAUSE: 884 other failures (closing_mismatch 877, tb_unbalanced 7) are likely consequences: ...
```

Fix the root cause first (share the `summary` breakdown), then run `transform retry`.

### 8. Why validation still differs: `validate analyse`

When every record transformed but validation still finds mismatches, analyse them (reads Tally's own figures, read-only: have the companies loaded):

```powershell
./dev.ps1 validate analyse -Env pilot                          # every company
./dev.ps1 validate analyse -Env pilot -Company "<exact name>"  # one company
```

It runs in the background like a sync (follow it again with `./dev.ps1 sync watch -Env pilot`) and prints, per company, counts and patterns only:
- **ledgers that differ today**, and how many each explanation fits: the opening balance missing or counted twice, a reversed sign, one voucher type's lines counted here but not by Tally (or the other way round, for cancelled, optional, deleted or non-posting vouchers), post-dated vouchers, Tally restarting income and expense ledgers each financial year, and the first year end where each ledger differs; unexplained ones by primary group (Tally's reserved names only);
- **each year end**: how many ledgers differ and what explains them;
- **the profit carrier**, **unbalanced vouchers** (by voucher type and pattern: rounding, foreign currency, a reversed sign, a single line, on-account bills, inventory lines), **trial balance** dates, **bills** and **stock quantities** (each voucher type, opening quantity, physical stock, alternate or compound units, several godowns or batches);
- **stored vouchers by type**: how many, whether stock vouchers have inventory lines here, and what their content holds that isn't read yet (Tally's tag names).

Share the output as it is. It also shows: pairs of explanations that fit only together; the differing ledgers by primary group, split into those the opening explains, those with a non-zero stored opening and those with none; and, for ledgers nothing explains, the first month end of the first financial year where they differ (it reads Tally's balance at each month end of that year) with the voucher types that have lines that month.

**Ledger profiles** (end of `validate analyse`): each ledger that differs today or at a year end, as ledger A, B, ...: its primary group, a renamed reserved group above it (e.g. Stock-in-Hand), whether it sits directly under its primary group, its kind and nature, whether our stored opening equals Tally's, the voucher types posting to it, at which year ends it differs and whether by the same amount, the voucher types around a year end where it differs only sometimes, vouchers whose effective date isn't their date, and what the difference equals (its opening, the stock items' opening value, Tally's opening minus ours, the closing stock value minus its opening at every date, one month's lines of a voucher type around a year end, its opening bills minus its opening). It also says whether the ledger already differs on the books' first day and how many optional, cancelled, post-dated, reversing and memorandum vouchers post to it. After the profiles, **Opening difference** says what Tally's own difference equals (the stock ledgers' openings, the opening stock value, ...). No names or amounts.

**Educational mode.** TallyPrime in Educational mode gives correct balances only on the 1st, 2nd and 31st of a month. Validation then runs as of the latest such date (e.g. the 2nd when you run it on the 15th), year ends on the 30th move to the 1st of the next month, and `validate analyse` prints `Dates used: ...` with the reason. Tally is asked whether it is in Educational mode; if it doesn't say, set it on the connection: `./dev.ps1 connect -Env pilot -Origin backup -All -Educational yes`. The settings line of `status`/`summary` shows `Educational mode: auto|yes|no`.

**Stock ledgers and the opening difference.** When Tally reports a Stock-in-Hand ledger at its closing stock value, validation compares it with that value and notes it (`Stock ledgers at the stock value [stock_ledger_at_stock_value, LB-VAL-021]`). The opening difference warning follows Tally's own trial balance from the books' beginning. `validate analyse` narrows down when a ledger starts to differ and matches again, and counts the vouchers then; effective dates appear after `transform rebuild`.

**Which ledger a line is on.** `validate analyse` says, for a ledger that starts to differ, which lines of any voucher then equal the difference, on what kind of ledger we put them and how the name was matched; whether two ledgers' differences cancel out; how many stored vouchers name the ledger, and ledger lines in lists the mapping doesn't read. After a change to how names are resolved, run `transform rebuild`.

**Foreign-currency ledgers.** Tally reports them at current exchange rates; validation compares them with Tally's book value (the amounts entered, as Ledger Vouchers show them) and notes it (`Foreign-currency ledgers at book value [foreign_ledgers_at_book_value, LB-VAL-022]`). Foreign amounts on lines appear after `transform rebuild`.

**One ledger, voucher by voucher.** `./dev.ps1 validate compare-ledger -Env pilot -Ledger <id> [-From YYYY-MM-DD] [-To YYYY-MM-DD]` reads that ledger's vouchers from Tally (read-only) and compares them with ours. It prints counts by voucher type and month and kinds only, and writes the details (dates, voucher numbers, both amounts) to `reports/pilot/private/compare-ledger-<id>-<time>.tsv` for you to check in Tally: local, git-ignored, never share it.

**Three statements, line by line.** Re-run full validation for every configured company with Tally's reports:

```powershell
./dev.ps1 validate -Env pilot
./dev.ps1 validate compare-statements -Env pilot
./dev.ps1 validate compare-statements -Env pilot -AsOf 2026-10-02
```

The comparison covers the Trial Balance, Balance Sheet and Profit & Loss as of the requested date (default today, moved to a reliable date if Tally requires it). It reports line counts and equal/different/unmatched totals only. Labels and amounts are written to `reports/pilot/private/compare-statements-<time>.tsv` for local inspection; do not share that file. The source reports are read-only and are retained separately from our canonical statement lines.

### 9. After a change to how data is fetched: `sync full -Restart`

`transform rebuild` re-applies changed rules to what is stored. When a fix needs fields that weren't fetched before (for example opening balances as at the books' beginning, or tracking numbers on inventory lines; schema.md 7.5), the stored records don't have them: fetch everything again with `./dev.ps1 sync full -Env pilot -Restart`. It takes as long as the first full sync, resumes if interrupted, transforms with the current rules and validates thoroughly; no rebuild is needed afterwards.

## Reading the results

Problems print as `<plain name> [<technical key>, <code>]: <count> (<better, was N | worse, was N | unchanged | fixed, was N | first result>)`. [error-catalogue.md](error-catalogue.md) lists every code. The table below covers other lines; validation lines are named by their key, e.g. `year_end_mismatch` is *Balances at year ends [LB-VAL-006]*.

| Line | Meaning | What to do |
| --- | --- | --- |
| `Overall: FAILED` / `ATTENTION NEEDED` / `OK` (in `report` and every `Result:` line) | Whether anything failed, needs attention, or nothing. | Follow `Next step:`; share the saved report. |
| `Sync run N (full): succeeded`, `failed: 0` | Everything was read and transformed. | – |
| `Records that failed to convert [records_failed, LB-TRF-001]: N` (N > 0) | Some Tally objects couldn't be mapped or stored. | Share the `summary` lines under *why raw records failed* (counts and kinds, no values). After a fix: `./dev.ps1 transform retry -Env pilot`. |
| `converted with a note: Values kept aside (didn't fit their column) [values_kept_in_extra, LB-TRF-003] N` | Records transformed, with some values kept aside in full (too long, out of range, invalid date). | Share the `report` (its details group them). |
| `ROOT CAUSE: ...` (validation) | Records failed to transform; the other failures counted there are likely their consequences. | Fix the root cause first, then `transform retry`. |
| `Vouchers that don't balance [voucher_unbalanced, LB-VAL-001] by voucher type: Sales N, custom (other) N` | Unbalanced vouchers by Tally's predefined voucher type they derive from (`custom (...)` when it can't be told). The line before says how many have inventory lines, a single line or are post-dated. | Share both lines. |
| `References matched flexibly [reference_matched_flexibly, LB-TRF-004]`: `reference matched after normalisation: voucher -> ledger` | References that resolved only after normalisation (e.g. case or spaces). | Expected; share the count. |
| `error: voucher_count_mismatch xN` | N (month, voucher type) pairs where the number of vouchers differs from Tally's. | Share the count. Usually follows vouchers that failed to transform. |
| `error: stock_quantity_mismatch xN` | N stock items whose closing quantity differs from Tally's. | Share the count. |
| `error: bills_mismatch xN` | N parties whose bill-wise outstanding differs from Tally's. | Share the count. |
| `error: year_end_mismatch xN` | Ledger balances that differ from Tally's at a financial year end. | Share the count. |
| `error: voucher_counts_unavailable` (or `stock_quantities_`, `bill_outstanding_`, `year_end_balances_`) | Tally couldn't provide those figures (e.g. timed out). | Share the line; `validate -Env pilot` again later. |
| `note: stock_values_not_compared` | Stock values per item depend on Tally's valuation method and aren't compared item by item. | Expected. |
| `Ledgers without a standard account [unmapped_ledgers, LB-TRF-008] ...: N` | Ledgers without a standard account (e.g. under *Indirect Expenses*), by design. Reports will place them under the nearest standard parent account (M6). | Expected. Share the count. |
| `Mapping assumptions [mapping_assumptions, LB-TRF-007]: N` | GST ledgers whose duty head Tally left empty, assumed to be Central Tax (schema.md 7.3, an assumption to verify). | Check in TallyPrime that the company's Central Tax (CGST) ledgers number N. Report "matches" or "doesn't match". |
| `Validation of entity N (company N) as of ...: PASSED` | All checks passed. | – |
| `unfinished full sync of entity N: K chunks done` (in `summary`) | A full sync was interrupted. | Run `./dev.ps1 sync full -Env pilot` again to continue it. |
| `raw records by type and status: voucher pending N` (in `summary`) | Records stored but not yet transformed, e.g. after an interrupted sync. | They're transformed when that company's sync completes. |
| `UNVERIFIED voucher 2024-03-01..2024-03-31` (in `summary`), `UnverifiedChunkError` | A month couldn't be proven complete; the sync stopped rather than count it as done. | Run `./dev.ps1 sync full -Env pilot` again: it fetches that month again. If it keeps happening, raise the timeout (`connect -TimeoutSec`). |
| `ChunkTooSlowError: ... no answer within 1200 s even as a whole` | Even the whole month with the longest timeout didn't arrive. | Restart TallyPrime, close other programs, then run `sync full` again (it resumes). |
| `IncompleteChunkError` | A month fetched in parts didn't contain everything Tally lists for it (Tally may not answer requests for parts of a month). | Share the line; raise the timeout (`-TimeoutSec`) so whole months fit. |
| `EntityLookupError: N of M configured entities are not available in the source` | Tally doesn't list a configured company (by GUID). | Check that both companies are loaded; run `./dev.ps1 entity-check -Env pilot` and share its output. |
| `error: voucher_unbalanced xN` | N vouchers whose lines don't sum to zero after transformation. | Share the count. |
| `error: tb_unbalanced xN` | The trial balance doesn't balance at a year end or today. | Share the count; usually follows another error. |
| `error: closing_mismatch xN` | N ledgers whose balance differs from Tally's. | Share the count. |
| `error: ledger_missing xN` | Ledgers in Tally but not synced, or the other way round. | Share the count; re-run step 5 once. |
| `error: profit_carrier_mismatch x1` | *Profit & Loss A/c* doesn't reconcile with the computed profit. Known points to check: books spanning several financial years, and companies that keep stock without integrated inventory (schema.md 10). | Share it, plus how many financial years the books cover and whether inventory is maintained. |
| `error: <ErrorType>: <short message> [LB-SYS-001]` from any command | Something failed unexpectedly. Outside the test environment you see only the error type and a short message (for database errors, the MySQL code), never SQL or values. | Share that line as it is. |
| `error: closing_unavailable` | Tally couldn't be reached for closing balances. | Check that TallyPrime is running with both companies loaded; run `./dev.ps1 validate -Env pilot`. |
| `warning: opening_difference x1` | The company's opening balances don't total zero (Tally's "Difference in opening balances"). Not a sync error. | Note it. The fix belongs in the client's books. |

## Afterwards

- **Validate again** (e.g. after reloading Tally): `./dev.ps1 validate -Env pilot`.
- **Transform failed records again** (no Tally needed): `./dev.ps1 transform retry -Env pilot` (step 7).
- **Reload a newer backup:** restore it in TallyPrime, then `./dev.ps1 sync full -Env pilot`. Changes are picked up by AlterID, and deletions by the deletion check.
- **Stop:** `./dev.ps1 down -Env pilot`. The data stays in the pilot volumes.
- **Start over completely:** `./dev.ps1 reset -Env pilot` (step 0) deletes all pilot data and keeps `.env.pilot`. Then continue from step 2.
- **Never** run `./dev.ps1 test` against pilot (it refuses), and never point `-Env test` at client companies.

## Change log

| Date | Version | Change |
| --- | --- | --- |
| 2026-10-22 | 0.22 | Document full validation and the three-statement source comparison, including private line-level details. |
| 2026-10-16 | 0.21 | `validate compare-ledger`; foreign-currency ledgers one by one. |
| 2026-10-16 | 0.20 | Foreign-currency ledgers at book value. |
| 2026-10-16 | 0.19 | Line attribution in `validate analyse`; `transform rebuild` after the name resolution change. |
| 2026-10-15 | 0.18 | Stock ledgers at the stock value; the opening difference as Tally's trial balance shows it; company numbers kept across `connect`; narrowed dates in `validate analyse`. |
| 2026-10-15 | 0.17 | Educational mode: validation and analysis use reliable dates only; `connect -Educational`. |
| 2026-10-15 | 0.16 | More facts in the ledger profiles; what the opening difference equals. |
| 2026-10-15 | 0.15 | Ledger profiles in `validate analyse`; the opening difference leaves out Stock-in-Hand ledgers in integrated companies. |
| 2026-10-15 | 0.14 | Job work godowns, stock journals read once and the source's own opening difference: after this release run `sync full -Restart` (godown flags are new fields); `validate analyse` compares stock by godown and lists job work. |
| 2026-10-15 | 0.13 | Refusals say whether a running run or only a run lock was found; the lock lapses after a shutdown and `sync abandon` clears it; `report`'s next step puts unfinished work first. |
| 2026-10-14 | 0.12 | Step 9: `sync full -Restart` after a fix that needs fields not fetched before (openings at the books' beginning, tracking numbers); step 8: pairs, primary groups, first month. |
| 2026-10-14 | 0.11 | `report` (step 6): verdict, sections, problems with meaning, cause and next step, saved as Markdown; plain names and stable codes everywhere ([error-catalogue.md](error-catalogue.md)); validation compared with the previous run. |
| 2026-10-14 | 0.10 | `validate analyse` (step 8); stock journal entries read; orders and memorandum don't move stock; foreign currency amounts in the base currency; `watch` follows jobs that are busy without printing. |
| 2026-10-13 | 0.9 | `transform explain` (step 7) for references that don't resolve; references resolve by alias and normalisation; vouchers of types that don't post to the books no longer count in balances; unbalanced vouchers by Tally's predefined type. |
| 2026-10-13 | 0.8 | `transform rebuild` (every stored record again, without Tally); `retry` and `rebuild` never apply an older version of an object over a newer one. |
| 2026-10-13 | 0.7 | After the fifth attempt (2,170 ledgers and 238,392 vouchers failed, "Transform batch failed: DataError"): `transform retry` (step 7); one way to name companies (`entity <id> (company <n>)`); failure and warning breakdowns in `summary`; values that don't fit kept in `extra`; field catalogue (`fields`, `promote-field`); validation compares voucher counts, stock quantities, bills and year-end balances, and names the root cause. |
| 2026-10-13 | 0.6 | Fifth attempt (unbound `UDF:` prefix; Tally still busy after a timeout; terminal lost mid-run; Ctrl+C left a run running): custom-field prefixes parsed and shown in `summary`; source checks wait up to the timeout; syncs run in the background, `sync watch`; `interrupted` runs, stale-run detection, `sync abandon`. |
| 2026-10-13 | 0.5 | Fourth attempt (Educational mode, part-month requests empty, unverified month carried on): timeout in effect and its source in `status`/`summary`; `connect -TimeoutSec/-PauseSec/-PartMonth`; whole-month retries; unverified months stop the sync and are re-fetched; `sync full -From`. |
| 2026-10-12 | 0.4 | Third attempt (Tally stopped answering after 18 minutes): chunked and resumable `sync full` (`-Restart` to start over), source checks and splitting after a timeout, `-TimeoutSec`, per-company progress and results, `summary` shows raw-record status and unfinished syncs. Data stored by the third attempt is kept and reused. |
| 2026-10-12 | 0.3 | Second attempt: "entities not available" after a successful fetch. `connect -All`; companies stored and found by GUID; `entity-check`; progress lines and a `Result:` line; sync and validation reported separately. |
| 2026-10-12 | 0.2 | After the first attempt failed (MySQL 1205 lock wait on the connection): step 0 `reset -Env pilot`; `connect` before anything that could sync; new connections stay paused unless `-Activate`; `tally-companies` only reads; errors show type and a short message only. |
| 2026-10-12 | 0.1 | First version, prepared with M4: `init-env`, `connect`, `summary`, name-free CLI output outside test. Not yet run. |
