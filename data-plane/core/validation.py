"""Validation of one entity's books (VAL-001, VAL-002; schema.md 5.2, architecture 4.6).

Source-independent: the source's own figures arrive as `connectors.base.SourceBalances`.
Everything is computed **as of a date**: only vouchers dated on or before it count, so
post-dated vouchers simply fall outside earlier dates.

Issue messages are stored in the database (they may name vouchers and ledgers); nothing
here logs names or amounts.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from connectors.base import SourceBalances
from core.models import accounting as A  # noqa: N812
from core.models.base import utcnow
from core.models.system import ValidationIssue, ValidationRun

ZERO = Decimal(0)
PROFIT_NATURES = ("income", "expense")


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
        self._vouchers()
        report.opening_difference = self._opening_difference(ledgers)
        self._trial_balance(report.opening_difference)
        self._closing(ledgers, source)

        report.findings = self.findings
        report.checks_passed = self.passed
        report.checks_failed = sum(1 for f in self.findings if f.severity == "error")
        report.status = "failed" if report.checks_failed else "passed"
        self._store(run, report)
        return report

    def _fail(self, finding: Finding) -> None:
        self.findings.append(finding)

    # --- our side ---------------------------------------------------------------------

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

    def _vouchers(self) -> None:
        """VAL-001: every effective voucher's lines sum to zero."""
        sums = self.session.execute(
            select(A.VoucherLine.voucher_id, func.sum(A.VoucherLine.amount))
            .where(A.VoucherLine.entity_id == self.entity.id, A.VoucherLine.is_effective.is_(True))
            .group_by(A.VoucherLine.voucher_id)
        ).all()
        unbalanced = {vid: Decimal(total) for vid, total in sums if Decimal(total) != ZERO}
        self.passed += len(sums) - len(unbalanced)
        if not unbalanced:
            return
        vouchers = self.session.execute(
            select(A.Voucher.id, A.Voucher.voucher_number, A.Voucher.voucher_date).where(
                A.Voucher.id.in_(list(unbalanced))
            )
        ).all()
        for vid, number, voucher_date in vouchers:
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
        self, ledgers: list[_LedgerBalance], source: SourceBalances | Exception | None
    ) -> None:
        """VAL-002: each ledger's balance matches the source's own closing balance."""
        entity_id = str(self.entity.id)
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
            if abs(theirs - expected_ours) <= self.tolerance:
                self.passed += 1
            else:
                self._fail(
                    Finding(code, "error", "ledger", str(ledger.id), theirs, expected_ours, message)
                )
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
