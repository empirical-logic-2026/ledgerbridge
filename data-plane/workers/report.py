"""One health report, and the shared layout of every command's results (source-independent).

`report` answers "is everything all right, and if not, what do I do next?" in one place:

    Overall: ACTION NEEDED
    Next step: .\\dev.ps1 validate analyse -Env pilot

then sections: connection, data loaded, work in progress, validation per company, warnings,
and problems with what each means, its likely cause (root causes before their consequences)
and the exact next command. Everything is read from the database: the report never
contacts the source.

Every problem is named the same way everywhere: its plain title, then the technical key and
its stable code in brackets (core/problems.py, docs/error-catalogue.md). Validation counts
are compared with the company's previous validation (better / worse / unchanged).

**Pilot-safe in every environment:** counts, dates, codes, labels such as
`entity 3 (company 1)` and error types only; never company, ledger or party names, error
messages, values or amounts. The Markdown version can be saved and shared as it is.
"""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.config import get_settings
from core.models import Connection, SyncRun
from core.models import accounting as A  # noqa: N812
from core.models.base import utcnow
from core.models.source import RawRecord
from core.models.system import (
    Alert,
    SyncCheckpoint,
    SyncLog,
    SyncUnverifiedRange,
    ValidationIssue,
    ValidationRun,
)
from core.problems import (
    BY_CODE,
    ERROR,
    INFO,
    WARNING,
    WORK_FIRST,
    Problem,
    for_error,
    for_key,
)
from core.transform import FOREIGN_UNREAD
from workers.entities import Labels
from workers.failures import failure_breakdown, format_group, warning_breakdown
from workers.fields import catalogue_counts
from workers.runs import FINISHED
from workers.sync import DELETION_CHECK, entity_ids_for, last_run, running_run

# OK; OK WITH WARNINGS (only warnings waiting on an open item: nothing to run); ACTION NEEDED
# (a warning with something to run, e.g. an interrupted sync); FAILED (an error). Only FAILED
# makes `report` and `validate` exit 1.
OK, OK_WARNINGS, ATTENTION, FAILED = "OK", "OK WITH WARNINGS", "ACTION NEEDED", "FAILED"
_RANK = {ERROR: 0, WARNING: 1, INFO: 2}
_MARK = {ERROR: "FAILED", WARNING: "WARNING", INFO: "note"}
# Checks that only run in a thorough validation (the source's controls).
CONTROL_KEYS = frozenset(
    {
        "year_end_mismatch",
        "voucher_count_mismatch",
        "stock_quantity_mismatch",
        "bills_mismatch",
        "year_end_balances_unavailable",
        "voucher_counts_unavailable",
        "stock_quantities_unavailable",
        "bill_outstanding_unavailable",
    }
)


# --- occurrences of problems --------------------------------------------------------------


@dataclass
class Occurrence:
    """One problem found somewhere (a company or a connection), with its count and, for
    validation, the count in the previous run."""

    problem: Problem
    where: str
    count: int | None = None
    previous: int | None = None
    comparable: bool = True
    note: str = ""

    @property
    def active(self) -> bool:
        """Found now (a check fixed since the previous run has count 0)."""
        return self.count is None or self.count > 0

    def amount(self) -> str:
        if self.count is None:
            return self.where
        text = f"{self.where}: {self.count:,}"
        if self.problem.key.endswith("_mismatch") or self.previous is not None:
            text += f" ({trend(self.count, self.previous, self.comparable)})"
        return text


def trend(now: int, before: int | None, comparable: bool = True) -> str:
    """Better / worse / unchanged against the previous run."""
    if not comparable:
        return "not compared: one of the two runs was a quick validation"
    if before is None:
        return "first result"
    if now < before:
        return f"better, was {before:,}" if now else f"fixed, was {before:,}"
    if now > before:
        return f"worse, was {before:,}"
    return "unchanged"


def verdict(occurrences: Iterable[Occurrence]) -> str:
    active = [o.problem for o in occurrences if o.active]
    if any(p.severity == ERROR for p in active):
        return FAILED
    warnings = [p for p in active if p.severity == WARNING]
    if any(not p.open_item for p in warnings):
        return ATTENTION
    return OK_WARNINGS if warnings else OK


def _present(occurrences: Iterable[Occurrence]) -> set[str]:
    return {o.problem.code for o in occurrences if o.problem.severity != INFO and o.active}


def cause_line(problem: Problem, present: set[str], full: bool = False) -> str:
    """Root cause or consequence, given which other problems are present."""
    roots = [c for c in problem.consequence_of if c in present and c != problem.code]
    if roots:
        named = ", ".join(f"{BY_CODE[c].title} [{c}]" for c in roots)
        return f"Consequence: likely follows from {named}, found too. Fix that first."
    followers = [
        p for p in sorted(present) if problem.code in BY_CODE.get(p, problem).consequence_of
    ]
    causes = problem.causes
    if problem.causes_alone:  # none of its root causes is present (they'd be named above)
        causes = problem.causes_alone
    text = " ".join(causes if full else causes[:1]) or "Not known yet."
    if followers:
        return (
            f"ROOT CAUSE: {len(followers)} other problem(s) here likely follow from it, so fix "
            f"it first. {text}"
        )
    return text


def ordered(occurrences: Iterable[Occurrence]) -> list[list[Occurrence]]:
    """Occurrences grouped by problem: root causes first, then by severity and code."""
    groups: dict[str, list[Occurrence]] = {}
    for o in occurrences:
        if not o.active:
            continue
        groups.setdefault(o.problem.code, []).append(o)
    present = _present(o for g in groups.values() for o in g)

    def key(group: list[Occurrence]) -> tuple[int, int, int, str]:
        p = group[0].problem
        consequence = any(c in present and c != p.code for c in p.consequence_of)
        return (_work_rank(p.code), _RANK[p.severity], int(consequence), p.code)

    return sorted(groups.values(), key=key)


def problem_lines(occurrences: list[Occurrence], env: str, details: bool) -> list[str]:
    """For every problem: where and how many, what it means, the likely cause and the next
    step (with -Details also how to investigate and fix)."""
    present = _present(occurrences)
    out: list[str] = []
    for group in ordered(occurrences):
        p = group[0].problem
        if p.severity == INFO and not details:
            continue
        out.append(f"{_MARK[p.severity]}  {p.label()}")
        out.append(f"  Where: {'; '.join(o.amount() for o in group)}")
        out.append(f"  What this means: {p.meaning}")
        out.append(f"  Likely cause: {cause_line(p, present, details)}")
        if details:
            for step in p.investigate:
                out.append(f"  Investigate: {step.replace('{env}', env)}")
            for step in p.fix:
                out.append(f"  Fix: {step.replace('{env}', env)}")
        out.append(f"  Next step: {p.command(env)}")
    return out


def _work_rank(code: str) -> int:
    """Unfinished work first (in WORK_FIRST's order), then everything else."""
    return WORK_FIRST.index(code) if code in WORK_FIRST else len(WORK_FIRST)


def next_step(occurrences: list[Occurrence], env: str) -> str | None:
    """The first problem's command: unfinished work (a running job, a full sync to resume,
    records waiting) before anything else, then root causes before their consequences.
    Problems waiting on an open item come last, named, since nothing can be run for them."""
    waiting = None
    for group in ordered(occurrences):
        p = group[0].problem
        if p.severity == INFO and p.code not in WORK_FIRST:
            continue
        if p.open_item:
            waiting = waiting or p
            continue
        return p.command(env)
    return f"nothing to run: open item {waiting.open_item}" if waiting else None


# --- validation, as every command shows it ------------------------------------------------


def _counts(session: Session, run_id: int) -> Counter[str]:
    return Counter(
        dict(
            session.execute(
                select(ValidationIssue.check_code, func.count())
                .where(ValidationIssue.validation_run_id == run_id)
                .group_by(ValidationIssue.check_code)
            ).all()
        )
    )


def previous_run(session: Session, run: ValidationRun) -> ValidationRun | None:
    return session.scalar(
        select(ValidationRun)
        .where(
            ValidationRun.entity_id == run.entity_id,
            ValidationRun.id < run.id,
            ValidationRun.status != "running",
        )
        .order_by(ValidationRun.id.desc())
        .limit(1)
    )


def validation_occurrences(session: Session, run: ValidationRun, where: str) -> list[Occurrence]:
    """The run's problems (by check code, counts only), each compared with the previous run;
    checks that failed before and pass now appear as fixed (count 0)."""
    now = _counts(session, run.id)
    before_run = previous_run(session, run)
    before = _counts(session, before_run.id) if before_run else None
    # A quick run skips the source's controls: those checks are compared only with a run of
    # the same kind (thorough is NULL for runs made before migration 0013: compared anyway).
    kinds = (run.thorough, before_run.thorough if before_run else None)
    same_kind = None in kinds or kinds[0] == kinds[1]
    out = []
    if run.thorough is False:
        out.append(Occurrence(BY_CODE["LB-VAL-018"], where))
    keys = set(now) | {k for k in (before or {}) if for_key(k).severity == ERROR}
    for key in sorted(keys, key=lambda k: for_key(k).code):
        problem = for_key(key)
        if key not in now and run.thorough is False and key in CONTROL_KEYS:
            continue  # skipped by this quick run, not fixed
        count = now.get(key, 0)
        if problem.severity == INFO:
            out.append(Occurrence(problem, where))
            continue
        previous = None if before is None else before.get(key, 0)
        comparable = same_kind or key not in CONTROL_KEYS
        out.append(Occurrence(problem, where, count, previous, comparable))
    return out


def validation_lines(
    session: Session, run: ValidationRun, where: str, indent: str = ""
) -> list[str]:
    """`Validation of entity 1 (company 1) as of 2026-10-14: FAILED ...` and one line per
    check that found something (or was fixed since the previous run)."""
    status = run.status.upper()
    warnings = sum(
        o.count or 0
        for o in validation_occurrences(session, run, where)
        if o.problem.severity == WARNING
    )
    if run.status == "passed" and warnings:
        status = f"PASSED with {warnings:,} warning{'s' if warnings != 1 else ''}"
    head = (
        f"{indent}Validation of {where} as of {run.as_of}: {status} "
        f"({run.checks_passed:,} checks passed, {run.checks_failed:,} failed; run {run.id}, "
        f"{run.started_at:%Y-%m-%d %H:%M} UTC)"
    )
    out = [head]
    for o in validation_occurrences(session, run, where):
        p = o.problem
        if p.severity == INFO:
            out.append(f"{indent}  note: {p.label()}")
            continue
        if not o.count and o.previous:
            out.append(f"{indent}  {p.label()}: 0 ({trend(0, o.previous)})")
        elif o.count:
            mark = "WARNING " if p.severity == WARNING else ""
            change = trend(o.count, o.previous, o.comparable)
            out.append(f"{indent}  {mark}{p.label()}: {o.count:,} ({change})")
    return out


def latest_validation(session: Session, entity_id: int) -> ValidationRun | None:
    return session.scalar(
        select(ValidationRun)
        .where(ValidationRun.entity_id == entity_id)
        .order_by(ValidationRun.id.desc())
        .limit(1)
    )


# --- the report ---------------------------------------------------------------------------


@dataclass
class Section:
    title: str
    lines: list[str] = field(default_factory=list)
    details: list[str] = field(default_factory=list)  # shown with -Details
    occurrences: list[Occurrence] = field(default_factory=list)

    @property
    def status(self) -> str:
        return verdict(self.occurrences)


@dataclass
class HealthReport:
    env: str
    generated: datetime
    sections: list[Section]
    commit: str = "unknown"  # the git commit the running code was built from (ADR-045)

    @property
    def occurrences(self) -> list[Occurrence]:
        return [o for s in self.sections for o in s.occurrences]

    @property
    def verdict(self) -> str:
        return verdict(self.occurrences)


def _count(session: Session, model: type, *where: object) -> int:
    return session.scalar(select(func.count()).select_from(model).where(*where)) or 0


def _run_line(run: SyncRun | None, label: str) -> str:
    if run is None:
        return f"{label}: never"
    when = f"{run.started_at:%Y-%m-%d %H:%M} UTC"
    return (
        f"{label}: run {run.id} ({run.run_type}) {run.status.upper()}, started {when}, "
        f"{run.records_received:,} received, {run.records_failed:,} failed"
    )


def _error_type(summary: str | None) -> str:
    return (summary or "").split(":", 1)[0].strip() or "unknown"


class Builder:
    def __init__(self, session: Session, env: str, entity_names: list[str] | None = None) -> None:
        self.session = session
        self.env = env  # for the commands in next steps
        self.connections = list(session.scalars(select(Connection).order_by(Connection.id)))
        self.only = entity_names  # exact names typed by the developer (never printed)

    def _entities(self, connection: Connection) -> list[tuple[int, str]]:
        """(entity id, source key) of the connection, optionally only the named ones."""
        query = select(A.EntitySource.entity_id, A.EntitySource.source_entity_key).where(
            A.EntitySource.connection_id == connection.id
        )
        if self.only:
            query = query.where(A.EntitySource.source_entity_name.in_(self.only))
        return list(self.session.execute(query.order_by(A.EntitySource.entity_id)).all())

    def build(self) -> HealthReport:
        sections = [
            self.connection(),
            self.data(),
            self.in_progress(),
            self.validation(),
            self.warnings(),
        ]
        return HealthReport(self.env, utcnow(), sections, get_settings().ledgerbridge_commit)

    # --- sections -------------------------------------------------------------------------

    def connection(self) -> Section:
        s = Section("Connection")
        if not self.connections:
            s.lines.append("no connection yet")
            s.occurrences.append(Occurrence(BY_CODE["LB-CON-001"], "this environment"))
        for c in self.connections:
            where = f"connection {c.id} ({c.name})"
            configured = len(c.config.get("entities") or [])
            s.lines.append(
                f"{where}: {c.status}, origin {c.config.get('origin', 'live')}, "
                f"{configured} companies configured"
            )
            sync = last_run(self.session, c.id)
            check = last_run(self.session, c.id, (DELETION_CHECK,))
            s.lines.append(f"  {_run_line(sync, 'last sync')}")
            s.details.append(f"  {_run_line(check, 'last deletion check')}")
            if c.status != "active":
                s.occurrences.append(Occurrence(BY_CODE["LB-CON-002"], where))
            if sync is None:
                s.occurrences.append(Occurrence(BY_CODE["LB-SYNC-009"], where))
            elif sync.status == "failed":
                problem = for_error(sync.error_summary, "LB-SYNC-001")
                s.occurrences.append(
                    Occurrence(problem, f"{where}, run {sync.id}", note=sync.error_summary or "")
                )
                s.lines.append(f"  error type: {_error_type(sync.error_summary)} [{problem.code}]")
            elif sync.status == "interrupted":
                s.occurrences.append(Occurrence(BY_CODE["LB-SYNC-010"], f"{where}, run {sync.id}"))
            if check is not None and check.status == "failed":
                s.occurrences.append(Occurrence(BY_CODE["LB-SYNC-003"], f"{where}, run {check.id}"))
        return s

    def data(self) -> Section:
        s = Section("Data loaded")
        for c in self.connections:
            labels = Labels(self.session, c)
            entities = self._entities(c)
            keys = [key for _, key in entities] if self.only else None
            raw = Counter()
            for status, n in self.session.execute(
                select(RawRecord.process_status, func.count())
                .where(
                    RawRecord.connection_id == c.id,
                    *([RawRecord.source_entity_key.in_(keys)] if keys is not None else []),
                )
                .group_by(RawRecord.process_status)
            ):
                raw[status] = n
            total = sum(raw.values())
            s.lines.append(
                f"connection {c.id}: {total:,} records stored, {raw['processed']:,} converted, "
                f"{raw['failed']:,} failed to convert, {raw['pending']:,} waiting"
            )
            busy = running_run(self.session, c.id) is not None
            if raw["failed"]:
                s.occurrences.append(
                    Occurrence(BY_CODE["LB-TRF-001"], f"connection {c.id}", raw["failed"])
                )
            if raw["pending"] and not busy:
                s.occurrences.append(
                    Occurrence(BY_CODE["LB-TRF-002"], f"connection {c.id}", raw["pending"])
                )
            for entity_id, _key in entities:
                live = (A.Ledger.entity_id == entity_id, A.Ledger.is_deleted.is_(False))
                vouchers = (A.Voucher.entity_id == entity_id, A.Voucher.is_deleted.is_(False))
                ledgers = _count(self.session, A.Ledger, *live)
                unmapped = _count(
                    self.session, A.Ledger, *live, A.Ledger.mapping_status == "unmapped"
                )
                n_vouchers = _count(self.session, A.Voucher, *vouchers)
                where = labels.for_entity(entity_id)
                s.lines.append(f"  {where}: {ledgers:,} ledgers, {n_vouchers:,} vouchers")
                s.details.append(
                    f"  {where}: parties "
                    f"{_count(self.session, A.Party, A.Party.entity_id == entity_id):,}, "
                    f"cancelled vouchers "
                    f"{_count(self.session, A.Voucher, *vouchers, A.Voucher.is_cancelled):,}, "
                    f"deleted in the source "
                    f"{_count(self.session, A.Voucher, A.Voucher.entity_id == entity_id, A.Voucher.is_deleted):,}"  # noqa: E501
                )
                if unmapped:
                    s.occurrences.append(Occurrence(BY_CODE["LB-TRF-008"], where, unmapped))
                fields = catalogue_counts(self.session, entity_id)
                if fields:
                    s.occurrences.append(
                        Occurrence(BY_CODE["LB-TRF-006"], where, sum(fields.values()))
                    )
            failures = failure_breakdown(self.session, c.id, keys)
            if failures:
                s.details.append("  why records failed to convert (kind of record, count, error):")
                s.details += [f"    {format_group(g)}" for g in failures]
            notes = warning_breakdown(self.session, c.id, keys)
            kinds: Counter[str] = Counter()
            for g in notes:
                kinds[note_code(g.message)] += g.count
            if notes:
                s.details.append(
                    "  converted with a note (kind of record, count, note; no values):"
                )
                s.details += [f"    {format_group(g)}" for g in notes]
            for code, n in sorted(kinds.items()):
                s.occurrences.append(Occurrence(BY_CODE[code], f"connection {c.id}", n))
            prefixes = c.config.get("xml_prefixes_seen") or []
            if prefixes:
                s.occurrences.append(
                    Occurrence(
                        BY_CODE["LB-TRF-009"], f"connection {c.id}", note=", ".join(prefixes)
                    )
                )
                s.details.append(f"  custom XML prefixes seen: {', '.join(prefixes)}")
        return s

    def in_progress(self) -> Section:
        s = Section("Work in progress")
        for c in self.connections:
            labels = Labels(self.session, c)
            run = running_run(self.session, c.id)
            if run is not None:
                s.lines.append(
                    f"connection {c.id}: run {run.id} ({run.run_type}) RUNNING since "
                    f"{run.started_at:%Y-%m-%d %H:%M} UTC; follow it: "
                    f"{BY_CODE['LB-SYNC-007'].command(self.env)}"
                )
                s.occurrences.append(Occurrence(BY_CODE["LB-SYNC-007"], f"connection {c.id}"))
            elif self._job_alive(c.id):
                s.lines.append(
                    f"connection {c.id}: a background job is RUNNING; follow it: "
                    f"{BY_CODE['LB-SYNC-007'].command(self.env)}"
                )
                s.occurrences.append(Occurrence(BY_CODE["LB-SYNC-007"], f"connection {c.id}"))
            resumable = self.session.execute(
                select(
                    SyncCheckpoint.source_entity_key,
                    func.count(),
                    func.min(SyncCheckpoint.created_at),
                )
                .where(SyncCheckpoint.connection_id == c.id)
                .group_by(SyncCheckpoint.source_entity_key)
            ).all()
            ids = entity_ids_for(self.session, c.id, [key for key, _, _ in resumable])
            for key, chunks, since in resumable:
                who = labels.for_key(key, ids.get(key))
                s.lines.append(
                    f"{who}: unfinished full sync, {chunks:,} parts done since "
                    f"{since:%Y-%m-%d %H:%M} UTC; resume: "
                    f"{BY_CODE['LB-SYNC-002'].command(self.env)}"
                )
                if run is None:
                    s.occurrences.append(Occurrence(BY_CODE["LB-SYNC-002"], who, chunks))
            pending = _count(
                self.session,
                RawRecord,
                RawRecord.connection_id == c.id,
                RawRecord.process_status == "pending",
            )
            if pending:
                s.lines.append(
                    f"connection {c.id}: {pending:,} records waiting to be converted; convert: "
                    f"{BY_CODE['LB-TRF-002'].command(self.env)}"
                )
            ranges = self.session.execute(
                select(
                    SyncUnverifiedRange.source_entity_key,
                    SyncUnverifiedRange.object_type,
                    SyncUnverifiedRange.period_from,
                    SyncUnverifiedRange.period_to,
                ).where(
                    SyncUnverifiedRange.connection_id == c.id,
                    SyncUnverifiedRange.resolved_at.is_(None),
                )
            ).all()
            range_ids = entity_ids_for(self.session, c.id, [r[0] for r in ranges])
            per_entity: Counter[str] = Counter()
            for key, kind, start, end in ranges:
                who = labels.for_key(key, range_ids.get(key))
                per_entity[who] += 1
                s.details.append(f"  UNVERIFIED {kind} {start}..{end} of {who}")
            for who, n in sorted(per_entity.items()):
                s.lines.append(
                    f"{who}: {n} periods UNVERIFIED; fetch again: "
                    f"{BY_CODE['LB-SYNC-004'].command(self.env)}"
                )
                s.occurrences.append(Occurrence(BY_CODE["LB-SYNC-004"], who, n))
        if not s.lines:
            s.lines.append("nothing in progress")
        return s

    def _job_alive(self, connection_id: int) -> bool:
        """The latest background job hasn't finished and showed signs of life recently."""
        job = self.session.scalar(
            select(SyncLog.job_id)
            .where(SyncLog.connection_id == connection_id)
            .order_by(SyncLog.id.desc())
            .limit(1)
        )
        if job is None:
            return False
        finished = self.session.scalar(
            select(func.count())
            .select_from(SyncLog)
            .where(SyncLog.job_id == job, SyncLog.line.like(f"{FINISHED}%"))
        )
        if finished:
            return False
        last = self.session.scalar(select(func.max(SyncLog.logged_at)).where(SyncLog.job_id == job))
        grace = timedelta(seconds=3 * get_settings().sync_heartbeat_sec)
        return last is not None and utcnow() - last < grace

    def validation(self) -> Section:
        s = Section("Validation per company")
        for c in self.connections:
            labels = Labels(self.session, c)
            for entity_id, _key in self._entities(c):
                where = labels.for_entity(entity_id)
                run = latest_validation(self.session, entity_id)
                if run is None:
                    s.lines.append(f"{where}: NOT VALIDATED yet")
                    s.occurrences.append(Occurrence(BY_CODE["LB-VAL-019"], where))
                    continue
                lines = validation_lines(self.session, run, where)
                s.lines.append(lines[0])
                s.occurrences += validation_occurrences(self.session, run, where)
                # Short: the checks that found something; -Details: notes and fixed ones too.
                for line in lines[1:]:
                    (s.details if "note:" in line or "(fixed" in line else s.lines).append(line)
        if not s.lines:
            s.lines.append("no company converted yet")
        return s

    def warnings(self) -> Section:
        """Warnings and notes found in the other sections, plus open alerts."""
        s = Section("Warnings")
        for c in self.connections:
            alerts = self.session.execute(
                select(Alert.kind, func.count())
                .where(Alert.connection_id == c.id, Alert.resolved_at.is_(None))
                .group_by(Alert.kind)
            ).all()
            listed = ", ".join(f"{k} {n}" for k, n in sorted(alerts)) or "none"
            s.lines.append(f"connection {c.id}: open alerts: {listed}")
        return s


def note_code(message: str) -> str:
    if message.startswith(FOREIGN_UNREAD):
        return "LB-TRF-011"
    if message.startswith("ambiguous reference"):
        return "LB-TRF-005"
    if message.startswith("reference matched"):
        return "LB-TRF-004"
    return "LB-TRF-003"


def build(session: Session, env: str, entity_names: list[str] | None = None) -> HealthReport:
    return Builder(session, env, entity_names).build()


# --- rendering ----------------------------------------------------------------------------


def _warnings_lines(report: HealthReport, details: bool) -> list[str]:
    out = []
    for group in ordered(report.occurrences):
        p = group[0].problem
        if p.severity == ERROR or (p.severity == INFO and not details):
            continue
        out.append(f"{_MARK[p.severity]}  {p.label()}: {'; '.join(o.amount() for o in group)}")
    return out


def render_text(report: HealthReport, details: bool = False) -> str:
    occurrences = report.occurrences
    errors = sum(1 for g in ordered(occurrences) if g[0].problem.severity == ERROR)
    warnings = sum(1 for g in ordered(occurrences) if g[0].problem.severity == WARNING)
    out = [
        f"LedgerBridge health report ({report.env}), {report.generated:%Y-%m-%d %H:%M} UTC, "
        f"code {report.commit}",
        f"Overall: {report.verdict}  ({errors} problem(s), {warnings} warning(s))",
    ]
    step = next_step(occurrences, report.env)
    if step:
        out.append(f"Next step: {step}")
    for section in report.sections:
        out.append("")
        if section.title == "Warnings":
            lines = _warnings_lines(report, details) + section.lines
            status = verdict(o for o in occurrences if o.problem.severity != ERROR)
        else:
            lines = section.lines + (section.details if details else [])
            status = section.status
        out.append(f"== {section.title}: {status} ==")
        out += [f"  {line}" for line in lines]
    problems = problem_lines(occurrences, report.env, details)
    if problems:
        out += ["", "== Problems and next steps ==", *[f"  {line}" for line in problems]]
    if not details:
        out += ["", f"More: .\\dev.ps1 report -Env {report.env} -Details"]
    return "\n".join(out)


def render_markdown(report: HealthReport) -> str:
    """The full report (with details) as Markdown, to save and share."""
    occurrences = report.occurrences
    out = [
        f"# LedgerBridge health report ({report.env})",
        "",
        f"Generated {report.generated:%Y-%m-%d %H:%M} UTC by code {report.commit}. Counts, "
        "dates and codes only: no "
        "names, values or amounts. Codes are explained in docs/error-catalogue.md.",
        "",
        f"**Overall: {report.verdict}**",
    ]
    step = next_step(occurrences, report.env)
    if step:
        out += ["", f"Next step: `{step}`"]
    for section in report.sections:
        if section.title == "Warnings":
            lines = _warnings_lines(report, True) + section.lines
            status = verdict(o for o in occurrences if o.problem.severity != ERROR)
        else:
            lines = section.lines + section.details
            status = section.status
        out += ["", f"## {section.title}: {status}", ""]
        out += [_bullet(line) for line in lines]
    problems = problem_lines(occurrences, report.env, True)
    if problems:
        out += ["", "## Problems and next steps", ""]
        for line in problems:
            if line.startswith("  "):
                label, _, rest = line.strip().partition(": ")
                value = f"`{rest}`" if label == "Next step" else _md(rest)
                out.append(f"  - {label}: {value}")
            else:
                out.append(f"- **{_md(line)}**")
    return "\n".join(out) + "\n"


def _md(text: str) -> str:
    """The text without its indent (list nesting shows it), with `*` escaped. Underscores
    inside words (check codes) aren't formatting in Markdown, so they stay as they are."""
    return text.strip().replace("*", "\\*")


def _bullet(line: str) -> str:
    """A Markdown list item, nested as deep as the line was indented (two spaces a level)."""
    depth = (len(line) - len(line.lstrip(" "))) // 2
    return f"{'  ' * depth}- {_md(line)}"
