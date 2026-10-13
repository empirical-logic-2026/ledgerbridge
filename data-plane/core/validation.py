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
"""

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from connectors.base import SourceBalances, SourceControls
from core.models import accounting as A  # noqa: N812
from core.models.base import utcnow
from core.models.source import RawRecord
from core.models.system import ValidationIssue, ValidationRun

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
)


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
            listed = ", ".join(f"{code} {n:,}" for code, n in sorted(self.consequences.items()))
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

    @property
    def failed_by_code(self) -> Counter[str]:
        return Counter(f.check_code for f in self.findings if f.severity == "error")


@dataclass
class _LedgerBalance:
    id: int
    name: str
    source_key: str
    connection_id: int
    nature: str | None
    opening: Decimal
    balance: Decimal  # opening + effective lines dated on or before as_of


def financial_year_ends(books_from: date | None, fy_start_month: int, as_of: date) -> list[date]:
    """Financial year ends after books_from and before as_of."""
    if books_from is None:
        return []
    ends = []
    year = books_from.year if books_from.month < fy_start_month else books_from.year + 1
    while True:
        end = date(year, fy_start_month, 1) - timedelta(days=1)
        if end >= as_of:
            return ends
        if end >= books_from:
            ends.append(end)
        year += 1


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
        )
        self.session.add(run)
        self.session.flush()
        report = ValidationReport(run.id, self.entity.id, self.entity.name, self.as_of)

        ledgers = self._ledger_balances(self.as_of)
        report.unbalanced_by_type, report.unbalanced_details = self._vouchers()
        report.opening_difference = self._opening_difference(ledgers)
        self._trial_balance(report.opening_difference)
        self._closing(ledgers, source)
        if controls is not None:
            for year_end, balances in sorted(controls.year_ends.items()):
                self._closing(self._ledger_balances(year_end), balances, year_end)
            self._voucher_counts(controls.voucher_counts)
            self._stock_quantities(controls.stock_quantities)
            self._bills(controls.bill_outstanding, controls.opening_bills)
        report.root_cause = self._root_cause()

        report.findings = self.findings
        report.checks_passed = self.passed
        report.checks_failed = sum(1 for f in self.findings if f.severity == "error")
        report.status = "failed" if report.checks_failed else "passed"
        self._store(run, report)
        return report

    def _fail(self, finding: Finding) -> None:
        self.findings.append(finding)

    # --- our side ---------------------------------------------------------------------

    def ledger_balances(self, as_of: date) -> list["_LedgerBalance"]:
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

    def _opening_difference(self, ledgers: list[_LedgerBalance]) -> Decimal:
        difference = sum((ledger.opening for ledger in ledgers), ZERO)
        if difference == ZERO:
            self.passed += 1
        else:
            self._fail(
                Finding(
                    "opening_difference",
                    "warning",
                    "entity",
                    str(self.entity.id),
                    ZERO,
                    difference,
                    "Opening balances don't total zero (difference in opening balances). "
                    "Correct the opening balances in the source books.",
                )
            )
        return difference

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
            if isinstance(source, Exception) or source is None:
                self._unavailable("year_end_balances", source, f"at {year_end}")
                return
            entity_id = f"{self.entity.id}@{year_end.isoformat()}"
        if source is None:
            self._fail(
                Finding(
                    "closing_not_supported",
                    "info",
                    "entity",
                    entity_id,
                    None,
                    None,
                    "The source can't report closing balances; closing checks skipped.",
                )
            )
            return
        if isinstance(source, Exception):
            self._fail(
                Finding(
                    "closing_unavailable",
                    "error",
                    "entity",
                    entity_id,
                    None,
                    None,
                    f"Closing balances couldn't be read from the source "
                    f"({type(source).__name__}); closing checks didn't run.",
                )
            )
            return
        ours = [
            ledger
            for ledger in ledgers
            if self.connection_id is None or ledger.connection_id == self.connection_id
        ]
        profit = sum((x.balance for x in ours if x.nature in PROFIT_NATURES), ZERO)
        if source.closing_stock is not None and source.opening_stock is not None:
            profit -= source.closing_stock - source.opening_stock  # debit positive: a loss
        seen = set()
        for ledger in ours:
            seen.add(ledger.source_key)
            theirs = source.ledgers.get(ledger.source_key)
            if theirs is None and year_end is not None:
                continue  # reported as ledger_missing as of the validation date
            if theirs is None:
                self._fail(
                    Finding(
                        "ledger_missing",
                        "error",
                        "ledger",
                        str(ledger.id),
                        None,
                        ledger.balance,
                        f"Ledger '{ledger.name}' isn't in the source.",
                    )
                )
                continue
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
                self._fail(
                    Finding(code, "error", "ledger", object_id, theirs, expected_ours, message)
                )
        if year_end is not None:
            return
        for key, theirs in source.ledgers.items():
            if key not in seen:
                self._fail(
                    Finding(
                        "ledger_missing",
                        "error",
                        "source_ledger",
                        key[:64],
                        theirs,
                        None,
                        "A ledger in the source isn't here (sync it, or check for a failure).",
                    )
                )

    # --- controls: counts, stock, bills (VAL-005 to VAL-008) ----------------------------

    def _unavailable(self, what: str, problem: Exception | None, detail: str = "") -> None:
        """A control the source couldn't provide: an error if it failed, a note if the
        source doesn't offer it."""
        where = f" {detail}" if detail else ""
        if problem is None:
            self._fail(
                Finding(
                    f"{what}_not_supported", "info", "entity", str(self.entity.id), None, None,
                    f"The source can't report {what.replace('_', ' ')}{where}; check skipped.",
                )
            )  # fmt: skip
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
        types = dict(
            self.session.execute(
                select(A.VoucherType.id, A.VoucherType.name).where(
                    A.VoucherType.entity_id == self.entity.id
                )
            ).all()
        )
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
        ids = {name: type_id for type_id, name in types.items()}
        for month, kind in sorted(set(ours) | set(theirs)):
            expected, actual = theirs.get((month, kind), 0), ours.get((month, kind), 0)
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

    def _stock_quantities(self, theirs: Mapping[str, Decimal] | Exception | None) -> None:
        """VAL-006: each stock item's closing quantity (opening plus movements of effective
        vouchers up to the date) equals the source's. Values depend on the source's
        valuation method and aren't compared item by item (the total closing stock is part
        of the profit check)."""
        if theirs is None or isinstance(theirs, Exception):
            self._unavailable("stock_quantities", theirs)
            return
        movements = (
            select(A.InventoryLine.item_id, func.sum(A.InventoryLine.quantity).label("moved"))
            .join(A.Voucher, A.Voucher.id == A.InventoryLine.voucher_id)
            .join(A.VoucherType, A.VoucherType.id == A.Voucher.voucher_type_id)
            .where(
                A.InventoryLine.entity_id == self.entity.id,
                A.InventoryLine.voucher_date <= self.as_of,
                A.Voucher.is_deleted.is_(False),
                A.Voucher.is_cancelled.is_(False),
                A.Voucher.is_optional.is_(False),
                A.VoucherType.moves_stock.is_(True),  # orders and memorandum don't
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
            self._fail(
                Finding(
                    "stock_values_not_compared", "info", "entity", str(self.entity.id), None, None,
                    "Stock values per item depend on the source's valuation method and aren't "
                    "compared item by item; the total closing stock is part of the profit check.",
                )
            )  # fmt: skip

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
            self._fail(
                Finding(
                    "bills_not_compared", "info", "entity", str(self.entity.id), None, None,
                    "Bill-wise outstanding is only compared as of today: the source reports "
                    "bills as outstanding now.",
                )
            )  # fmt: skip
            return
        for part in (outstanding, opening):
            if part is None or isinstance(part, Exception):
                self._unavailable("bill_outstanding", part)
                return
        assert isinstance(outstanding, Mapping) and isinstance(opening, Mapping)  # noqa: S101
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
        fixed = [i for i, code, kind, oid in earlier if (code, kind, oid) not in current]
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
