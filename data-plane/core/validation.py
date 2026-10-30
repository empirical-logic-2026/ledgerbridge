"""Validation of one entity's books (VAL-001, VAL-002, VAL-005 to VAL-009; schema.md 5.2;
architecture 4.6).

Source-independent: the source's own figures arrive as `connectors.base.SourceBalances` and
`connectors.base.SourceControls`. Everything is computed **as of a date**: only vouchers
dated on or before it count, so post-dated vouchers simply fall outside earlier dates.

Checks (all exact by default; amounts within the connection's tolerance):
- every voucher balances; the trial balance balances at every year end and the as-of date;
- each ledger's balance equals the source's closing balance as of the date (the profit
  carrier with the period's profit) and at every financial year end before it;
- with controls: vouchers per month and voucher type equal the source's counts; each stock
  item's closing quantity equals the source's; each party's bill-wise outstanding equals
  the source's.

When raw records failed to transform, the report says how many failures are likely their
consequences, so the root cause is obvious (`root_cause`).

Issue messages are stored in the database (they may name vouchers and ledgers); nothing
here logs names or amounts.

Where it fits: `workers/validate.py` reads the source's figures through the connector and
runs a Validator after every sync (and on `validate`); the report is stored in
`validation_runs` / `validation_issues` and printed by the CLI. `workers/analyse.py`
(`validate analyse`) explains failures using the same balances (`ledger_balances`,
`at_stock_value`, `at_book_value`).
"""

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from connectors.base import SourceBalances, SourceControls, SourceStatements
from core import statements
from core.dates import financial_year_ends
from core.models import accounting as A  # noqa: N812
from core.models.base import utcnow
from core.models.source import RawRecord
from core.models.system import Connection, ValidationIssue, ValidationRun
from core.names import NORMALISED, NameIndex, close_match, differences
from core.problems import title
from core.statement_differences import Summary

ZERO = Decimal(0)
PROFIT_NATURES = ("income", "expense")
# Failures that follow from records missing in the accounting tables (raw records that
# failed to transform): a missing voucher or ledger changes balances and counts.
CONSEQUENCES = (
    "closing_mismatch",
    "profit_carrier_mismatch",
    "year_end_mismatch",
    "tb_unbalanced",
    "voucher_count_mismatch",
    "stock_quantity_mismatch",
    "bills_mismatch",
    "statement_mismatch",
    "stock_value_mismatch",
)

# Issue codes by check. An earlier issue is resolved only when this run ran its check and
# didn't find it again (`_store`). *_READ: the check was attempted but the source's figures
# couldn't be read (or aren't offered), so only those notes are covered; *_COMPARED: the
# comparison ran.
ALWAYS_CHECKED = ("voucher_unbalanced", "opening_difference", "tb_unbalanced")
CLOSING_READ = ("closing_unavailable", "closing_not_supported")
CLOSING_COMPARED = (
    *CLOSING_READ, "closing_mismatch", "profit_carrier_mismatch", "ledger_missing",
    "stock_ledger_at_stock_value", "foreign_ledgers_at_book_value",
)  # fmt: skip
YEAR_END_READ = ("year_end_balances_unavailable", "year_end_balances_not_supported")
YEAR_END_COMPARED = (*YEAR_END_READ, "year_end_mismatch")
COUNTS_READ = ("voucher_counts_unavailable", "voucher_counts_not_supported")
COUNTS_COMPARED = (*COUNTS_READ, "voucher_count_mismatch", "voucher_type_names_differ")
STOCK_READ = ("stock_quantities_unavailable", "stock_quantities_not_supported")
STOCK_COMPARED = (*STOCK_READ, "stock_quantity_mismatch", "stock_values_not_compared")
BILLS_READ = (
    "bill_outstanding_unavailable",
    "bill_outstanding_not_supported",
    "bills_not_compared",
)
BILLS_COMPARED = (*BILLS_READ, "bills_mismatch")
STATEMENTS_READ = ("statements_unavailable", "statements_not_supported")
STATEMENTS_COMPARED = (
    *STATEMENTS_READ,
    "statement_mismatch",
    "stock_value_mismatch",
    "statement_taken_from_source",
)
# Codes from no known check (older runs): resolved as before when not found again.
KNOWN_CODES = frozenset(
    (*ALWAYS_CHECKED, *CLOSING_COMPARED, *YEAR_END_COMPARED, *COUNTS_COMPARED,
     *STOCK_COMPARED, *BILLS_COMPARED, *STATEMENTS_COMPARED)
)  # fmt: skip


def _read(figures: object) -> bool:
    """Whether the source's figures for a check were read (not missing or an error)."""
    return figures is not None and not isinstance(figures, Exception)


@dataclass
class RootCause:
    """Raw records of the entity that failed to transform, and the failures that are
    likely their consequences (counts only)."""

    failed_records: Counter[str] = field(default_factory=Counter)  # object type -> count
    missing_ledgers: int = 0  # ledger_missing findings
    vouchers_for_unknown_ledger: int = 0
    consequences: Counter[str] = field(default_factory=Counter)  # check code -> count

    @property
    def any(self) -> bool:
        return bool(self.failed_records or self.missing_ledgers)

    def lines(self) -> list[str]:
        """Plain-language explanation (counts and check codes only)."""
        if not self.any:
            return []
        out = []
        if self.missing_ledgers:
            out.append(
                f"{self.missing_ledgers:,} ledgers in the source are missing here"
                + (
                    f" ({self.failed_records['ledger']:,} ledger records failed to transform)"
                    if self.failed_records.get("ledger")
                    else ""
                )
            )
        if self.vouchers_for_unknown_ledger:
            out.append(
                f"{self.vouchers_for_unknown_ledger:,} vouchers failed to transform because they "
                "refer to a ledger that is missing"
            )
        others = {k: v for k, v in self.failed_records.items() if k != "ledger"}
        if others:
            listed = ", ".join(f"{kind} {n:,}" for kind, n in sorted(others.items()))
            out.append(f"raw records that failed to transform: {listed}")
        total = sum(self.consequences.values())
        if total:
            listed = ", ".join(
                f"{title(code)} {n:,}" for code, n in sorted(self.consequences.items())
            )
            out.append(
                f"{total:,} other failures ({listed}) are likely consequences: fix the records "
                "that failed to transform first (summary shows why they failed), then run "
                "transform retry"
            )
        return out


@dataclass(frozen=True)
class Finding:
    check_code: str
    severity: str  # error / warning / info
    object_type: str
    object_id: str | None
    expected: Decimal | None
    actual: Decimal | None
    message: str

    @property
    def key(self) -> tuple[str, str, str | None]:
        return (self.check_code, self.object_type, self.object_id)


@dataclass
class ValidationReport:
    validation_run_id: int
    entity_id: int
    entity_name: str
    as_of: date
    status: str = "running"
    checks_passed: int = 0
    checks_failed: int = 0
    findings: list[Finding] = field(default_factory=list)
    opening_difference: Decimal = ZERO
    root_cause: RootCause = field(default_factory=RootCause)
    # Unbalanced vouchers by voucher base type (sales, journal, ...): counts only.
    unbalanced_by_type: Counter[str] = field(default_factory=Counter)
    # What unbalanced vouchers have in common (counts): "with inventory lines", ...
    unbalanced_details: Counter[str] = field(default_factory=Counter)
    # Statement lines that differ from the source's, pilot-safe (core/statement_differences).
    statement_summary: list[str] = field(default_factory=list)

    @property
    def failed_by_code(self) -> Counter[str]:
        return Counter(f.check_code for f in self.findings if f.severity == "error")


def counted_godown():  # noqa: ANN201 - a SQL condition
    """Inventory lines whose godown counts in stock balances: no godown, or one that isn't
    "our stock with a third party" (a job worker's location; ADR-031). Needs an outer join
    of `godowns` on the line's godown."""
    return or_(A.Godown.id.is_(None), A.Godown.holding != "ours_with_third_party")


@dataclass
class _LedgerBalance:
    id: int
    name: str
    source_key: str
    connection_id: int
    nature: str | None
    opening: Decimal
    balance: Decimal  # opening + effective lines dated on or before as_of


def at_stock_value(
    ours: Mapping[str, Decimal], source: SourceBalances, tolerance: Decimal = ZERO
) -> set[str]:
    """The stock ledgers (source keys) the source reports at its closing stock value rather
    than at their own opening and postings: their balances here differ from the source's,
    and the source's total equals its closing stock value as of the date (VAL-012). Used by
    validation and by `validate analyse`, so both treat them alike."""
    mine = {key: balance for key, balance in ours.items() if key in source.stock_ledgers}
    if not mine or source.closing_stock is None:
        return set()
    theirs = sum((source.ledgers.get(key, ZERO) for key in mine), ZERO)
    if abs(theirs - sum(mine.values(), ZERO)) <= tolerance:
        return set()
    if abs(theirs - source.closing_stock) > tolerance:
        return set()
    return set(mine)


def at_book_value(
    ours: Mapping[str, Decimal], source: SourceBalances, tolerance: Decimal = ZERO
) -> dict[frozenset[str], tuple[Decimal, Decimal]]:
    """Foreign-currency ledgers compared with the source's book value (VAL-013): each set
    the source gives a book value for -> (its book value, ours). The source's own closing
    balance of such a ledger is revalued at current rates; its books keep the amounts
    entered. Used by validation and `validate analyse` alike."""
    out = {}
    for keys, book in source.book_values.items():
        mine = [ours[k] for k in keys if k in ours]
        if mine:
            out[keys] = (book, sum(mine, ZERO))
    return out


def _period_profit(ledgers: list[_LedgerBalance], source: SourceBalances) -> Decimal:
    """The period's profit as the profit carrier needs it: income and expense ledgers, less
    the stock's change in value (debit positive: a positive figure is a loss)."""
    profit = sum((x.balance for x in ledgers if x.nature in PROFIT_NATURES), ZERO)
    if source.closing_stock is not None and source.opening_stock is not None:
        profit -= source.closing_stock - source.opening_stock
    return profit


def _kinds(pairs: set[tuple[str, str]]) -> str:
    """Kinds of difference between pairs of names, counted (never the names)."""
    kinds = Counter(k for pair in pairs for k in differences(*pair))
    return ", ".join(f"{k} {n:,}" for k, n in sorted(kinds.items()))


class Validator:
    def __init__(
        self,
        session: Session,
        entity_id: int,
        as_of: date,
        tolerance: Decimal = ZERO,
        connection_id: int | None = None,
    ) -> None:
        self.session = session
        self.entity = session.get_one(A.Entity, entity_id)
        self.as_of = as_of
        self.tolerance = tolerance
        self.connection_id = connection_id
        self.findings: list[Finding] = []
        self.passed = 0
        # Issue codes whose checks this run ran: only their earlier issues can be resolved.
        self.covered: set[str] = set(ALWAYS_CHECKED)

    # --- driver -----------------------------------------------------------------------

    def run(
        self,
        source: SourceBalances | Exception | None,
        sync_run_id: int | None = None,
        controls: SourceControls | None = None,
    ) -> ValidationReport:
        run = ValidationRun(
            entity_id=self.entity.id,
            sync_run_id=sync_run_id,
            as_of=self.as_of,
            started_at=utcnow(),
            status="running",
            thorough=controls is not None,
        )
        self.session.add(run)
        self.session.flush()
        report = ValidationReport(run.id, self.entity.id, self.entity.name, self.as_of)

        ledgers = self._ledger_balances(self.as_of)
        report.unbalanced_by_type, report.unbalanced_details = self._vouchers()
        # Our ledger openings' total: the trial balance must total exactly that.
        report.opening_difference = self._opening_difference(ledgers, source)
        self._trial_balance(report.opening_difference)
        self._closing(ledgers, source)
        self._cover(CLOSING_COMPARED if _read(source) else CLOSING_READ)
        if controls is not None:
            for year_end, balances in sorted(controls.year_ends.items()):
                self._closing(self._ledger_balances(year_end), balances, year_end)
                self._cover(YEAR_END_COMPARED if _read(balances) else YEAR_END_READ)
            self._voucher_counts(controls.voucher_counts)
            self._cover(COUNTS_COMPARED if _read(controls.voucher_counts) else COUNTS_READ)
            self._stock_quantities(controls.stock_quantities)
            self._cover(STOCK_COMPARED if _read(controls.stock_quantities) else STOCK_READ)
            self._bills(controls.bill_outstanding, controls.opening_bills)
            self._cover(self._bills_covered(controls))
            if controls.statements:
                report.statement_summary = self._statements(controls.statements)
                read = all(isinstance(s, SourceStatements) for s in controls.statements.values())
                self._cover(STATEMENTS_COMPARED if read else STATEMENTS_READ)
        report.root_cause = self._root_cause()

        report.findings = self.findings
        report.checks_passed = self.passed
        report.checks_failed = sum(1 for f in self.findings if f.severity == "error")
        report.status = "failed" if report.checks_failed else "passed"
        self._store(run, report)
        return report

    def _fail(self, finding: Finding) -> None:
        """Records a finding: a failed check (error), a warning or a note (info)."""
        self.findings.append(finding)

    def _statements(self, figures: Mapping[date, SourceStatements | Exception]) -> list[str]:
        """VAL-015, RPT-012 (ADR-040): at each date, the source's stock value against the
        one stored for it, then our Trial Balance, Profit & Loss and Balance Sheet against
        the source's own, line by line and in total. Both sides are stored for the views
        (core/statements.py). Returns the pilot-safe summary of the lines that differ."""
        if self.connection_id is None:
            return []
        summary = Summary(self.tolerance)
        connection = self.session.get(Connection, self.connection_id)
        origin = str((connection.config if connection else {}).get("origin", "live"))
        for on, source in sorted(figures.items()):
            if not isinstance(source, SourceStatements):
                self._unavailable("statements", source, f"at {on}")
                continue
            result = statements.refresh(
                self.session, self.entity.id, self.connection_id, origin, source, self.tolerance
            )
            self._stock_value(on, result.stock_before, source)
            summary.add(self.session, self.entity.id, source, result)
            # A line taken from the source where ours differs is an open difference, not a
            # pass (ADR-043): a warning, counted in neither passed nor failed.
            self.passed += result.compared - len(result.differences) - len(result.taken)
            for taken in result.taken:
                self._fail(
                    Finding(
                        "statement_taken_from_source",
                        "warning",
                        "statement",
                        f"{taken.statement}@{on.isoformat()}:{taken.key}"[:64],
                        taken.source,
                        taken.ours,
                        f"{taken.statement.replace('_', ' ').capitalize()} as of {on}: "
                        f"'{taken.label}' is taken from the source; ours differs.",
                    )
                )
            for difference in result.differences:
                self._fail(
                    Finding(
                        "statement_mismatch",
                        "error",
                        "statement",
                        f"{difference.statement}@{on.isoformat()}:{difference.key}"[:64],
                        difference.source,
                        difference.ours,
                        f"{difference.statement.replace('_', ' ').capitalize()} as of {on}: "
                        f"'{difference.label}' differs from the source.",
                    )
                )
        return summary.lines()

    def _stock_value(
        self,
        on: date,
        stored: tuple[Decimal | None, Decimal | None] | None,
        source: SourceStatements,
    ) -> None:
        """The stock value stored for a date (from an earlier read) against the source's
        now; nothing to compare the first time a date is read."""
        if stored is None:
            return
        same = all(
            (a is None and b is None)
            or (a is not None and b is not None and abs(a - b) <= self.tolerance)
            for a, b in zip(stored, (source.opening_stock, source.closing_stock), strict=True)
        )
        if same:
            self.passed += 1
            return
        self._fail(
            Finding(
                "stock_value_mismatch",
                "error",
                "entity",
                f"{self.entity.id}@{on.isoformat()}",
                source.closing_stock,
                stored[1],
                f"The source's stock value as of {on} differs from the one stored for that date.",
            )
        )

    def _cover(self, codes: tuple[str, ...]) -> None:
        self.covered.update(codes)

    def _bills_covered(self, controls: SourceControls) -> tuple[str, ...]:
        """The bill codes this run covers: bills are compared only as of today or later."""
        if self.as_of < date.today():
            return ("bills_not_compared",)
        if _read(controls.bill_outstanding) and _read(controls.opening_bills):
            return BILLS_COMPARED
        return BILLS_READ

    def _note(self, check_code: str, object_id: str, message: str) -> None:
        """An information finding about the entity (no amounts)."""
        self._fail(Finding(check_code, "info", "entity", object_id, None, None, message))

    # --- our side ---------------------------------------------------------------------

    def ledger_balances(self, as_of: date) -> list[_LedgerBalance]:
        """Each ledger's opening and balance as of a date (used by `validate analyse`)."""
        return self._ledger_balances(as_of)

    def _ledger_balances(self, as_of: date) -> list[_LedgerBalance]:
        movements = (
            select(A.VoucherLine.ledger_id, func.sum(A.VoucherLine.amount).label("movement"))
            .where(
                A.VoucherLine.entity_id == self.entity.id,
                A.VoucherLine.is_effective.is_(True),
                A.VoucherLine.voucher_date <= as_of,
            )
            .group_by(A.VoucherLine.ledger_id)
            .subquery()
        )
        rows = self.session.execute(
            select(
                A.Ledger.id,
                A.Ledger.name,
                A.Ledger.source_key,
                A.Ledger.connection_id,
                A.AccountGroup.nature,
                A.Ledger.opening_balance,
                func.coalesce(movements.c.movement, 0),
            )
            .join(A.AccountGroup, A.AccountGroup.id == A.Ledger.group_id)
            .outerjoin(movements, movements.c.ledger_id == A.Ledger.id)
            .where(A.Ledger.entity_id == self.entity.id, A.Ledger.is_deleted.is_(False))
        ).all()
        return [
            _LedgerBalance(i, n, k, c, nature, Decimal(o), Decimal(o) + Decimal(m))
            for i, n, k, c, nature, o, m in rows
        ]

    # --- checks -----------------------------------------------------------------------

    def _vouchers(self) -> tuple[Counter[str], Counter[str]]:
        """VAL-001: every effective voucher's lines sum to zero. Returns the unbalanced ones
        per voucher type (the source's standard type, e.g. "Sales Order"; for a type whose
        standard type isn't known, "custom (<base type>)"), and what they have in common."""
        sums = self.session.execute(
            select(A.VoucherLine.voucher_id, func.sum(A.VoucherLine.amount), func.count())
            .where(A.VoucherLine.entity_id == self.entity.id, A.VoucherLine.is_effective.is_(True))
            .group_by(A.VoucherLine.voucher_id)
        ).all()
        unbalanced = {vid: Decimal(total) for vid, total, _ in sums if Decimal(total) != ZERO}
        single = {vid for vid, total, lines in sums if vid in unbalanced and lines == 1}
        self.passed += len(sums) - len(unbalanced)
        by_type: Counter[str] = Counter()
        details: Counter[str] = Counter()
        if not unbalanced:
            return by_type, details
        ids = list(unbalanced)
        with_inventory: set[int] = set()
        for start in range(0, len(ids), 5_000):
            with_inventory.update(
                self.session.scalars(
                    select(A.InventoryLine.voucher_id)
                    .where(A.InventoryLine.voucher_id.in_(ids[start : start + 5_000]))
                    .distinct()
                )
            )
        details["with inventory lines"] = len(with_inventory)
        details["with a single effective line"] = len(single)
        vouchers = self.session.execute(
            select(
                A.Voucher.id,
                A.Voucher.voucher_number,
                A.Voucher.voucher_date,
                A.VoucherType.standard_type,
                A.VoucherType.base_type,
                A.Voucher.is_post_dated,
            )
            .join(A.VoucherType, A.VoucherType.id == A.Voucher.voucher_type_id)
            .where(A.Voucher.id.in_(ids))
        ).all()
        for vid, number, voucher_date, standard, base_type, post_dated in vouchers:
            by_type[standard or f"custom ({base_type})"] += 1
            if post_dated:
                details["post-dated"] += 1
            self._fail(
                Finding(
                    "voucher_unbalanced",
                    "error",
                    "voucher",
                    str(vid),
                    ZERO,
                    unbalanced[vid],
                    f"Voucher {number or vid} dated {voucher_date} doesn't balance.",
                )
            )
        return by_type, +details

    def _opening_difference(
        self, ledgers: list[_LedgerBalance], source: SourceBalances | Exception | None
    ) -> Decimal:
        """The source's own difference in opening balances: its ledger openings and opening
        stock value at the books' beginning (Tally shows the difference when they don't
        total zero; checked on the test company, 2026-10-15). The warning fires only when
        the source itself shows one; our openings are compared ledger by ledger through the
        closing balances. Without the source's figures, ours (ledgers and opening stock) are
        used. Returns our ledger openings' total: the trial balance must total exactly that."""
        ours = sum((ledger.opening for ledger in ledgers), ZERO)
        theirs = None
        if isinstance(source, SourceBalances) and source.opening_difference is not None:
            theirs = source.opening_difference
            where = "The source shows a difference in opening balances"
        else:
            stock = self.session.scalar(
                select(func.coalesce(func.sum(A.Item.opening_value), 0)).where(
                    A.Item.entity_id == self.entity.id, A.Item.is_deleted.is_(False)
                )
            )
            theirs = ours + Decimal(stock or 0)
            where = "Opening balances here don't total zero (the source's couldn't be read)"
        if abs(theirs) <= self.tolerance:
            self.passed += 1
        else:
            self._fail(
                Finding(
                    "opening_difference",
                    "warning",
                    "entity",
                    str(self.entity.id),
                    ZERO,
                    theirs,
                    f"{where}: ledger openings and opening stock don't total zero. Correct "
                    "the opening balances in the source books.",
                )
            )
        return ours

    def _trial_balance(self, opening_difference: Decimal) -> None:
        """The trial balance totals the opening difference at every year end and at as_of,
        i.e. the movements balance."""
        dates = [
            *financial_year_ends(self.entity.books_from, self.entity.fy_start_month, self.as_of),
            self.as_of,
        ]
        for on in dates:
            total = sum((ledger.balance for ledger in self._ledger_balances(on)), ZERO)
            if total == opening_difference:
                self.passed += 1
                continue
            self._fail(
                Finding(
                    "tb_unbalanced",
                    "error",
                    "entity",
                    f"{self.entity.id}@{on.isoformat()}",
                    opening_difference,
                    total,
                    f"Trial balance as of {on} doesn't balance.",
                )
            )

    def _closing(
        self,
        ledgers: list[_LedgerBalance],
        source: SourceBalances | Exception | None,
        year_end: date | None = None,
    ) -> None:
        """VAL-002: each ledger's balance matches the source's own closing balance; with
        `year_end`, at that financial year end (missing ledgers are reported once, as of the
        validation date)."""
        entity_id = str(self.entity.id)
        if year_end is not None:
            entity_id = f"{self.entity.id}@{year_end.isoformat()}"
        if not isinstance(source, SourceBalances):
            self._closing_unreadable(source, year_end, entity_id)
            return
        ours = [
            ledger
            for ledger in ledgers
            if self.connection_id is None or ledger.connection_id == self.connection_id
        ]
        profit = _period_profit(ours, source)
        at_stock_value = self._at_stock_value(ours, source, year_end or self.as_of, entity_id)
        at_book = self._at_book_value(ours, source, year_end, entity_id)
        seen = set()
        for ledger in ours:
            seen.add(ledger.source_key)
            theirs = source.ledgers.get(ledger.source_key)
            if theirs is None and year_end is not None:
                continue  # reported as ledger_missing as of the validation date
            if ledger.source_key in at_stock_value:
                self.passed += 1  # compared with the source's closing stock value
                continue
            if ledger.source_key in at_book:
                continue  # compared with the source's book value (_at_book_value)
            if theirs is None:
                self._fail(
                    Finding(
                        "ledger_missing", "error", "ledger", str(ledger.id), None,
                        ledger.balance, f"Ledger '{ledger.name}' isn't in the source.",
                    )
                )  # fmt: skip
                continue
            self._compare_closing(ledger, theirs, profit, source, year_end)
        if year_end is None:
            self._missing_here(source, seen)

    def _closing_unreadable(
        self, source: Exception | None, year_end: date | None, entity_id: str
    ) -> None:
        """No closing balances from the source: not offered (a note) or not readable."""
        if year_end is not None:
            self._unavailable("year_end_balances", source, f"at {year_end}")
        elif source is None:
            self._note(
                "closing_not_supported",
                entity_id,
                "The source can't report closing balances; closing checks skipped.",
            )
        else:
            self._fail(
                Finding(
                    "closing_unavailable", "error", "entity", entity_id, None, None,
                    f"Closing balances couldn't be read from the source "
                    f"({type(source).__name__}); closing checks didn't run.",
                )
            )  # fmt: skip

    def _compare_closing(
        self,
        ledger: _LedgerBalance,
        theirs: Decimal,
        profit: Decimal,
        source: SourceBalances,
        year_end: date | None,
    ) -> None:
        """One ledger against the source's closing balance; the profit carrier (e.g. Tally's
        Profit & Loss A/c) with the period's profit added."""
        if ledger.source_key in source.profit_carriers:
            expected_ours = ledger.balance + profit
            code = "profit_carrier_mismatch"
            message = (
                f"Ledger '{ledger.name}' (carries the computed profit) doesn't reconcile: "
                "its posted balance plus the profit for the period differs from the source."
            )
        else:
            expected_ours = ledger.balance
            code = "closing_mismatch"
            message = f"Ledger '{ledger.name}' closing balance differs from the source."
        object_id = str(ledger.id)
        if year_end is not None:
            code, object_id = "year_end_mismatch", f"{ledger.id}@{year_end.isoformat()}"
            message = f"{message[:-1]} at the year end {year_end}."
        if abs(theirs - expected_ours) <= self.tolerance:
            self.passed += 1
        else:
            self._fail(Finding(code, "error", "ledger", object_id, theirs, expected_ours, message))

    def _missing_here(self, source: SourceBalances, seen: set[str]) -> None:
        """Ledgers the source has that aren't here."""
        for key, theirs in source.ledgers.items():
            if key not in seen:
                self._fail(
                    Finding(
                        "ledger_missing", "error", "source_ledger", key[:64], theirs, None,
                        "A ledger in the source isn't here (sync it, or check for a failure).",
                    )
                )  # fmt: skip

    def _at_book_value(
        self,
        ours: list[_LedgerBalance],
        source: SourceBalances,
        year_end: date | None,
        object_id: str,
    ) -> set[str]:
        """Foreign-currency ledgers: compared, per set the source gives a book value for,
        with that book value instead of their revalued closing balances (VAL-013; pilot
        2026-10-16: Tally's Ledger Vouchers equalled ours while its closing balance was at
        current rates). Returns the ledgers compared this way."""
        found = at_book_value({x.source_key: x.balance for x in ours}, source)
        if not found:
            return set()
        by_key = {x.source_key: x for x in ours}
        on = year_end or self.as_of
        for keys, (book, mine) in found.items():
            if abs(book - mine) <= self.tolerance:
                self.passed += 1
                continue
            first = by_key[min(k for k in keys if k in by_key)]
            code = "year_end_mismatch" if year_end is not None else "closing_mismatch"
            suffix = f"@{year_end.isoformat()}" if year_end is not None else ""
            what = (
                f"Ledger '{first.name}'"
                if len(keys) == 1
                else f"{len(keys)} foreign-currency ledgers of one group (with '{first.name}')"
            )
            self._fail(
                Finding(
                    code, "error", "ledger", f"{first.id}{suffix}", book, mine,
                    f"{what}: the balance differs from the source's book value as of {on}.",
                )
            )  # fmt: skip
        self._note(
            "foreign_ledgers_at_book_value",
            object_id,
            "Foreign-currency ledgers were compared with the source's book value (its "
            "trial balance), not with their closing balances at current rates.",
        )
        return set().union(*found)

    def _at_stock_value(
        self, ours: list[_LedgerBalance], source: SourceBalances, on: date, object_id: str
    ) -> set[str]:
        """Stock ledgers the source reports at its closing stock value rather than at their
        own opening and postings (pilot, 2026-10-15: in two companies the Stock-in-Hand
        ledger's balance was the closing stock value at every date; on the test company the
        ledger keeps its own opening). When the stock ledgers' balances here differ from the
        source's and the source's total equals its closing stock value as of the date, they
        are compared with that value (a note says so); otherwise ledger by ledger."""
        mine = at_stock_value({x.source_key: x.balance for x in ours}, source, self.tolerance)
        if not mine:
            return set()
        theirs = sum((source.ledgers.get(key, ZERO) for key in mine), ZERO)
        self._fail(
            Finding(
                "stock_ledger_at_stock_value", "info", "entity", object_id,
                source.closing_stock, theirs,
                f"Ledgers under the source's stock group carry its closing stock value as of "
                f"{on}, not their own postings: compared with that value.",
            )
        )  # fmt: skip
        return set(mine)

    # --- controls: counts, stock, bills (VAL-005 to VAL-008) ----------------------------

    def _unavailable(self, what: str, problem: Exception | None, detail: str = "") -> None:
        """A control the source couldn't provide: an error if it failed, a note if the
        source doesn't offer it."""
        where = f" {detail}" if detail else ""
        if problem is None:
            self._note(
                f"{what}_not_supported",
                str(self.entity.id),
                f"The source can't report {what.replace('_', ' ')}{where}; check skipped.",
            )
            return
        object_id = f"{self.entity.id}{where.replace(' at ', '@')}"[:64]
        self._fail(
            Finding(
                f"{what}_unavailable", "error", "entity", object_id, None, None,
                f"The source's {what.replace('_', ' ')}{where} couldn't be read "
                f"({type(problem).__name__}); this check didn't run.",
            )
        )  # fmt: skip

    def _voucher_counts(self, theirs: Mapping[tuple[date, str], int] | Exception | None) -> None:
        """VAL-005: vouchers per month and voucher type equal the source's own counts
        (cancelled and optional vouchers included; deleted ones excluded)."""
        if theirs is None or isinstance(theirs, Exception):
            self._unavailable("voucher_counts", theirs)
            return
        rows = self.session.execute(
            select(A.VoucherType.id, A.VoucherType.name, A.VoucherType.is_deleted).where(
                A.VoucherType.entity_id == self.entity.id
            )
        ).all()
        types = {type_id: name for type_id, name, _ in rows}
        # A finding names the type by id: when a deleted type and a live one share a name,
        # the live one (a type deleted and created again keeps its name).
        ids = {name: type_id for type_id, name, deleted in rows if deleted}
        ids.update({name: type_id for type_id, name, deleted in rows if not deleted})
        ours: Counter[tuple[date, str]] = Counter()
        for voucher_date, type_id, count in self.session.execute(
            select(A.Voucher.voucher_date, A.Voucher.voucher_type_id, func.count())
            .where(
                A.Voucher.entity_id == self.entity.id,
                A.Voucher.is_deleted.is_(False),
                A.Voucher.voucher_date <= self.as_of,
            )
            .group_by(A.Voucher.voucher_date, A.Voucher.voucher_type_id)
        ):
            ours[(voucher_date.replace(day=1), types.get(type_id, ""))] += count
        counted = self._by_our_type_names(theirs, ids)
        for month, kind in sorted(set(ours) | set(counted)):
            expected, actual = counted.get((month, kind), 0), ours.get((month, kind), 0)
            if expected == actual:
                self.passed += 1
                continue
            self._fail(
                Finding(
                    "voucher_count_mismatch",
                    "error",
                    "voucher_month",
                    f"{month:%Y-%m}:{ids.get(kind, 'unknown type')}"[:64],
                    Decimal(expected),
                    Decimal(actual),
                    f"{month:%Y-%m}, voucher type '{kind}': {actual} vouchers here, "
                    f"{expected} in the source.",
                )
            )

    def _by_our_type_names(
        self, theirs: Mapping[tuple[date, str], int], names: Iterable[str]
    ) -> Counter[tuple[date, str]]:
        """The source's counts under our voucher types' names, matched by the transform's
        name rules (core/names.py): a source that writes a type's name differently in its
        counts than in its vouchers is still compared with that type (pilot 2026-10-30: a
        name with two spaces in a row, every voucher of the type counted as another's).
        Such names are noted with the kinds of difference only, and so are names the rules
        don't match that are close to one of ours (their counts still differ)."""
        names = list(names)
        index = NameIndex.build((name, name) for name in names)
        keyed: Counter[tuple[date, str]] = Counter()
        matched: set[tuple[str, str]] = set()
        near: set[tuple[str, str]] = set()
        for (month, kind), count in theirs.items():
            found = index.resolve(kind)
            if found.how == NORMALISED:
                matched.add((kind, found.value))
            elif not found.found:
                close, _ = close_match(kind, names)
                if close is not None:
                    near.add((kind, close))
            keyed[(month, found.value if found.found else kind)] += count
        parts = [
            f"{len(pairs):,} {what} ({_kinds(pairs)})"
            for pairs, what in (
                (matched, "compared with the type each matches by the name rules"),
                (near, "not matched: close to one of ours but differing by more"),
            )
            if pairs
        ]
        if parts:
            self._note(
                "voucher_type_names_differ",
                str(self.entity.id),
                "The source writes voucher type names differently in its voucher counts than "
                f"in its vouchers: {'; '.join(parts)}.",
            )
        return keyed

    def _stock_quantities(self, theirs: Mapping[str, Decimal] | Exception | None) -> None:
        """VAL-006: each stock item's closing quantity (opening plus movements of effective
        vouchers up to the date) equals the source's. Values depend on the source's
        valuation method and aren't compared item by item (the total closing stock is part
        of the profit check)."""
        if theirs is None or isinstance(theirs, Exception):
            self._unavailable("stock_quantities", theirs)
            return
        movements = (
            select(A.InventoryLine.item_id, func.sum(A.InventoryLine.stock_quantity).label("moved"))
            .join(A.Voucher, A.Voucher.id == A.InventoryLine.voucher_id)
            .join(A.VoucherType, A.VoucherType.id == A.Voucher.voucher_type_id)
            .outerjoin(A.Godown, A.Godown.id == A.InventoryLine.godown_id)
            .where(
                A.InventoryLine.entity_id == self.entity.id,
                A.InventoryLine.voucher_date <= self.as_of,
                A.Voucher.is_deleted.is_(False),
                A.Voucher.is_cancelled.is_(False),
                A.Voucher.is_optional.is_(False),
                A.VoucherType.moves_stock.is_(True),  # orders and memorandum don't
                counted_godown(),  # not at a job worker's location
            )
            .group_by(A.InventoryLine.item_id)
            .subquery()
        )
        ours = {
            key: (item_id, name, Decimal(opening) + Decimal(moved))
            for item_id, key, name, opening, moved in self.session.execute(
                select(
                    A.Item.id,
                    A.Item.source_key,
                    A.Item.name,
                    A.Item.opening_qty,
                    func.coalesce(movements.c.moved, 0),
                )
                .outerjoin(movements, movements.c.item_id == A.Item.id)
                .where(A.Item.entity_id == self.entity.id, A.Item.is_deleted.is_(False))
            )
        }
        for key in sorted(set(ours) | set(theirs)):
            item_id, name, actual = ours.get(key, (None, None, None))
            expected = theirs.get(key)
            if actual is not None and expected is not None and actual == expected:
                self.passed += 1
                continue
            self._fail(
                Finding(
                    "stock_quantity_mismatch",
                    "error",
                    "item" if item_id is not None else "source_item",
                    str(item_id) if item_id is not None else key[:64],
                    expected,
                    actual,
                    f"Stock item '{name}' closing quantity differs from the source."
                    if name is not None
                    else "A stock item in the source isn't here.",
                )
            )
        if ours or theirs:
            self._note(
                "stock_values_not_compared",
                str(self.entity.id),
                "Stock values per item depend on the source's valuation method and aren't "
                "compared item by item; the total closing stock is part of the profit check.",
            )

    def _bills(
        self,
        outstanding: Mapping[str, Decimal] | Exception | None,
        opening: Mapping[str, Decimal] | Exception | None,
    ) -> None:
        """VAL-007: each party's bill-wise outstanding (its opening bills plus every bill
        allocation of effective vouchers, 'on account' excluded) equals the source's.

        The source reports bills as outstanding now, whatever the as-of date, so the check
        runs only for validations as of today or later and counts every voucher."""
        if self.as_of < date.today():
            self._note(
                "bills_not_compared",
                str(self.entity.id),
                "Bill-wise outstanding is only compared as of today: the source reports "
                "bills as outstanding now.",
            )
            return
        if not isinstance(outstanding, Mapping):
            self._unavailable("bill_outstanding", outstanding)
            return
        if not isinstance(opening, Mapping):
            self._unavailable("bill_outstanding", opening)
            return
        ours: Counter[str] = Counter()
        ledger_ids: dict[str, int] = {}
        for ledger_id, name, total in self.session.execute(
            select(A.Ledger.id, A.Ledger.name, func.sum(A.BillAllocation.amount))
            .join(A.VoucherLine, A.VoucherLine.ledger_id == A.Ledger.id)
            .join(A.BillAllocation, A.BillAllocation.voucher_line_id == A.VoucherLine.id)
            .where(
                A.Ledger.entity_id == self.entity.id,
                A.VoucherLine.is_effective.is_(True),
                A.BillAllocation.bill_type != "on_account",
            )
            .group_by(A.Ledger.id, A.Ledger.name)
        ):
            ours[name] += Decimal(total)
            ledger_ids[name] = ledger_id
        parties = (
            set(ours)
            | {p for p, v in outstanding.items() if v}
            | {p for p, v in opening.items() if v}
        )
        for party in sorted(parties):
            expected = Decimal(outstanding.get(party, ZERO))
            actual = Decimal(opening.get(party, ZERO)) + ours.get(party, ZERO)
            if abs(expected - actual) <= self.tolerance:
                self.passed += 1
                continue
            known = party in ledger_ids
            self._fail(
                Finding(
                    "bills_mismatch",
                    "error",
                    "ledger" if known else "source_party",
                    str(ledger_ids[party]) if known else party[:64],
                    expected,
                    actual,
                    f"Bill-wise outstanding of '{party}' differs from the source.",
                )
            )

    def _root_cause(self) -> RootCause:
        """Failed raw records of this entity and the failures likely caused by them."""
        cause = RootCause()
        keys = select(A.EntitySource.source_entity_key).where(
            A.EntitySource.entity_id == self.entity.id
        )
        conditions = [RawRecord.source_entity_key.in_(keys), RawRecord.process_status == "failed"]
        if self.connection_id is not None:
            conditions.append(RawRecord.connection_id == self.connection_id)
        for object_type, count in self.session.execute(
            select(RawRecord.object_type, func.count())
            .where(*conditions)
            .group_by(RawRecord.object_type)
        ):
            cause.failed_records[object_type] = count
        cause.vouchers_for_unknown_ledger = (
            self.session.scalar(
                select(func.count()).where(
                    *conditions, RawRecord.process_error.like("%unknown ledger%")
                )
            )
            or 0
        )
        errors = Counter(f.check_code for f in self.findings if f.severity == "error")
        cause.missing_ledgers = errors.get("ledger_missing", 0)
        if cause.any:
            cause.consequences = Counter({c: errors[c] for c in CONSEQUENCES if errors.get(c)})
        return cause

    # --- storage ----------------------------------------------------------------------

    def _store(self, run: ValidationRun, report: ValidationReport) -> None:
        now = utcnow()
        for f in report.findings:
            self.session.add(
                ValidationIssue(
                    validation_run_id=run.id,
                    check_code=f.check_code,
                    severity=f.severity,
                    object_type=f.object_type,
                    object_id=f.object_id,
                    expected_value=f.expected,
                    actual_value=f.actual,
                    message=f.message,
                    created_at=now,
                    updated_at=now,
                )
            )
        # Problems from earlier runs that this run no longer finds are resolved.
        current = {f.key for f in report.findings}
        earlier = self.session.execute(
            select(
                ValidationIssue.id,
                ValidationIssue.check_code,
                ValidationIssue.object_type,
                ValidationIssue.object_id,
            )
            .join(ValidationRun, ValidationRun.id == ValidationIssue.validation_run_id)
            .where(
                ValidationRun.entity_id == self.entity.id,
                ValidationRun.id != run.id,
                ValidationIssue.resolved_at.is_(None),
            )
        ).all()
        # An issue is resolved only when its check ran again and didn't find it (a quick
        # validation, or a control the source couldn't give, leaves earlier issues open).
        fixed = [
            i
            for i, code, kind, oid in earlier
            if (code, kind, oid) not in current
            and (code in self.covered or code not in KNOWN_CODES)
        ]
        if fixed:
            self.session.execute(
                update(ValidationIssue)
                .where(ValidationIssue.id.in_(fixed))
                .values(resolved_at=now, updated_at=now)
            )
        run.status = report.status
        run.checks_passed = report.checks_passed
        run.checks_failed = report.checks_failed
        run.updated_at = now
        self.session.commit()
