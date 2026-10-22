"""Every error and warning LedgerBridge reports, with a stable code (source-independent).

One registry for all output (report, status, summary, sync, validate) and for
docs/error-catalogue.md, which is generated from it (`python -m devtools.error_catalogue`;
a test fails when the document is stale).

A problem has:
- a stable **code**: LB-SYNC-xxx (fetching from the source), LB-TRF-xxx (turning stored
  records into accounting tables), LB-VAL-xxx (validation against the source), LB-CON-xxx
  (the connection's settings), LB-SYS-xxx (the system itself). Codes are never reused or
  renumbered: a retired problem keeps its code;
- the **technical key** the code replaces in plain output (a validation check code such as
  `year_end_mismatch`, or an internal name), shown in brackets;
- a plain-language **title**, what it **means**, its **causes**, how to **investigate** and
  how to **fix** it, and the **next step** as an exact command (`{env}` is filled in);
- the problems it is usually a **consequence of**: when one of those is present too, the
  report says so and points at the root cause first.

Texts hold no names, values or amounts: they are safe to print for any environment.
"""

from dataclasses import dataclass, field

ERROR = "error"
WARNING = "warning"
INFO = "info"


@dataclass(frozen=True)
class Problem:
    code: str
    key: str
    title: str
    severity: str  # error / warning / info
    meaning: str
    causes: tuple[str, ...]
    investigate: tuple[str, ...]
    fix: tuple[str, ...]
    next_step: str  # an exact command; {env} is the environment
    consequence_of: tuple[str, ...] = field(default=())  # codes of likely root causes

    def label(self) -> str:
        """`Balances at year ends [year_end_mismatch, LB-VAL-006]`."""
        return f"{self.title} [{self.key}, {self.code}]"

    def command(self, env: str) -> str:
        return self.next_step.replace("{env}", env)


def _p(*args: object, **kwargs: object) -> Problem:
    return Problem(*args, **kwargs)  # type: ignore[arg-type]


# Records missing here change balances and counts: records that failed to convert, ledgers
# missing, and unfinished work (a full sync not finished or interrupted, records waiting).
_FAILED = ("LB-TRF-001", "LB-VAL-007", "LB-SYNC-002", "LB-SYNC-010", "LB-TRF-002")
# Unfinished work comes first in every report's order and next step, before any analysis:
# a running job (follow it), a full sync to resume, then records waiting to be converted
# (pilot 2026-10-15: the next step said `validate analyse` while a full sync was unfinished).
WORK_FIRST = ("LB-SYNC-007", "LB-SYNC-002", "LB-SYNC-010", "LB-SYNC-004", "LB-TRF-002")

PROBLEMS: tuple[Problem, ...] = (
    # --- sync: fetching from the source -------------------------------------------------
    _p(
        "LB-SYNC-001",
        "sync_failed",
        "Last sync failed",
        ERROR,
        "The last sync stopped with an error, so recent changes in the source may be missing.",
        (
            "The source stopped answering or answered with an error.",
            "A database error while storing records.",
        ),
        (
            "Run the report with -Details: it shows the error's type (never values).",
            "Check that the source (TallyPrime) is open with the companies loaded.",
        ),
        ("Fix the cause, then sync again: an interrupted full sync continues where it stopped.",),
        ".\\dev.ps1 sync -Env {env}",
    ),
    _p(
        "LB-SYNC-002",
        "full_sync_unfinished",
        "Unfinished full sync",
        WARNING,
        "A full sync stopped part way. What it fetched is kept; the rest isn't fetched yet.",
        (
            "The window was closed, the computer slept or the source stopped answering.",
            "The job was stopped (sync abandon or a restart of the stack).",
        ),
        ("The report shows how many parts are done and since when.",),
        ("Run the full sync again: it continues from the last completed part.",),
        ".\\dev.ps1 sync full -Env {env}",
    ),
    _p(
        "LB-SYNC-003",
        "deletion_check_failed",
        "Last deletion check failed",
        WARNING,
        "The check for records deleted in the source didn't finish, so deleted records may still "
        "count here.",
        ("The source stopped answering or listed fewer records than expected.",),
        ("Run the report with -Details for the error's type.",),
        ("Run the deletion check again once the source answers.",),
        ".\\dev.ps1 sync deletions -Env {env}",
    ),
    _p(
        "LB-SYNC-004",
        "unverified_range",
        "Periods not verified",
        WARNING,
        "For some periods the source's answer couldn't be confirmed complete, so records from "
        "those periods may be missing.",
        (
            "The source timed out on a large period even after splitting it.",
            "The source returned fewer records than it listed.",
        ),
        ("The report lists the object types and periods (dates only).",),
        (
            "Run a full sync again (fetches unverified periods again); raise the request timeout "
            "with connect -TimeoutSec if they time out.",
        ),
        ".\\dev.ps1 sync full -Env {env}",
        ("LB-SYNC-005",),
    ),
    _p(
        "LB-SYNC-005",
        "source_unresponsive",
        "The source didn't answer",
        ERROR,
        "The source (TallyPrime) didn't answer in time or refused the connection.",
        (
            "TallyPrime is closed, busy (a report or dialog open) or the company isn't loaded.",
            "The request timeout is too short for a large company.",
        ),
        (
            "Check that TallyPrime is open, idle and has the companies loaded.",
            ".\\dev.ps1 entity-check -Env {env} shows whether the companies are found.",
        ),
        ("Leave TallyPrime idle and sync again; raise the timeout with connect -TimeoutSec.",),
        ".\\dev.ps1 entity-check -Env {env}",
    ),
    _p(
        "LB-SYNC-006",
        "entity_not_found",
        "Companies not found in the source",
        ERROR,
        "Some configured companies aren't loaded in the source, so they weren't synced.",
        (
            "The company isn't open in TallyPrime.",
            "The company's name or identity changed in the source.",
        ),
        (".\\dev.ps1 entity-check -Env {env} shows the kinds of difference (never names).",),
        ("Load the companies in TallyPrime, or connect again with their exact names.",),
        ".\\dev.ps1 entity-check -Env {env}",
    ),
    _p(
        "LB-SYNC-007",
        "sync_running",
        "Sync in progress",
        INFO,
        "A sync or another background job is running now.",
        ("A sync you started, or the worker's scheduled sync.",),
        ("Follow it to see its progress.",),
        ("Wait for it to finish; closing the window doesn't stop it.",),
        ".\\dev.ps1 sync watch -Env {env}",
    ),
    _p(
        "LB-SYNC-008",
        "sync_busy",
        "A sync is already running",
        WARNING,
        "This command needs the connection, but another run of it is in progress. The message "
        "says which was found: a running run (its id and last sign of life) or only the "
        "connection's run lock (and when it expires).",
        (
            "The worker started a scheduled sync, or another window started one.",
            "Only a lock: another process is starting a run right now.",
        ),
        (".\\dev.ps1 status -Env {env} shows the running run.",),
        (
            "Wait for it, then run the command again. A run whose process is gone is marked "
            "interrupted after a few minutes without a sign of life, and its lock is cleared; "
            "sync abandon does both at once.",
        ),
        ".\\dev.ps1 sync watch -Env {env}",
    ),
    _p(
        "LB-SYNC-009",
        "never_synced",
        "Never synced",
        WARNING,
        "This connection has no sync yet, so there is no data.",
        ("The connection was just created.",),
        (".\\dev.ps1 status -Env {env}",),
        ("Run a full sync.",),
        ".\\dev.ps1 sync full -Env {env}",
    ),
    _p(
        "LB-SYNC-010",
        "sync_interrupted",
        "Last sync interrupted",
        WARNING,
        "The last sync was interrupted before it finished; its progress is kept.",
        ("The window or stack was stopped, or the process was gone (sync abandon).",),
        ("The report shows any unfinished full sync and its progress.",),
        ("Run the sync again: it continues where it stopped.",),
        ".\\dev.ps1 sync -Env {env}",
    ),
    # --- transform: stored records into accounting tables -------------------------------
    _p(
        "LB-TRF-001",
        "records_failed",
        "Records that failed to convert",
        ERROR,
        "Some stored records couldn't be converted into the accounting tables, so they are "
        "missing from balances, counts and reports.",
        (
            "A reference to a record that is missing (e.g. a voucher's ledger failed itself).",
            "A value the rules don't handle yet (e.g. an unusual amount or date format).",
        ),
        (
            "Run the report with -Details: failures are grouped by kind of record and error "
            "(no values).",
            ".\\dev.ps1 transform explain -Env {env} explains references that didn't resolve.",
        ),
        ("Fix the rule (a code change), then convert the failed records again: transform retry.",),
        ".\\dev.ps1 transform explain -Env {env}",
    ),
    _p(
        "LB-TRF-002",
        "records_pending",
        "Records not converted yet",
        WARNING,
        "Some stored records are still waiting to be converted.",
        ("A sync or transform job was interrupted, or is still running.",),
        ("Check work in progress in the report.",),
        (
            "Convert them: transform retry (doesn't contact the source). If a full sync is "
            "unfinished, resume it instead: it converts them.",
        ),
        ".\\dev.ps1 transform retry -Env {env}",
        ("LB-SYNC-002", "LB-SYNC-010"),
    ),
    _p(
        "LB-TRF-003",
        "values_kept_in_extra",
        "Values kept aside (didn't fit their column)",
        INFO,
        "Some values were longer or larger than their column. The record is kept, the full value "
        "is in its `extra` column and the column holds a shortened copy.",
        ("The source allows longer texts than the column (e.g. long narrations).",),
        ("Run the report with -Details for the columns affected and the largest size seen.",),
        (
            "Nothing needed unless reports must show the full value; widen the column with a "
            "migration if so.",
        ),
        ".\\dev.ps1 report -Env {env} -Details",
    ),
    _p(
        "LB-TRF-004",
        "reference_matched_flexibly",
        "References matched flexibly",
        INFO,
        "Some references by name matched only after allowing for differences in spacing, case "
        "or punctuation, or through an alias.",
        (
            "The source stores a name slightly differently where it is used than where it is "
            "defined.",
        ),
        ("Run the report with -Details for counts by kind of match.",),
        ("Nothing needed: these records are converted. Review if numbers look wrong.",),
        ".\\dev.ps1 report -Env {env} -Details",
    ),
    _p(
        "LB-TRF-005",
        "reference_ambiguous",
        "Ambiguous references left empty",
        WARNING,
        "Some references by name matched more than one record, so they were left empty.",
        ("Two records with names that differ only in spacing, case or punctuation.",),
        (".\\dev.ps1 transform explain -Env {env}",),
        ("Rename one of the look-alike records in the source, sync, then transform retry.",),
        ".\\dev.ps1 transform explain -Env {env}",
    ),
    _p(
        "LB-TRF-006",
        "fields_without_column",
        "Fields with no column",
        INFO,
        "The source has fields with no column here (e.g. Tally user-defined fields). They are "
        "kept in `extra` and listed in the field catalogue.",
        ("Customisations in the source (TDL, UDFs).",),
        (".\\dev.ps1 fields -Env {env}",),
        ("Promote a field to a reporting dimension if it is needed: promote-field.",),
        ".\\dev.ps1 fields -Env {env}",
    ),
    _p(
        "LB-TRF-007",
        "mapping_assumptions",
        "Mapping assumptions",
        INFO,
        "Some records were converted with an assumption (e.g. a GST ledger with no duty head "
        "taken as Central Tax).",
        ("The source left a field empty that the mapping needs.",),
        ("docs/pilot-runbook.md explains each assumption and how to check it in the source.",),
        ("Check the count in the source; report whether it matches.",),
        ".\\dev.ps1 summary -Env {env}",
    ),
    _p(
        "LB-TRF-008",
        "unmapped_ledgers",
        "Ledgers without a standard account",
        INFO,
        "Some ledgers have no standard account. Reports place them under the nearest standard "
        "parent account.",
        ("Ledgers under custom groups, by design.",),
        ("The report shows the count per company.",),
        ("Nothing needed now (mapping review comes with the reports milestone).",),
        ".\\dev.ps1 report -Env {env}",
    ),
    _p(
        "LB-TRF-009",
        "custom_xml_prefixes",
        "Custom fields in the source's data",
        INFO,
        "The source's data contains fields from customisations (XML prefixes such as UDF). They "
        "are stored unchanged.",
        ("TDL customisations or user-defined fields in the source.",),
        (".\\dev.ps1 fields -Env {env}",),
        ("Nothing needed; promote a field if reports need it.",),
        ".\\dev.ps1 fields -Env {env}",
    ),
    # --- validation: our figures against the source's ----------------------------------
    _p(
        "LB-VAL-001",
        "voucher_unbalanced",
        "Vouchers that don't balance",
        ERROR,
        "Some vouchers' debits and credits don't add up to the same total here.",
        (
            "A line not read (e.g. a kind of line the rules don't handle).",
            "Rounding or foreign currency amounts read differently.",
            "A sign read the wrong way round.",
        ),
        (".\\dev.ps1 validate analyse -Env {env} reports the patterns by count.",),
        ("Fix the rule found by analyse, then transform rebuild.",),
        ".\\dev.ps1 validate analyse -Env {env}",
        _FAILED,
    ),
    _p(
        "LB-VAL-002",
        "tb_unbalanced",
        "Trial balance doesn't balance",
        ERROR,
        "On some dates total debits and credits differ.",
        (
            "Vouchers that don't balance (LB-VAL-001).",
            "Opening balances that don't total zero (LB-VAL-003).",
        ),
        (".\\dev.ps1 validate analyse -Env {env} shows which dates and why.",),
        ("Fix the unbalanced vouchers first; this usually follows.",),
        ".\\dev.ps1 validate analyse -Env {env}",
        ("LB-VAL-001", "LB-VAL-003", *_FAILED),
    ),
    _p(
        "LB-VAL-003",
        "opening_difference",
        "Opening balances don't total zero",
        WARNING,
        "The ledgers' opening balances don't add up to zero (the source reports a difference "
        "in opening balances).",
        (
            "The source company itself has a difference in opening balances.",
            "A ledger's opening balance is missing here.",
        ),
        ("Check the trial balance in the source for 'Difference in opening balances'.",),
        ("If the source shows the same difference, nothing to fix here.",),
        ".\\dev.ps1 validate analyse -Env {env}",
        _FAILED,
    ),
    _p(
        "LB-VAL-004",
        "closing_mismatch",
        "Ledger balances today",
        ERROR,
        "Some ledgers' balances as of the validation date differ from the source's.",
        (
            "A rule that counts some vouchers differently (e.g. a voucher type, post-dated or "
            "optional vouchers).",
            "Opening balances handled differently across financial years.",
            "Records that failed to convert (LB-TRF-001).",
        ),
        (".\\dev.ps1 validate analyse -Env {env} tests the explanations and counts which fit.",),
        ("Fix the rule found by analyse, then transform rebuild and validate.",),
        ".\\dev.ps1 validate analyse -Env {env}",
        _FAILED,
    ),
    _p(
        "LB-VAL-005",
        "profit_carrier_mismatch",
        "Profit and loss balance",
        ERROR,
        "The profit and loss ledger's balance (with the period's profit) differs from the "
        "source's.",
        (
            "Income or expense ledgers that differ (LB-VAL-004).",
            "Profit carried forward across financial years differently.",
        ),
        (".\\dev.ps1 validate analyse -Env {env}",),
        ("Fix the ledger balances first; this usually follows.",),
        ".\\dev.ps1 validate analyse -Env {env}",
        ("LB-VAL-004", *_FAILED),
    ),
    _p(
        "LB-VAL-006",
        "year_end_mismatch",
        "Balances at year ends",
        ERROR,
        "Some ledgers' balances at past financial year ends differ from the source's.",
        (
            "The same causes as today's balances (LB-VAL-004), from an earlier year: the first "
            "year end that differs is often where today's differences start.",
            "The source restarting income and expense ledgers each financial year.",
        ),
        (".\\dev.ps1 validate analyse -Env {env} shows the first year end where each differs.",),
        ("Fix the rule found by analyse, then transform rebuild.",),
        ".\\dev.ps1 validate analyse -Env {env}",
        _FAILED,
    ),
    _p(
        "LB-VAL-007",
        "ledger_missing",
        "Ledgers missing here",
        ERROR,
        "Some ledgers in the source aren't in the accounting tables.",
        (
            "Ledger records that failed to convert (LB-TRF-001).",
            "Ledgers not fetched (an unfinished or unverified sync).",
        ),
        (".\\dev.ps1 transform explain -Env {env}",),
        ("Fix the failures, then transform retry.",),
        ".\\dev.ps1 transform explain -Env {env}",
        ("LB-TRF-001", "LB-SYNC-002", "LB-SYNC-004"),
    ),
    _p(
        "LB-VAL-008",
        "voucher_count_mismatch",
        "Voucher counts per month",
        ERROR,
        "In some months the number of vouchers of a type differs from the source's.",
        ("Vouchers that failed to convert, or periods not fetched completely.",),
        ("The report's work in progress and -Details show failures and unverified periods.",),
        ("Fix the failures or fetch again (sync full), then validate.",),
        ".\\dev.ps1 sync full -Env {env}",
        ("LB-TRF-001", "LB-SYNC-002", "LB-SYNC-004"),
    ),
    _p(
        "LB-VAL-009",
        "stock_quantity_mismatch",
        "Stock quantities",
        ERROR,
        "Some stock items' closing quantities differ from the source's.",
        (
            "Inventory-only vouchers counted differently (delivery and receipt notes, journals).",
            "Alternate or compound units, godown transfers or opening quantities.",
        ),
        (".\\dev.ps1 validate analyse -Env {env} counts the explanations per voucher type.",),
        ("Fix the rule found by analyse, then transform rebuild.",),
        ".\\dev.ps1 validate analyse -Env {env}",
        _FAILED,
    ),
    _p(
        "LB-VAL-010",
        "bills_mismatch",
        "Bill-wise outstanding",
        ERROR,
        "Some parties' outstanding bills differ from the source's.",
        (
            "On-account amounts or opening bills handled differently.",
            "Vouchers that failed to convert.",
        ),
        (".\\dev.ps1 validate analyse -Env {env}",),
        ("Fix the rule found by analyse, then transform rebuild.",),
        ".\\dev.ps1 validate analyse -Env {env}",
        _FAILED,
    ),
    _p(
        "LB-VAL-011",
        "closing_unavailable",
        "Source balances couldn't be read",
        ERROR,
        "The source's closing balances couldn't be read, so balances weren't compared.",
        ("The source stopped answering or the company isn't loaded.",),
        (".\\dev.ps1 entity-check -Env {env}",),
        ("Load the companies in TallyPrime and validate again.",),
        ".\\dev.ps1 validate -Env {env}",
    ),
    _p(
        "LB-VAL-012",
        "year_end_balances_unavailable",
        "Source year-end balances couldn't be read",
        ERROR,
        "The source's balances at a year end couldn't be read, so that year end wasn't compared.",
        ("The source timed out on a large company.",),
        (".\\dev.ps1 entity-check -Env {env}",),
        ("Validate again with TallyPrime idle; raise the timeout with connect -TimeoutSec.",),
        ".\\dev.ps1 validate -Env {env}",
    ),
    _p(
        "LB-VAL-013",
        "voucher_counts_unavailable",
        "Source voucher counts couldn't be read",
        ERROR,
        "The source's voucher counts couldn't be read, so they weren't compared.",
        ("The source timed out or stopped answering.",),
        (".\\dev.ps1 entity-check -Env {env}",),
        ("Validate again with TallyPrime idle.",),
        ".\\dev.ps1 validate -Env {env}",
    ),
    _p(
        "LB-VAL-014",
        "stock_quantities_unavailable",
        "Source stock quantities couldn't be read",
        ERROR,
        "The source's stock quantities couldn't be read, so they weren't compared.",
        ("The source timed out or stopped answering.",),
        (".\\dev.ps1 entity-check -Env {env}",),
        ("Validate again with TallyPrime idle.",),
        ".\\dev.ps1 validate -Env {env}",
    ),
    _p(
        "LB-VAL-015",
        "bill_outstanding_unavailable",
        "Source bills couldn't be read",
        ERROR,
        "The source's bill-wise outstanding couldn't be read, so bills weren't compared.",
        ("The source timed out or stopped answering.",),
        (".\\dev.ps1 entity-check -Env {env}",),
        ("Validate again with TallyPrime idle.",),
        ".\\dev.ps1 validate -Env {env}",
    ),
    _p(
        "LB-VAL-016",
        "check_not_supported",
        "Check not offered by the source",
        INFO,
        "The source can't report some figures, so that check was skipped.",
        ("The source or its version doesn't offer that report.",),
        ("The report's -Details lists which checks.",),
        ("Nothing to fix.",),
        ".\\dev.ps1 report -Env {env} -Details",
    ),
    _p(
        "LB-VAL-017",
        "not_compared",
        "Compared only in total",
        INFO,
        "Some figures are compared only in total or only as of today (stock values, bills).",
        ("Stock values depend on the source's valuation method; bills are reported as of now.",),
        ("schema.md Section 5.2 describes each check.",),
        ("Nothing to fix.",),
        ".\\dev.ps1 report -Env {env} -Details",
    ),
    _p(
        "LB-VAL-018",
        "source_controls_not_checked",
        "Quick validation",
        INFO,
        "This validation skipped the source's controls (voucher counts, stock, bills, year "
        "ends), so those checks show no result.",
        ("validate -Quick, or a validation after an incremental sync.",),
        ("Compare with the last thorough validation.",),
        ("Run a thorough validation.",),
        ".\\dev.ps1 validate -Env {env}",
    ),
    _p(
        "LB-VAL-019",
        "never_validated",
        "Not validated yet",
        WARNING,
        "This company has never been validated against the source.",
        ("It was synced with validation skipped, or not synced yet.",),
        (".\\dev.ps1 status -Env {env}",),
        ("Validate it.",),
        ".\\dev.ps1 validate -Env {env}",
    ),
    _p(
        "LB-VAL-020",
        "validation_error",
        "Validation couldn't run",
        ERROR,
        "Validation stopped with an error, so the company has no new result.",
        ("The source didn't answer, or a company isn't loaded.",),
        (".\\dev.ps1 entity-check -Env {env}",),
        ("Load the companies in TallyPrime and validate again.",),
        ".\\dev.ps1 validate -Env {env}",
    ),
    _p(
        "LB-VAL-021",
        "stock_ledger_at_stock_value",
        "Stock ledgers at the stock value",
        INFO,
        "The source reports its stock ledgers (Tally: under Stock-in-Hand) at its closing "
        "stock value, not at their own opening and postings, so they were compared with that "
        "value.",
        (
            "Tally with accounts integrated with inventory in some companies, or closing "
            "values entered on the stock ledgers.",
        ),
        (".\\dev.ps1 validate analyse -Env {env} profiles the stock ledgers.",),
        ("Nothing to fix.",),
        ".\\dev.ps1 report -Env {env} -Details",
    ),
    _p(
        "LB-VAL-022",
        "foreign_ledgers_at_book_value",
        "Foreign-currency ledgers at book value",
        INFO,
        "Ledgers kept in a foreign currency were compared with the source's book value (as "
        "its trial balance and ledger vouchers show it), not with their closing balances "
        "revalued at current exchange rates.",
        ("Tally reports a foreign-currency ledger's closing balance at current rates.",),
        (".\\dev.ps1 validate analyse -Env {env} profiles foreign-currency ledgers.",),
        ("Nothing to fix.",),
        ".\\dev.ps1 report -Env {env} -Details",
    ),
    _p(
        "LB-VAL-023",
        "statement_reports_unavailable",
        "Source statements couldn't be compared",
        ERROR,
        "The source didn't provide all three financial statements, so no complete comparison "
        "was made.",
        (
            "The source doesn't support all three statement reports.",
            "A report returned no statement lines.",
        ),
        (".\\dev.ps1 validate compare-statements -Env {env}",),
        (
            "Check that the source is available and provides Trial Balance, Balance Sheet and "
            "Profit & Loss reports, then compare again.",
        ),
        ".\\dev.ps1 validate compare-statements -Env {env}",
    ),
    # --- connection settings ------------------------------------------------------------
    _p(
        "LB-CON-001",
        "no_connection",
        "No connection yet",
        WARNING,
        "Nothing is connected in this environment yet.",
        ("A new environment.",),
        ("docs/pilot-runbook.md, step 3.",),
        ("Connect the source's companies (add -Origin backup for backup data).",),
        ".\\dev.ps1 connect -Env {env} -All",
    ),
    _p(
        "LB-CON-002",
        "connection_paused",
        "Scheduled syncs paused",
        INFO,
        "The worker doesn't sync this connection on a schedule; manual syncs still work.",
        ("New connections start paused, or it was paused on purpose.",),
        (".\\dev.ps1 status -Env {env}",),
        ("Activate it if scheduled syncs are wanted.",),
        ".\\dev.ps1 connect -Env {env} -All -Activate",
    ),
    # --- the system itself --------------------------------------------------------------
    _p(
        "LB-SYS-001",
        "unexpected_error",
        "Unexpected error",
        ERROR,
        "A command stopped with an error it doesn't explain itself (its type and a short "
        "message are shown, never values).",
        ("A bug, or a database or network problem.",),
        (".\\dev.ps1 logs api -Env {env} (shows errors without accounting values).",),
        ("Share the error line (type and code) with the developer.",),
        ".\\dev.ps1 status -Env {env}",
    ),
    _p(
        "LB-SYS-002",
        "job_gone",
        "Background job stopped without finishing",
        ERROR,
        "A background job stopped sending signs of life before it finished.",
        ("The api container restarted or the computer slept.",),
        (".\\dev.ps1 status -Env {env}",),
        ("Run the command again; a sync continues where it stopped.",),
        ".\\dev.ps1 report -Env {env}",
    ),
    _p(
        "LB-SYS-003",
        "database_unavailable",
        "Database busy or unavailable",
        ERROR,
        "The database didn't answer or a lock wasn't released in time.",
        ("The stack is starting or stopping, or another long job holds a lock.",),
        (".\\dev.ps1 status -Env {env}",),
        ("Wait for running jobs, then run the command again.",),
        ".\\dev.ps1 status -Env {env}",
    ),
)

BY_CODE: dict[str, Problem] = {p.code: p for p in PROBLEMS}
BY_KEY: dict[str, Problem] = {p.key: p for p in PROBLEMS}
# Validation check codes that share one problem.
_ALIASES = {
    "closing_not_supported": "check_not_supported",
    "year_end_balances_not_supported": "check_not_supported",
    "voucher_counts_not_supported": "check_not_supported",
    "stock_quantities_not_supported": "check_not_supported",
    "bill_outstanding_not_supported": "check_not_supported",
    "stock_values_not_compared": "not_compared",
    "bills_not_compared": "not_compared",
}
# Error types (from a stored error summary "Type: message") with their own problem.
_ERROR_TYPES = {
    "EntityLookupError": "LB-SYNC-006",
    "SourceUnresponsiveError": "LB-SYNC-005",
    "ChunkTooSlowError": "LB-SYNC-005",
    "ConnectError": "LB-SYNC-005",
    "ConnectTimeout": "LB-SYNC-005",
    "ReadTimeout": "LB-SYNC-005",
    "OperationalError": "LB-SYS-003",
    "SyncBusyError": "LB-SYNC-008",
}


def for_key(key: str) -> Problem:
    """The problem for a technical key or validation check code. Unknown keys (a check added
    without a catalogue entry) get a generic problem so output never breaks."""
    key = _ALIASES.get(key, key)
    if key in BY_KEY:
        return BY_KEY[key]
    return Problem(
        "LB-VAL-099", key, key.replace("_", " ").capitalize(), WARNING,
        "A check without a catalogue entry yet.", (), (), (), ".\\dev.ps1 report -Env {env}",
    )  # fmt: skip


def for_error(summary: str | None, default: str) -> Problem:
    """The problem for a stored error summary ("Type: message"): by its type, else
    `default` (a code)."""
    kind = (summary or "").split(":", 1)[0].strip()
    return BY_CODE[_ERROR_TYPES.get(kind, default)]


def title(key: str) -> str:
    """`Balances at year ends [year_end_mismatch, LB-VAL-006]`."""
    return for_key(key).label()
