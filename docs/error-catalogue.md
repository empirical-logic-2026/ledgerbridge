# Error catalogue

Every error and warning LedgerBridge reports has a stable code. Commands print the plain
name first, then the technical key and the code in brackets, for example
`Balances at year ends [year_end_mismatch, LB-VAL-006]`. Codes are never reused or
renumbered.

**Generated** from `data-plane/core/problems.py` by `python -m devtools.error_catalogue`
(also run by `./dev.ps1 diagrams`); don't edit this file by hand. A test fails when it is
out of date.

- **Error** (red, FAILED): something is wrong or missing; the overall verdict is FAILED.
- **Warning** (yellow, WARNING): needs attention; the overall verdict is ATTENTION NEEDED.
- **Note**: for information; doesn't change the verdict.

Start with `.\dev.ps1 report -Env <env>`: it shows the overall verdict, every problem
found with its code, and the next step. **Consequences** name the problems they usually
follow from: when those are found too, fix them first.

Commands below use `-Env <env>`: `test` or `pilot`. Everything printed is counts, dates,
codes and labels such as `entity 3 (company 1)`: never names, values or amounts.

| Code | Name | Key | Severity |
| --- | --- | --- | --- |
| [LB-SYNC-001](#lb-sync-001-last-sync-failed) | Last sync failed | `sync_failed` | Error |
| [LB-SYNC-002](#lb-sync-002-unfinished-full-sync) | Unfinished full sync | `full_sync_unfinished` | Warning |
| [LB-SYNC-003](#lb-sync-003-last-deletion-check-failed) | Last deletion check failed | `deletion_check_failed` | Warning |
| [LB-SYNC-004](#lb-sync-004-periods-not-verified) | Periods not verified | `unverified_range` | Warning |
| [LB-SYNC-005](#lb-sync-005-the-source-didnt-answer) | The source didn't answer | `source_unresponsive` | Error |
| [LB-SYNC-006](#lb-sync-006-companies-not-found-in-the-source) | Companies not found in the source | `entity_not_found` | Error |
| [LB-SYNC-007](#lb-sync-007-sync-in-progress) | Sync in progress | `sync_running` | Note |
| [LB-SYNC-008](#lb-sync-008-a-sync-is-already-running) | A sync is already running | `sync_busy` | Warning |
| [LB-SYNC-009](#lb-sync-009-never-synced) | Never synced | `never_synced` | Warning |
| [LB-SYNC-010](#lb-sync-010-last-sync-interrupted) | Last sync interrupted | `sync_interrupted` | Warning |
| [LB-TRF-001](#lb-trf-001-records-that-failed-to-convert) | Records that failed to convert | `records_failed` | Error |
| [LB-TRF-002](#lb-trf-002-records-not-converted-yet) | Records not converted yet | `records_pending` | Warning |
| [LB-TRF-003](#lb-trf-003-values-kept-aside-didnt-fit-their-column) | Values kept aside (didn't fit their column) | `values_kept_in_extra` | Note |
| [LB-TRF-004](#lb-trf-004-references-matched-flexibly) | References matched flexibly | `reference_matched_flexibly` | Note |
| [LB-TRF-005](#lb-trf-005-ambiguous-references-left-empty) | Ambiguous references left empty | `reference_ambiguous` | Warning |
| [LB-TRF-006](#lb-trf-006-fields-with-no-column) | Fields with no column | `fields_without_column` | Note |
| [LB-TRF-007](#lb-trf-007-mapping-assumptions) | Mapping assumptions | `mapping_assumptions` | Note |
| [LB-TRF-008](#lb-trf-008-ledgers-without-a-standard-account) | Ledgers without a standard account | `unmapped_ledgers` | Note |
| [LB-TRF-009](#lb-trf-009-custom-fields-in-the-sources-data) | Custom fields in the source's data | `custom_xml_prefixes` | Note |
| [LB-VAL-001](#lb-val-001-vouchers-that-dont-balance) | Vouchers that don't balance | `voucher_unbalanced` | Error |
| [LB-VAL-002](#lb-val-002-trial-balance-doesnt-balance) | Trial balance doesn't balance | `tb_unbalanced` | Error |
| [LB-VAL-003](#lb-val-003-opening-balances-dont-total-zero) | Opening balances don't total zero | `opening_difference` | Warning |
| [LB-VAL-004](#lb-val-004-ledger-balances-today) | Ledger balances today | `closing_mismatch` | Error |
| [LB-VAL-005](#lb-val-005-profit-and-loss-balance) | Profit and loss balance | `profit_carrier_mismatch` | Error |
| [LB-VAL-006](#lb-val-006-balances-at-year-ends) | Balances at year ends | `year_end_mismatch` | Error |
| [LB-VAL-007](#lb-val-007-ledgers-missing-here) | Ledgers missing here | `ledger_missing` | Error |
| [LB-VAL-008](#lb-val-008-voucher-counts-per-month) | Voucher counts per month | `voucher_count_mismatch` | Error |
| [LB-VAL-009](#lb-val-009-stock-quantities) | Stock quantities | `stock_quantity_mismatch` | Error |
| [LB-VAL-010](#lb-val-010-bill-wise-outstanding) | Bill-wise outstanding | `bills_mismatch` | Error |
| [LB-VAL-011](#lb-val-011-source-balances-couldnt-be-read) | Source balances couldn't be read | `closing_unavailable` | Error |
| [LB-VAL-012](#lb-val-012-source-year-end-balances-couldnt-be-read) | Source year-end balances couldn't be read | `year_end_balances_unavailable` | Error |
| [LB-VAL-013](#lb-val-013-source-voucher-counts-couldnt-be-read) | Source voucher counts couldn't be read | `voucher_counts_unavailable` | Error |
| [LB-VAL-014](#lb-val-014-source-stock-quantities-couldnt-be-read) | Source stock quantities couldn't be read | `stock_quantities_unavailable` | Error |
| [LB-VAL-015](#lb-val-015-source-bills-couldnt-be-read) | Source bills couldn't be read | `bill_outstanding_unavailable` | Error |
| [LB-VAL-016](#lb-val-016-check-not-offered-by-the-source) | Check not offered by the source | `check_not_supported` | Note |
| [LB-VAL-017](#lb-val-017-compared-only-in-total) | Compared only in total | `not_compared` | Note |
| [LB-VAL-018](#lb-val-018-quick-validation) | Quick validation | `source_controls_not_checked` | Note |
| [LB-VAL-019](#lb-val-019-not-validated-yet) | Not validated yet | `never_validated` | Warning |
| [LB-VAL-020](#lb-val-020-validation-couldnt-run) | Validation couldn't run | `validation_error` | Error |
| [LB-CON-001](#lb-con-001-no-connection-yet) | No connection yet | `no_connection` | Warning |
| [LB-CON-002](#lb-con-002-scheduled-syncs-paused) | Scheduled syncs paused | `connection_paused` | Note |
| [LB-SYS-001](#lb-sys-001-unexpected-error) | Unexpected error | `unexpected_error` | Error |
| [LB-SYS-002](#lb-sys-002-background-job-stopped-without-finishing) | Background job stopped without finishing | `job_gone` | Error |
| [LB-SYS-003](#lb-sys-003-database-busy-or-unavailable) | Database busy or unavailable | `database_unavailable` | Error |

## Sync: fetching from the source

### LB-SYNC-001: Last sync failed

`sync_failed` | Error

**What it means:** The last sync stopped with an error, so recent changes in the source may be missing.

**Common causes:**

- The source stopped answering or answered with an error.
- A database error while storing records.

**How to investigate:**

- Run the report with -Details: it shows the error's type (never values).
- Check that the source (TallyPrime) is open with the companies loaded.

**How to fix:**

- Fix the cause, then sync again: an interrupted full sync continues where it stopped.

**Next step:** `.\dev.ps1 sync -Env <env>`

### LB-SYNC-002: Unfinished full sync

`full_sync_unfinished` | Warning

**What it means:** A full sync stopped part way. What it fetched is kept; the rest isn't fetched yet.

**Common causes:**

- The window was closed, the computer slept or the source stopped answering.
- The job was stopped (sync abandon or a restart of the stack).

**How to investigate:**

- The report shows how many parts are done and since when.

**How to fix:**

- Run the full sync again: it continues from the last completed part.

**Next step:** `.\dev.ps1 sync full -Env <env>`

### LB-SYNC-003: Last deletion check failed

`deletion_check_failed` | Warning

**What it means:** The check for records deleted in the source didn't finish, so deleted records may still count here.

**Common causes:**

- The source stopped answering or listed fewer records than expected.

**How to investigate:**

- Run the report with -Details for the error's type.

**How to fix:**

- Run the deletion check again once the source answers.

**Next step:** `.\dev.ps1 sync deletions -Env <env>`

### LB-SYNC-004: Periods not verified

`unverified_range` | Warning

**What it means:** For some periods the source's answer couldn't be confirmed complete, so records from those periods may be missing.

**Usually a consequence of:** LB-SYNC-005.

**Common causes:**

- The source timed out on a large period even after splitting it.
- The source returned fewer records than it listed.

**How to investigate:**

- The report lists the object types and periods (dates only).

**How to fix:**

- Run a full sync again (fetches unverified periods again); raise the request timeout with connect -TimeoutSec if they time out.

**Next step:** `.\dev.ps1 sync full -Env <env>`

### LB-SYNC-005: The source didn't answer

`source_unresponsive` | Error

**What it means:** The source (TallyPrime) didn't answer in time or refused the connection.

**Common causes:**

- TallyPrime is closed, busy (a report or dialog open) or the company isn't loaded.
- The request timeout is too short for a large company.

**How to investigate:**

- Check that TallyPrime is open, idle and has the companies loaded.
- .\dev.ps1 entity-check -Env <env> shows whether the companies are found.

**How to fix:**

- Leave TallyPrime idle and sync again; raise the timeout with connect -TimeoutSec.

**Next step:** `.\dev.ps1 entity-check -Env <env>`

### LB-SYNC-006: Companies not found in the source

`entity_not_found` | Error

**What it means:** Some configured companies aren't loaded in the source, so they weren't synced.

**Common causes:**

- The company isn't open in TallyPrime.
- The company's name or identity changed in the source.

**How to investigate:**

- .\dev.ps1 entity-check -Env <env> shows the kinds of difference (never names).

**How to fix:**

- Load the companies in TallyPrime, or connect again with their exact names.

**Next step:** `.\dev.ps1 entity-check -Env <env>`

### LB-SYNC-007: Sync in progress

`sync_running` | Note

**What it means:** A sync or another background job is running now.

**Common causes:**

- A sync you started, or the worker's scheduled sync.

**How to investigate:**

- Follow it to see its progress.

**How to fix:**

- Wait for it to finish; closing the window doesn't stop it.

**Next step:** `.\dev.ps1 sync watch -Env <env>`

### LB-SYNC-008: A sync is already running

`sync_busy` | Warning

**What it means:** This command needs the connection, but another run of it is in progress. The message says which was found: a running run (its id and last sign of life) or only the connection's run lock (and when it expires).

**Common causes:**

- The worker started a scheduled sync, or another window started one.
- Only a lock: another process is starting a run right now.

**How to investigate:**

- .\dev.ps1 status -Env <env> shows the running run.

**How to fix:**

- Wait for it, then run the command again. A run whose process is gone is marked interrupted after a few minutes without a sign of life, and its lock is cleared; sync abandon does both at once.

**Next step:** `.\dev.ps1 sync watch -Env <env>`

### LB-SYNC-009: Never synced

`never_synced` | Warning

**What it means:** This connection has no sync yet, so there is no data.

**Common causes:**

- The connection was just created.

**How to investigate:**

- .\dev.ps1 status -Env <env>

**How to fix:**

- Run a full sync.

**Next step:** `.\dev.ps1 sync full -Env <env>`

### LB-SYNC-010: Last sync interrupted

`sync_interrupted` | Warning

**What it means:** The last sync was interrupted before it finished; its progress is kept.

**Common causes:**

- The window or stack was stopped, or the process was gone (sync abandon).

**How to investigate:**

- The report shows any unfinished full sync and its progress.

**How to fix:**

- Run the sync again: it continues where it stopped.

**Next step:** `.\dev.ps1 sync -Env <env>`


## Transform: converting stored records into the accounting tables

### LB-TRF-001: Records that failed to convert

`records_failed` | Error

**What it means:** Some stored records couldn't be converted into the accounting tables, so they are missing from balances, counts and reports.

**Common causes:**

- A reference to a record that is missing (e.g. a voucher's ledger failed itself).
- A value the rules don't handle yet (e.g. an unusual amount or date format).

**How to investigate:**

- Run the report with -Details: failures are grouped by kind of record and error (no values).
- .\dev.ps1 transform explain -Env <env> explains references that didn't resolve.

**How to fix:**

- Fix the rule (a code change), then convert the failed records again: transform retry.

**Next step:** `.\dev.ps1 transform explain -Env <env>`

### LB-TRF-002: Records not converted yet

`records_pending` | Warning

**What it means:** Some stored records are still waiting to be converted.

**Usually a consequence of:** LB-SYNC-002, LB-SYNC-010.

**Common causes:**

- A sync or transform job was interrupted, or is still running.

**How to investigate:**

- Check work in progress in the report.

**How to fix:**

- Convert them: transform retry (doesn't contact the source). If a full sync is unfinished, resume it instead: it converts them.

**Next step:** `.\dev.ps1 transform retry -Env <env>`

### LB-TRF-003: Values kept aside (didn't fit their column)

`values_kept_in_extra` | Note

**What it means:** Some values were longer or larger than their column. The record is kept, the full value is in its `extra` column and the column holds a shortened copy.

**Common causes:**

- The source allows longer texts than the column (e.g. long narrations).

**How to investigate:**

- Run the report with -Details for the columns affected and the largest size seen.

**How to fix:**

- Nothing needed unless reports must show the full value; widen the column with a migration if so.

**Next step:** `.\dev.ps1 report -Env <env> -Details`

### LB-TRF-004: References matched flexibly

`reference_matched_flexibly` | Note

**What it means:** Some references by name matched only after allowing for differences in spacing, case or punctuation, or through an alias.

**Common causes:**

- The source stores a name slightly differently where it is used than where it is defined.

**How to investigate:**

- Run the report with -Details for counts by kind of match.

**How to fix:**

- Nothing needed: these records are converted. Review if numbers look wrong.

**Next step:** `.\dev.ps1 report -Env <env> -Details`

### LB-TRF-005: Ambiguous references left empty

`reference_ambiguous` | Warning

**What it means:** Some references by name matched more than one record, so they were left empty.

**Common causes:**

- Two records with names that differ only in spacing, case or punctuation.

**How to investigate:**

- .\dev.ps1 transform explain -Env <env>

**How to fix:**

- Rename one of the look-alike records in the source, sync, then transform retry.

**Next step:** `.\dev.ps1 transform explain -Env <env>`

### LB-TRF-006: Fields with no column

`fields_without_column` | Note

**What it means:** The source has fields with no column here (e.g. Tally user-defined fields). They are kept in `extra` and listed in the field catalogue.

**Common causes:**

- Customisations in the source (TDL, UDFs).

**How to investigate:**

- .\dev.ps1 fields -Env <env>

**How to fix:**

- Promote a field to a reporting dimension if it is needed: promote-field.

**Next step:** `.\dev.ps1 fields -Env <env>`

### LB-TRF-007: Mapping assumptions

`mapping_assumptions` | Note

**What it means:** Some records were converted with an assumption (e.g. a GST ledger with no duty head taken as Central Tax).

**Common causes:**

- The source left a field empty that the mapping needs.

**How to investigate:**

- docs/pilot-runbook.md explains each assumption and how to check it in the source.

**How to fix:**

- Check the count in the source; report whether it matches.

**Next step:** `.\dev.ps1 summary -Env <env>`

### LB-TRF-008: Ledgers without a standard account

`unmapped_ledgers` | Note

**What it means:** Some ledgers have no standard account. Reports place them under the nearest standard parent account.

**Common causes:**

- Ledgers under custom groups, by design.

**How to investigate:**

- The report shows the count per company.

**How to fix:**

- Nothing needed now (mapping review comes with the reports milestone).

**Next step:** `.\dev.ps1 report -Env <env>`

### LB-TRF-009: Custom fields in the source's data

`custom_xml_prefixes` | Note

**What it means:** The source's data contains fields from customisations (XML prefixes such as UDF). They are stored unchanged.

**Common causes:**

- TDL customisations or user-defined fields in the source.

**How to investigate:**

- .\dev.ps1 fields -Env <env>

**How to fix:**

- Nothing needed; promote a field if reports need it.

**Next step:** `.\dev.ps1 fields -Env <env>`


## Validation: our figures against the source's

### LB-VAL-001: Vouchers that don't balance

`voucher_unbalanced` | Error

**What it means:** Some vouchers' debits and credits don't add up to the same total here.

**Usually a consequence of:** LB-TRF-001, LB-VAL-007, LB-SYNC-002, LB-SYNC-010, LB-TRF-002.

**Common causes:**

- A line not read (e.g. a kind of line the rules don't handle).
- Rounding or foreign currency amounts read differently.
- A sign read the wrong way round.

**How to investigate:**

- .\dev.ps1 validate analyse -Env <env> reports the patterns by count.

**How to fix:**

- Fix the rule found by analyse, then transform rebuild.

**Next step:** `.\dev.ps1 validate analyse -Env <env>`

### LB-VAL-002: Trial balance doesn't balance

`tb_unbalanced` | Error

**What it means:** On some dates total debits and credits differ.

**Usually a consequence of:** LB-VAL-001, LB-VAL-003, LB-TRF-001, LB-VAL-007, LB-SYNC-002, LB-SYNC-010, LB-TRF-002.

**Common causes:**

- Vouchers that don't balance (LB-VAL-001).
- Opening balances that don't total zero (LB-VAL-003).

**How to investigate:**

- .\dev.ps1 validate analyse -Env <env> shows which dates and why.

**How to fix:**

- Fix the unbalanced vouchers first; this usually follows.

**Next step:** `.\dev.ps1 validate analyse -Env <env>`

### LB-VAL-003: Opening balances don't total zero

`opening_difference` | Warning

**What it means:** The ledgers' opening balances don't add up to zero (the source reports a difference in opening balances).

**Usually a consequence of:** LB-TRF-001, LB-VAL-007, LB-SYNC-002, LB-SYNC-010, LB-TRF-002.

**Common causes:**

- The source company itself has a difference in opening balances.
- A ledger's opening balance is missing here.

**How to investigate:**

- Check the trial balance in the source for 'Difference in opening balances'.

**How to fix:**

- If the source shows the same difference, nothing to fix here.

**Next step:** `.\dev.ps1 validate analyse -Env <env>`

### LB-VAL-004: Ledger balances today

`closing_mismatch` | Error

**What it means:** Some ledgers' balances as of the validation date differ from the source's.

**Usually a consequence of:** LB-TRF-001, LB-VAL-007, LB-SYNC-002, LB-SYNC-010, LB-TRF-002.

**Common causes:**

- A rule that counts some vouchers differently (e.g. a voucher type, post-dated or optional vouchers).
- Opening balances handled differently across financial years.
- Records that failed to convert (LB-TRF-001).

**How to investigate:**

- .\dev.ps1 validate analyse -Env <env> tests the explanations and counts which fit.

**How to fix:**

- Fix the rule found by analyse, then transform rebuild and validate.

**Next step:** `.\dev.ps1 validate analyse -Env <env>`

### LB-VAL-005: Profit and loss balance

`profit_carrier_mismatch` | Error

**What it means:** The profit and loss ledger's balance (with the period's profit) differs from the source's.

**Usually a consequence of:** LB-VAL-004, LB-TRF-001, LB-VAL-007, LB-SYNC-002, LB-SYNC-010, LB-TRF-002.

**Common causes:**

- Income or expense ledgers that differ (LB-VAL-004).
- Profit carried forward across financial years differently.

**How to investigate:**

- .\dev.ps1 validate analyse -Env <env>

**How to fix:**

- Fix the ledger balances first; this usually follows.

**Next step:** `.\dev.ps1 validate analyse -Env <env>`

### LB-VAL-006: Balances at year ends

`year_end_mismatch` | Error

**What it means:** Some ledgers' balances at past financial year ends differ from the source's.

**Usually a consequence of:** LB-TRF-001, LB-VAL-007, LB-SYNC-002, LB-SYNC-010, LB-TRF-002.

**Common causes:**

- The same causes as today's balances (LB-VAL-004), from an earlier year: the first year end that differs is often where today's differences start.
- The source restarting income and expense ledgers each financial year.

**How to investigate:**

- .\dev.ps1 validate analyse -Env <env> shows the first year end where each differs.

**How to fix:**

- Fix the rule found by analyse, then transform rebuild.

**Next step:** `.\dev.ps1 validate analyse -Env <env>`

### LB-VAL-007: Ledgers missing here

`ledger_missing` | Error

**What it means:** Some ledgers in the source aren't in the accounting tables.

**Usually a consequence of:** LB-TRF-001, LB-SYNC-002, LB-SYNC-004.

**Common causes:**

- Ledger records that failed to convert (LB-TRF-001).
- Ledgers not fetched (an unfinished or unverified sync).

**How to investigate:**

- .\dev.ps1 transform explain -Env <env>

**How to fix:**

- Fix the failures, then transform retry.

**Next step:** `.\dev.ps1 transform explain -Env <env>`

### LB-VAL-008: Voucher counts per month

`voucher_count_mismatch` | Error

**What it means:** In some months the number of vouchers of a type differs from the source's.

**Usually a consequence of:** LB-TRF-001, LB-SYNC-002, LB-SYNC-004.

**Common causes:**

- Vouchers that failed to convert, or periods not fetched completely.

**How to investigate:**

- The report's work in progress and -Details show failures and unverified periods.

**How to fix:**

- Fix the failures or fetch again (sync full), then validate.

**Next step:** `.\dev.ps1 sync full -Env <env>`

### LB-VAL-009: Stock quantities

`stock_quantity_mismatch` | Error

**What it means:** Some stock items' closing quantities differ from the source's.

**Usually a consequence of:** LB-TRF-001, LB-VAL-007, LB-SYNC-002, LB-SYNC-010, LB-TRF-002.

**Common causes:**

- Inventory-only vouchers counted differently (delivery and receipt notes, journals).
- Alternate or compound units, godown transfers or opening quantities.

**How to investigate:**

- .\dev.ps1 validate analyse -Env <env> counts the explanations per voucher type.

**How to fix:**

- Fix the rule found by analyse, then transform rebuild.

**Next step:** `.\dev.ps1 validate analyse -Env <env>`

### LB-VAL-010: Bill-wise outstanding

`bills_mismatch` | Error

**What it means:** Some parties' outstanding bills differ from the source's.

**Usually a consequence of:** LB-TRF-001, LB-VAL-007, LB-SYNC-002, LB-SYNC-010, LB-TRF-002.

**Common causes:**

- On-account amounts or opening bills handled differently.
- Vouchers that failed to convert.

**How to investigate:**

- .\dev.ps1 validate analyse -Env <env>

**How to fix:**

- Fix the rule found by analyse, then transform rebuild.

**Next step:** `.\dev.ps1 validate analyse -Env <env>`

### LB-VAL-011: Source balances couldn't be read

`closing_unavailable` | Error

**What it means:** The source's closing balances couldn't be read, so balances weren't compared.

**Common causes:**

- The source stopped answering or the company isn't loaded.

**How to investigate:**

- .\dev.ps1 entity-check -Env <env>

**How to fix:**

- Load the companies in TallyPrime and validate again.

**Next step:** `.\dev.ps1 validate -Env <env>`

### LB-VAL-012: Source year-end balances couldn't be read

`year_end_balances_unavailable` | Error

**What it means:** The source's balances at a year end couldn't be read, so that year end wasn't compared.

**Common causes:**

- The source timed out on a large company.

**How to investigate:**

- .\dev.ps1 entity-check -Env <env>

**How to fix:**

- Validate again with TallyPrime idle; raise the timeout with connect -TimeoutSec.

**Next step:** `.\dev.ps1 validate -Env <env>`

### LB-VAL-013: Source voucher counts couldn't be read

`voucher_counts_unavailable` | Error

**What it means:** The source's voucher counts couldn't be read, so they weren't compared.

**Common causes:**

- The source timed out or stopped answering.

**How to investigate:**

- .\dev.ps1 entity-check -Env <env>

**How to fix:**

- Validate again with TallyPrime idle.

**Next step:** `.\dev.ps1 validate -Env <env>`

### LB-VAL-014: Source stock quantities couldn't be read

`stock_quantities_unavailable` | Error

**What it means:** The source's stock quantities couldn't be read, so they weren't compared.

**Common causes:**

- The source timed out or stopped answering.

**How to investigate:**

- .\dev.ps1 entity-check -Env <env>

**How to fix:**

- Validate again with TallyPrime idle.

**Next step:** `.\dev.ps1 validate -Env <env>`

### LB-VAL-015: Source bills couldn't be read

`bill_outstanding_unavailable` | Error

**What it means:** The source's bill-wise outstanding couldn't be read, so bills weren't compared.

**Common causes:**

- The source timed out or stopped answering.

**How to investigate:**

- .\dev.ps1 entity-check -Env <env>

**How to fix:**

- Validate again with TallyPrime idle.

**Next step:** `.\dev.ps1 validate -Env <env>`

### LB-VAL-016: Check not offered by the source

`check_not_supported` | Note

**What it means:** The source can't report some figures, so that check was skipped.

**Common causes:**

- The source or its version doesn't offer that report.

**How to investigate:**

- The report's -Details lists which checks.

**How to fix:**

- Nothing to fix.

**Next step:** `.\dev.ps1 report -Env <env> -Details`

### LB-VAL-017: Compared only in total

`not_compared` | Note

**What it means:** Some figures are compared only in total or only as of today (stock values, bills).

**Common causes:**

- Stock values depend on the source's valuation method; bills are reported as of now.

**How to investigate:**

- schema.md Section 5.2 describes each check.

**How to fix:**

- Nothing to fix.

**Next step:** `.\dev.ps1 report -Env <env> -Details`

### LB-VAL-018: Quick validation

`source_controls_not_checked` | Note

**What it means:** This validation skipped the source's controls (voucher counts, stock, bills, year ends), so those checks show no result.

**Common causes:**

- validate -Quick, or a validation after an incremental sync.

**How to investigate:**

- Compare with the last thorough validation.

**How to fix:**

- Run a thorough validation.

**Next step:** `.\dev.ps1 validate -Env <env>`

### LB-VAL-019: Not validated yet

`never_validated` | Warning

**What it means:** This company has never been validated against the source.

**Common causes:**

- It was synced with validation skipped, or not synced yet.

**How to investigate:**

- .\dev.ps1 status -Env <env>

**How to fix:**

- Validate it.

**Next step:** `.\dev.ps1 validate -Env <env>`

### LB-VAL-020: Validation couldn't run

`validation_error` | Error

**What it means:** Validation stopped with an error, so the company has no new result.

**Common causes:**

- The source didn't answer, or a company isn't loaded.

**How to investigate:**

- .\dev.ps1 entity-check -Env <env>

**How to fix:**

- Load the companies in TallyPrime and validate again.

**Next step:** `.\dev.ps1 validate -Env <env>`


## Connection settings

### LB-CON-001: No connection yet

`no_connection` | Warning

**What it means:** Nothing is connected in this environment yet.

**Common causes:**

- A new environment.

**How to investigate:**

- docs/pilot-runbook.md, step 3.

**How to fix:**

- Connect the source's companies (add -Origin backup for backup data).

**Next step:** `.\dev.ps1 connect -Env <env> -All`

### LB-CON-002: Scheduled syncs paused

`connection_paused` | Note

**What it means:** The worker doesn't sync this connection on a schedule; manual syncs still work.

**Common causes:**

- New connections start paused, or it was paused on purpose.

**How to investigate:**

- .\dev.ps1 status -Env <env>

**How to fix:**

- Activate it if scheduled syncs are wanted.

**Next step:** `.\dev.ps1 connect -Env <env> -All -Activate`


## The system itself

### LB-SYS-001: Unexpected error

`unexpected_error` | Error

**What it means:** A command stopped with an error it doesn't explain itself (its type and a short message are shown, never values).

**Common causes:**

- A bug, or a database or network problem.

**How to investigate:**

- .\dev.ps1 logs api -Env <env> (shows errors without accounting values).

**How to fix:**

- Share the error line (type and code) with the developer.

**Next step:** `.\dev.ps1 status -Env <env>`

### LB-SYS-002: Background job stopped without finishing

`job_gone` | Error

**What it means:** A background job stopped sending signs of life before it finished.

**Common causes:**

- The api container restarted or the computer slept.

**How to investigate:**

- .\dev.ps1 status -Env <env>

**How to fix:**

- Run the command again; a sync continues where it stopped.

**Next step:** `.\dev.ps1 report -Env <env>`

### LB-SYS-003: Database busy or unavailable

`database_unavailable` | Error

**What it means:** The database didn't answer or a lock wasn't released in time.

**Common causes:**

- The stack is starting or stopping, or another long job holds a lock.

**How to investigate:**

- .\dev.ps1 status -Env <env>

**How to fix:**

- Wait for running jobs, then run the command again.

**Next step:** `.\dev.ps1 status -Env <env>`
