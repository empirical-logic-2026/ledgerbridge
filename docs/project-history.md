# Project history

| Field | Value |
| --- | --- |
| Version | 1.3 |
| Date | 2026-10-19 |
| Covers | M0 to M4, the pilot on the client's two companies, PRs #1 to #33 |

What has been built and done so far, in order: the milestones, every pull request with what it did and why, the problems the pilot found and how each was fixed, the pilot's results, lessons learned and what is still open. Counts and Tally's standard names only: no client names or amounts. The rules themselves are in the [rulebook](rules/validation-and-conversion-rules.md); the database in the [schema reference](database/schema-reference.md); the decisions in [architecture.md](architecture.md) (ADR-001 to ADR-038).

## 1. Milestones

| Milestone | What it delivered | PRs |
| --- | --- | --- |
| M0 Repository scaffold | Repository layout, docs (requirements, architecture, schema, roadmap), Docker Compose stacks for `test` and `pilot`, `dev.ps1`. | #1 |
| M1 Tally proof of concept | Reading Tally through its XML interface into `raw_records`; the sign convention confirmed on the test company. | #2 |
| M2 Database foundation | The four databases (`ledgerbridge_source`, `_accounting`, `_reporting`, `_system`), database users with least rights, migrations as `migrator`. | #4 |
| M3 Full and incremental sync | Raw records into the canonical tables; AlterID markers; altered, cancelled and deleted vouchers; several companies per run. | #5 |
| M4 Validation | Voucher, trial balance and closing-balance checks after every sync, stored with alerts; then the source's controls (counts, stock, bills, year ends). | #7, then the pilot fixes |
| Pilot (M9 started early) | The client's two companies loaded from backups in the `pilot` environment; the developer runs it, Claude Code never touches it. | #8 to #33 |

Design work alongside: AI data protection (#3), the dashboard home page design (#6), budget planning (#16), foreign currency (#32), the plain-language codebase guide (#18) and the generated diagrams (#19).

## 2. Pull requests in order

| PR | Date | What | Why |
| --- | --- | --- | --- |
| #1 | 2026-10-09 | M0 scaffold and docs | Starting point. |
| #2 | 2026-10-09 | M1 Tally proof of concept | Prove Tally can be read and the signs understood. |
| #3 | 2026-10-09 | AI data-protection requirements and design (AI-011 to AI-018, ADR-015) | Client data must never leave the deployment unprotected. |
| #4 | 2026-10-09 | M2 schema with readable database names (ADR-016) | One database per layer, least-privilege users. |
| #5 | 2026-10-12 | M3 full and incremental sync | Canonical model filled from Tally. |
| #6 | 2026-10-12 | Dashboard home page design (docs) | Agreed design before building M7. |
| #7 | 2026-10-12 | M4 validation and alerts; pilot preparation | Prove the books are complete and correct. |
| #8 | 2026-10-12 | `dev.ps1 init-env` path fix; control characters test | First pilot step failed on a path. |
| #9 | 2026-10-12 | No lock on the connection row during syncs; new connections paused; safe connect and reset (ADR-020) | The pilot's first sync blocked other commands. |
| #10 | 2026-10-12 | Companies found by GUID; `entity-check`; progress output (ADR-021) | Company names with double and trailing spaces weren't found. |
| #11 | 2026-10-12 | Chunked, resumable, company-by-company syncs; adaptive splitting (ADR-022) | Large months timed out; a failure lost all progress. |
| #12 | 2026-10-12 | Unverified chunks never counted complete; part-month probe; refetch from a date (ADR-023) | A part-month listing returned fewer vouchers than the month. |
| #13 | 2026-10-13 | UDF prefixes; busy source after timeouts; background syncs with `watch` (ADR-024) | Undeclared `UDF:` prefixes broke parsing; closing the terminal stopped syncs. |
| #14 | 2026-10-13 | `transform retry`, failure breakdowns, company labels, safe data errors, flexible accounting layer (ADR-025) | 2,170 ledgers and 238,392 vouchers failed in one batch on a data error. |
| #15 | 2026-10-13 | `transform rebuild`; only an object's latest version is applied (DAT-008) | Re-convert stored data with new code without Tally. |
| #16 | 2026-10-13 | Budget planning and analysis in the plan (docs, ADR-026) | Client requirement. |
| #17 | 2026-10-13 | Reference resolution, `transform explain`, voucher type tree, non-posting types (ADR-027) | Records failed on names that differed in spacing or case; custom voucher types. |
| #18 | 2026-10-13 | Plain-language codebase guide | Onboarding. |
| #19 | 2026-10-13 | ER, database and data-flow diagrams generated from the models | Keep pictures true to the code. |
| #20 | 2026-10-13 | `validate analyse`; stock journals, orders and foreign-currency rules | Explain mismatches with counts only. |
| #21 | 2026-10-14 | Health report, stable error codes, error catalogue (ADR-028) | Readable results for the developer. |
| #22 | 2026-10-14 | Tally's counting rules reproduced on the test company (ADR-029): openings as at the books' beginning, tracked notes, non-posting vouchers | Ledgers differed by their opening; stock by tracked lines. |
| #23 | 2026-10-15 | `dev.ps1` arguments, run lock tied to its job, unfinished work first (ADR-030) | `status` split an argument; a lock survived a shutdown. |
| #24 | 2026-10-15 | Job work and godowns; stock journals read once; the source's own opening difference (ADR-031) | Stock differences on job work; stock journal entries counted twice. |
| #25 | 2026-10-15 | Stock ledgers with integrated inventory; anonymous ledger profiles | A renamed Stock-in-Hand group's ledger differed. |
| #26 | 2026-10-15 | Probes for the last ledger differences | Narrow down the remaining differences. |
| #27 | 2026-10-15 | Compare only on reliable dates in Educational mode (ADR-032) | Tally's balance for the 30th included later vouchers. |
| #28 | 2026-10-15 | Stock ledgers at the stock value; Tally's own totals; effective dates; narrowed dates (ADR-033) | Two companies reported the stock ledger at the stock value. |
| #29 | 2026-10-16 | Names as Tally resolves them; deleted masters; line attribution in `validate analyse` (ADR-034) | Three customers differed as if lines sat on the wrong ledger. |
| #30 | 2026-10-16 | Foreign-currency ledgers at Tally's book value (ADR-035) | The three customers were foreign-currency ledgers, revalued by Tally. |
| #31 | 2026-10-16 | `validate compare-ledger`; foreign-currency ledgers one by one (ADR-036) | Prove our vouchers equal Tally's, ledger by ledger. |
| #32 | 2026-10-16 | Foreign currency alongside the base-currency books (docs, ADR-037) | Client requirement: own-currency balances, gains and losses, exposure. |
| #33 | 2026-10-16 | Foreign-currency book value from Tally's vouchers; opening difference as Tally shows it (ADR-038) | Tally's report showed no calculated line to subtract; an opening warning Tally doesn't show. |
| #34 | 2026-10-16 | Knowledge base: rulebook, generated schema reference, project history, progress log, Word and PDF copies | One place for every rule and table, with proof and history. |
| #35 | 2026-10-19 | TallyPrime Edit Log checked like for like; seed case and test (no code change) | Confirm the platform works unchanged on Edit Log. |
| #36 | 2026-10-19 | Security foundations: checks on every pull request, CLAUDE.md security checklist and report sections, threat model and security guide (SEC-009, ADR-039) | Catch bugs, vulnerable dependencies, insecure code and secrets before merging, ahead of M5. |
| #37 to #44 | 2026-10-19 to 2026-10-22 | dev.ps1 tests on Windows in CI; A3 simplicity review (Tally connector, transform, validation and analyse, workers, scripts) with every result identical before and after; the review's findings fixed | Code the developer can fully understand; bugs found on the way fixed with tests. |
| feat/stock-values | 2026-10-22 | The source's stock values and foreign-currency revaluations stored as source figures; Trial Balance, Profit & Loss and Balance Sheet laid out as Tally's and checked against its own reports line by line (ADR-040) | Reports must equal Tally's; recorded on the test company with integration on and off. |

## 3. Problems found and how each was fixed

| Problem (pilot) | Cause | Fix | PR |
| --- | --- | --- | --- |
| Commands blocked during a sync | A transaction held the connection row | Short transactions; commit each batch | #9 |
| Companies not found | Names with double and trailing spaces | Identify companies by GUID | #10 |
| Timeouts and lost progress on large months | One request per month; no checkpoints | Chunks, checkpoints, adaptive splitting, resume | #11 |
| Missing vouchers counted as complete | Part-month listings incomplete | Verify chunks; unverified ranges re-fetched | #12 |
| Parse errors | Undeclared `UDF:` XML prefixes | Prefixes kept and parsed | #13 |
| Thousands of records failed together | One data error failed a whole batch | Record-level failures; values kept in `extra`; retry and rebuild | #14, #15 |
| References not resolved | Spacing, case, aliases, custom voucher types | One resolution rule set; voucher type tree | #17 |
| Ledgers off by their opening | Openings fetched for Tally's current period | Fetch as at the books' beginning | #22 |
| Stock counted twice | Invoice lines tracked to notes; stock journals' two lists | Count the note; read stock journals once | #22, #24 |
| Stock differences on job work | A job worker's godown is outside Tally's stock | Godown kinds | #24 |
| Stock ledger differences | Tally reports it at the stock value | Compare with the stock value | #25, #28 |
| Wrong balances on some dates | Educational mode answers only the 1st, 2nd, 31st | Reliable dates | #27 |
| Three customers differing | Foreign-currency ledgers revalued by Tally | Book value from Tally's own vouchers | #30, #31, #33 |
| Opening difference warning | Our figure differed from what Tally displays | Use Tally's own trial balance line | #33 |
| A lock outliving its job; argument splitting | Lock not tied to the job; PowerShell arrays | Lock with heartbeat; argument handling | #23 |

## 4. Pilot results (counts only)

- **Entity 2:** validation **passes**: 415,301 checks, 0 failed.
- **Entity 1:** from 16 failures (Educational-mode dates, PR #27) to 9 (three foreign-currency customers today and at year ends, plus the opening warning). `validate compare-ledger` then matched every one of Tally's vouchers with ours for those customers (47 of 47, 60 of 60, 3 of 3; our extra vouchers were 3 optional Journals each, not counted), with equal totals. PR #33 compares them with Tally's book value and follows Tally's own opening difference; the result of the developer's run after it is to be recorded here.
- **Test company:** passes every check (104 as of 2026-10-02), with the stock-ledger and foreign-currency notes.

### TallyPrime Edit Log (2026-10-19)

The test company was opened in TallyPrime Edit Log (migrated, same GUID). Every export the sync and validation use was identical to TallyPrime's in fields, formats and values; an alteration leaves no edit history in the XML export, only a filled `UPDATEDDATETIME` (not fetched). Full sync, validation (105 checks) and the report passed with no code change. A first attempt opened an empty new company of the same name (a different GUID, with job work, cost centres and reversing journals off): nothing was written to it.

## 5. Lessons learned

- **Reproduce before coding.** Every counting rule was first reproduced on the test company and checked against Tally's own reports (ADR-029); guesses about Tally were wrong more than once (trailing spaces, report periods, revaluation).
- **Count, don't name.** Analysis and reports print counts, kinds and Tally's standard names only, so the pilot could be debugged without sharing client data; detail files stay local (`reports/<env>/private/`).
- **Tally's figures are computed for a period and a date.** Openings, balances, stock and revaluations all depend on the requested period; Educational mode restricts reliable dates.
- **The source's own figure beats our reconstruction.** Opening differences, stock values and foreign-currency book values are taken from what Tally itself shows, with our calculation as a fallback.
- **Make long jobs resumable and visible.** Chunks, checkpoints, background jobs with `watch`, heartbeats and stable error codes made the pilot recoverable.
- **Never guess TDL.** A request with an unknown function froze TallyPrime behind a dialog; only exported field and report names are used.

## 6. Open items

| Item | Status |
| --- | --- |
| Sign-off on a licensed TallyPrime | The pilot ran in Educational mode; results must be confirmed on a licensed installation (every date reliable). |
| Accountant sign-off | An accountant confirms the converted books match the client's (OPEN-001). |
| Windows Application Control on the developer's machine | Blocks `.venv\Scripts\*.exe`, so `./dev.ps1 test` can't run; tests run with the base interpreter meanwhile. |
| Foreign-currency data layer | Designed (FX-001 to FX-013, ADR-037), planned for M4b; needs a foreign-currency voucher and a rate entered in TallyPrime first, to copy their exported fields. |
| Long field paths | The field catalogue keys a field by its path cut to 255 characters, so two paths differing only after that are counted as one (values are unaffected). Left until such paths appear; the fix is a schema change (rulebook Section 12). |
| Onboarding robustness | Making the first sync of a new company smooth end to end (connect, full sync, validation, report) without manual steps. |

## Change log

| Date | Version | Change |
| --- | --- | --- |
| 2026-10-22 | 1.3 | PRs #37 to #44; statements from the source's own figures. |
| 2026-10-19 | 1.2 | PRs #34 to #36; security foundations. |
| 2026-10-19 | 1.1 | TallyPrime Edit Log check. |
| 2026-10-16 | 1.0 | First edition, up to PR #33. |
