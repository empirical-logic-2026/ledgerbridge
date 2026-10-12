"""Command line for syncing sources (source-independent).

    python -m workers.cli entities --connection tally-test --source tally
    python -m workers.cli extract --connection tally-test --entity "LedgerBridge Test Co"
    python -m workers.cli sync --connection tally-test --entity "LedgerBridge Test Co" [--full]
    python -m workers.cli check-deletions --connection tally-test
    python -m workers.cli validate --connection tally-test [--as-of 2026-09-30]
    python -m workers.cli connect --connection tally-pilot --source tally --origin backup \
        --entity "Company A" --entity "Company B" [--paused]
    python -m workers.cli status
    python -m workers.cli summary
    python -m workers.cli trial-balance --entity-code LEDGERBRIDGE_TEST_CO

`extract` only stores raw records (M1); `sync` also transforms them (M3); `check-deletions`
soft-deletes what no longer exists in the source (also run by `sync --check-deletions`).
`sync` and `check-deletions` validate afterwards (VAL-001, VAL-002), like the worker does.

Output shows names, keys, counts, check codes and pass/fail only, except `trial-balance`,
which prints balances for the developer's own use. Validation results with amounts are in
the database and the API, never in this output.

**Outside the test environment (APP_ENV=pilot) the output holds no names at all:** no
company, ledger or party names and no error messages (only their type), so it can be
shared as counts and pass/fail. Companies appear as "entity <id>", and `trial-balance`
refuses to run (docs/pilot-runbook.md).
"""

import argparse
import sys
from collections.abc import Sequence
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from connectors import registry
from connectors.base import Period
from core.config import get_settings
from core.db import get_engine
from core.models import Connection, SyncRun
from core.models import accounting as A  # noqa: N812
from core.models.accounting import Entity
from core.models.base import utcnow
from core.models.source import RawRecord
from core.models.system import Alert, ValidationIssue, ValidationRun
from core.transform import trial_balance
from core.validation import ValidationReport
from workers.extract import connector_for, find_entity, get_or_create_connection, run_extract
from workers.sync import (
    DELETION_CHECK,
    SyncBusyError,
    SyncResult,
    deletion_check_interval,
    is_due,
    last_run,
    run_deletion_check,
    run_sync,
)
from workers.validate import after_run, run_validation


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m workers.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    def connection_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--connection", required=True, help="connection name")
        p.add_argument(
            "--source",
            choices=registry.available_sources(),
            help="source type; needed only when the connection is created",
        )

    def period_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--from", dest="date_from", type=date.fromisoformat)
        p.add_argument("--to", dest="date_to", type=date.fromisoformat)

    entities = sub.add_parser("entities", help="list entities (companies) in the source")
    connection_args(entities)

    extract = sub.add_parser(
        "extract", help="full extraction of one entity into ledgerbridge_source.raw_records"
    )
    connection_args(extract)
    extract.add_argument("--entity", required=True, help="entity (company) name in the source")
    period_args(extract)

    sync = sub.add_parser("sync", help="fetch changes and transform them into accounting tables")
    connection_args(sync)
    sync.add_argument(
        "--entity", action="append", help="entity name (repeatable); default: configured or all"
    )
    sync.add_argument("--full", action="store_true", help="ignore markers and fetch everything")
    sync.add_argument(
        "--check-deletions",
        action="store_true",
        help="afterwards, run a deletion check (normally on its own, hourly schedule)",
    )
    sync.add_argument(
        "--origin", choices=("live", "backup"), help="origin tag for this connection's data"
    )
    period_args(sync)

    sync.add_argument("--no-validate", action="store_true", help="skip validation after the sync")

    validate = sub.add_parser("validate", help="validate synced entities against the source")
    connection_args(validate)
    validate.add_argument("--entity", action="append", help="entity name (repeatable)")
    validate.add_argument(
        "--as-of", type=date.fromisoformat, help="balances as of this date (default today)"
    )

    deletions = sub.add_parser(
        "check-deletions", help="soft-delete what no longer exists in the source"
    )
    connection_args(deletions)
    deletions.add_argument("--entity", action="append", help="entity name (repeatable)")

    connect = sub.add_parser(
        "connect", help="create or update a connection: origin and the entities it syncs"
    )
    connection_args(connect)
    connect.add_argument("--origin", choices=("live", "backup"), required=True)
    connect.add_argument(
        "--entity", action="append", required=True, help="entity name (repeatable)"
    )
    connect.add_argument(
        "--paused",
        action="store_true",
        help="no scheduled syncs (e.g. backup data that doesn't change); manual syncs work",
    )

    sub.add_parser("status", help="each connection's last sync and when the next is due")
    sub.add_parser("summary", help="counts and pass/fail per entity (safe to share)")

    tb = sub.add_parser("trial-balance", help="trial balance computed from voucher lines")
    tb.add_argument("--entity-code", required=True)
    return parser


def _period(args: argparse.Namespace) -> Period | None:
    if not (args.date_from or args.date_to):
        return None
    if not (args.date_from and args.date_to):
        raise SystemExit("--from and --to must be given together")
    return Period(args.date_from, args.date_to)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    with Session(get_engine()) as session:
        if args.command == "status":
            return _status(session)
        if args.command == "summary":
            return _summary(session)
        if args.command == "trial-balance":
            if not _show_names():
                print("trial-balance prints amounts: test environment only.", file=sys.stderr)
                return 2
            return _trial_balance(session, args.entity_code)

        connection = get_or_create_connection(session, args.connection, args.source)
        if getattr(args, "origin", None):
            connection.config = {**connection.config, "origin": args.origin}
        if args.command in ("sync", "check-deletions") and args.entity:
            # Remember which entities this connection syncs (used by the scheduler).
            known = list(dict.fromkeys([*connection.config.get("entities", []), *args.entity]))
            connection.config = {**connection.config, "entities": known}
        session.commit()
        connector = connector_for(session, connection)

        if args.command == "connect":
            return _connect(session, connection, connector, args)

        if args.command == "entities":
            entities = connector.list_entities()
            print(f"{len(entities)} entities in connection '{connection.name}'")
            if _show_names():
                for entity in entities:
                    print(f"  {entity.name}  [{entity.key}]")
            return 0

        if args.command == "validate":
            reports = run_validation(session, connection, connector, args.entity, args.as_of)
            return _print_validation(reports)

        if args.command in ("sync", "check-deletions"):
            validate = not getattr(args, "no_validate", False)
            try:
                if args.command == "sync":
                    result = run_sync(
                        session, connection, connector, args.entity, args.full, _period(args)
                    )
                    code = _print_sync(result)
                    if validate and not (args.check_deletions and not code):
                        code |= _print_validation(after_run(session, connection, connector, result))
                    if code or not args.check_deletions:
                        return code
                result = run_deletion_check(session, connection, connector, args.entity)
            except SyncBusyError as exc:
                print(str(exc), file=sys.stderr)
                return 3
            code = _print_sync(result)
            if validate:
                code |= _print_validation(after_run(session, connection, connector, result))
            return code

        entity = find_entity(connector, args.entity)
        extracted = run_extract(session, connection, connector, entity, _period(args))

    print(f"Sync run {extracted.sync_run_id}: {extracted.status}")
    for object_type, count in sorted(extracted.by_object_type.items()):
        print(f"  {object_type}: {count}")
    print(
        f"  received {extracted.received}, stored {extracted.stored}, unchanged {extracted.skipped}"
    )
    if extracted.error:
        print(f"  error: {_error(extracted.error)}", file=sys.stderr)
        return 1
    return 0


def _show_names() -> bool:
    """Names and error messages are printed in the test environment only."""
    return get_settings().app_env == "test"


def _error(summary: str) -> str:
    """'Type: message' in test; only 'Type' elsewhere (messages can name companies)."""
    return summary if _show_names() else summary.split(":", 1)[0]


def _entities(names: Sequence[str]) -> str:
    return ", ".join(names) if _show_names() else f"{len(names)} entities"


def _connect(
    session: Session, connection: Connection, connector: object, args: argparse.Namespace
) -> int:
    """Sets the connection's origin, its exact list of entities and whether it's scheduled."""
    wanted = list(dict.fromkeys(args.entity))
    connection.config = {**connection.config, "origin": args.origin, "entities": wanted}
    connection.status = "paused" if args.paused else "active"
    session.commit()
    available = {e.name for e in connector.list_entities()}  # type: ignore[attr-defined]
    missing = [name for name in wanted if name not in available]
    print(
        f"Connection '{connection.name}': origin {args.origin}, {connection.status}, "
        f"{len(wanted)} entities configured, {len(wanted) - len(missing)} found in the source"
    )
    if missing:
        detail = f": {', '.join(missing)}" if _show_names() else ""
        print(
            f"  {len(missing)} not found{detail}. Check the exact names (and that the "
            "companies are loaded) in the source.",
            file=sys.stderr,
        )
        return 2
    return 0


def _print_sync(r: SyncResult) -> int:
    print(f"Sync run {r.sync_run_id} ({r.run_type}): {r.status}  entities: {_entities(r.entities)}")
    if r.run_type == DELETION_CHECK:
        print(f"  keys listed:  {dict(sorted(r.fetched.items()))}")
        print(f"  soft-deleted: {r.deleted or 'none'}")
    else:
        print(f"  fetched:     {dict(sorted(r.fetched.items()))}")
        print(f"  raw stored:  {r.stored} new or changed, {r.unchanged} unchanged")
        print(f"  transformed: {dict(sorted(r.transformed.items()))}  failed: {r.failed}")
    for number, (entity, names) in enumerate(r.unmapped_ledgers.items(), start=1):
        if _show_names():
            print(f"  unmapped ledgers in {entity} ({len(names)}): {', '.join(names) or 'none'}")
        else:
            print(f"  unmapped ledgers in entity {number} of this run: {len(names)}")
    if _show_names():
        for warning in r.warnings:
            print(f"  warning: {warning}")
    elif r.warnings:
        print(f"  warnings (mapping assumptions): {len(r.warnings)}")
    if r.error:
        print(f"  error: {_error(r.error)}", file=sys.stderr)
        return 1
    return 0


def _print_validation(reports: list[ValidationReport]) -> int:
    """Counts, codes and pass/fail only (safe for client data)."""
    for r in reports:
        name = r.entity_name if _show_names() else f"entity {r.entity_id}"
        print(
            f"Validation run {r.validation_run_id} of {name} as of {r.as_of}: "
            f"{r.status.upper()}  {r.checks_passed} checks passed, {r.checks_failed} failed"
        )
        for code, count in sorted(r.failed_by_code.items()):
            print(f"  failed: {code} x{count}")
        if any(f.check_code == "opening_difference" for f in r.findings):
            print("  WARNING: opening balances don't total zero (difference in opening balances)")
        for f in r.findings:
            if f.severity == "info":
                print(f"  note: {f.check_code}")
    return 1 if any(r.status == "failed" for r in reports) else 0


def _status(session: Session) -> int:
    now = utcnow()
    connections = session.scalars(select(Connection).order_by(Connection.name)).all()
    if not connections:
        print("No connections yet.")
    for connection in connections:
        configured = connection.config.get("entities", [])
        entities = _entities(configured) if configured else "all loaded"
        check_every = deletion_check_interval(connection)
        print(
            f"{connection.name}: {connection.status}, origin "
            f"{connection.config.get('origin', 'live')}, entities: {entities}"
        )
        sync = last_run(session, connection.id)
        _print_schedule(
            "sync", connection, sync, connection.sync_interval_sec, now, "fetched", "failed"
        )
        if sync is None:
            print(f"  deletion check (every {check_every}s): after the first sync")
            continue
        check = last_run(session, connection.id, (DELETION_CHECK,))
        _print_schedule("deletion check", connection, check, check_every, now, "keys listed")
        _print_validation_status(session, connection)
    return 0


def _print_validation_status(session: Session, connection: Connection) -> None:
    """Per entity: the latest validation and the opening difference warning; open alerts."""
    from core.models.accounting import EntitySource

    for entity in session.scalars(
        select(Entity)
        .join(EntitySource, EntitySource.entity_id == Entity.id)
        .where(EntitySource.connection_id == connection.id)
        .order_by(Entity.name)
    ):
        run = session.scalar(
            select(ValidationRun)
            .where(ValidationRun.entity_id == entity.id)
            .order_by(ValidationRun.id.desc())
            .limit(1)
        )
        name = entity.name if _show_names() else f"entity {entity.id}"
        if run is None:
            print(f"  validation of {name}: never ran")
            continue
        print(
            f"  validation of {name}: run {run.id} {run.status.upper()} as of {run.as_of}, "
            f"{run.checks_passed} passed, {run.checks_failed} failed, "
            f"at {run.started_at:%Y-%m-%d %H:%M:%S} UTC"
        )
        opening = session.scalar(
            select(func.count())
            .select_from(ValidationIssue)
            .where(
                ValidationIssue.validation_run_id == run.id,
                ValidationIssue.check_code == "opening_difference",
            )
        )
        if opening:
            print("    WARNING: opening balances don't total zero (difference in opening balances)")
    alerts = session.execute(
        select(Alert.kind, func.count())
        .where(Alert.connection_id == connection.id, Alert.resolved_at.is_(None))
        .group_by(Alert.kind)
    ).all()
    listed = ", ".join(f"{kind} {n}" for kind, n in sorted(alerts)) or "none"
    print(f"  open alerts: {listed}")


def _print_schedule(
    label: str,
    connection: Connection,
    run: SyncRun | None,
    interval: int,
    now: datetime,
    received: str,
    failed: str | None = None,
) -> None:
    head = f"  {label} (every {interval}s):"
    if run is None:
        print(f"{head} never ran; next: due now")
        return
    finished = f"{run.finished_at:%Y-%m-%d %H:%M:%S}" if run.finished_at else "-"
    counts = f"{run.records_received} {received}"
    if failed:
        counts += f", {run.records_failed} {failed}"
    print(
        f"{head} last run {run.id} ({run.run_type}) {run.status}, started "
        f"{run.started_at:%Y-%m-%d %H:%M:%S} UTC, finished {finished}, {counts}"
    )
    if run.status == "running":
        print("    next: after the current run")
    elif is_due(connection, run.started_at, now, interval):
        print("    next: due now (picked up within a minute by the worker)")
    else:
        wait = interval - int((now - run.started_at).total_seconds())
        print(f"    next: in about {wait}s")


def _count(session: Session, model: type, *where: object) -> int:
    return session.scalar(select(func.count()).select_from(model).where(*where)) or 0


def _summary(session: Session) -> int:
    """Counts and pass/fail per connection and entity; no names or amounts in any
    environment, so the output can be shared (docs/pilot-runbook.md)."""
    for connection in session.scalars(select(Connection).order_by(Connection.id)):
        sync = last_run(session, connection.id)
        check = last_run(session, connection.id, (DELETION_CHECK,))
        print(
            f"connection {connection.id}: origin {connection.config.get('origin', 'live')}, "
            f"{connection.status}, {len(connection.config.get('entities', []))} entities configured"
        )
        for label, run in (("last sync", sync), ("last deletion check", check)):
            if run is None:
                print(f"  {label}: never")
            else:
                print(
                    f"  {label}: run {run.id} ({run.run_type}) {run.status}, "
                    f"{run.records_received} received, {run.records_failed} failed"
                )
        failed_raw = _count(
            session,
            RawRecord,
            RawRecord.connection_id == connection.id,
            RawRecord.process_status == "failed",
        )
        print(f"  raw records that failed to transform: {failed_raw}")
        entity_ids = session.scalars(
            select(A.EntitySource.entity_id)
            .where(A.EntitySource.connection_id == connection.id)
            .order_by(A.EntitySource.entity_id)
        ).all()
        for entity_id in entity_ids:
            live = (A.Ledger.entity_id == entity_id, A.Ledger.is_deleted.is_(False))
            vouchers = (A.Voucher.entity_id == entity_id, A.Voucher.is_deleted.is_(False))
            print(f"  entity {entity_id}:")
            counts = {
                "ledgers": _count(session, A.Ledger, *live),
                "unmapped": _count(session, A.Ledger, *live, A.Ledger.mapping_status == "unmapped"),
                "parties": _count(session, A.Party, A.Party.entity_id == entity_id),
                "vouchers": _count(session, A.Voucher, *vouchers),
                "cancelled": _count(
                    session, A.Voucher, *vouchers, A.Voucher.is_cancelled.is_(True)
                ),
                "deleted_in_source": _count(
                    session, A.Voucher, A.Voucher.entity_id == entity_id, A.Voucher.is_deleted
                ),
                "effective_lines": _count(
                    session,
                    A.VoucherLine,
                    A.VoucherLine.entity_id == entity_id,
                    A.VoucherLine.is_effective,
                ),
            }
            print("    " + ", ".join(f"{k} {v}" for k, v in counts.items()))
            run = session.scalar(
                select(ValidationRun)
                .where(ValidationRun.entity_id == entity_id)
                .order_by(ValidationRun.id.desc())
                .limit(1)
            )
            if run is None:
                print("    validation: never ran")
                continue
            print(
                f"    validation: run {run.id} {run.status.upper()} as of {run.as_of}, "
                f"{run.checks_passed} passed, {run.checks_failed} failed"
            )
            codes = session.execute(
                select(ValidationIssue.check_code, ValidationIssue.severity, func.count())
                .where(ValidationIssue.validation_run_id == run.id)
                .group_by(ValidationIssue.check_code, ValidationIssue.severity)
            ).all()
            for code, severity, n in sorted(codes):
                print(f"      {severity}: {code} x{n}")
        alerts = session.execute(
            select(Alert.kind, func.count())
            .where(Alert.connection_id == connection.id, Alert.resolved_at.is_(None))
            .group_by(Alert.kind)
        ).all()
        print(f"  open alerts: {', '.join(f'{k} {n}' for k, n in sorted(alerts)) or 'none'}")
    return 0


def _trial_balance(session: Session, entity_code: str) -> int:
    entity = session.scalar(select(Entity).where(Entity.code == entity_code))
    if entity is None:
        print(f"No entity with code {entity_code}", file=sys.stderr)
        return 2
    rows = trial_balance(session, entity.id)
    total_dr = total_cr = 0
    print(f"Trial balance of {entity.name} (from voucher lines; debit positive)")
    print(f"  {'Ledger':<32}{'Debit':>14}{'Credit':>14}")
    for name, balance in rows:
        if balance == 0:
            continue
        dr, cr = (balance, 0) if balance > 0 else (0, -balance)
        total_dr += dr
        total_cr += cr
        print(f"  {name:<32}{dr:>14,.2f}{cr:>14,.2f}")
    print(f"  {'Total':<32}{total_dr:>14,.2f}{total_cr:>14,.2f}")
    return 0 if total_dr == total_cr else 1


if __name__ == "__main__":
    raise SystemExit(main())
