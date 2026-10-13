"""Command line for syncing sources (source-independent).

    python -m workers.cli entities --connection tally-test --source tally
    python -m workers.cli extract --connection tally-test --entity "LedgerBridge Test Co"
    python -m workers.cli sync --connection tally-test --entity "LedgerBridge Test Co" [--full]
    python -m workers.cli check-deletions --connection tally-test
    python -m workers.cli validate --connection tally-test [--as-of 2026-09-30]
    python -m workers.cli connect --connection tally-pilot --source tally --origin backup \
        --entity "Company A" --entity "Company B" [--activate | --pause]
    python -m workers.cli connect --connection tally-pilot --source tally --origin backup --all
    python -m workers.cli entity-check --connection tally-pilot
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
refuses to run (docs/pilot-runbook.md). Unexpected errors print their type and a short
message only, never SQL statements or parameters.

`entities` only reads: it never creates or changes a connection. Connections created by
any command start **paused**; only `connect --activate` makes the worker sync them on a
schedule.
"""

import argparse
import signal
import sys
import threading
import time
from collections.abc import Sequence
from datetime import date, datetime

from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from connectors import registry
from connectors.base import Period
from core import naming
from core.config import get_settings
from core.db import get_engine
from core.errors import redact_quoted, short_error
from core.models import Connection, SyncRun
from core.models import accounting as A  # noqa: N812
from core.models.accounting import Entity
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
from core.transform import trial_balance
from core.validation import ValidationReport
from workers.entities import by_names, configured, to_config
from workers.extract import connector_for, get_or_create_connection, run_extract
from workers.runs import (
    FINISHED,
    JobLog,
    Tee,
    abandon_runs,
    install_tee,
    reap_stale_runs,
)
from workers.sync import (
    DELETION_CHECK,
    EntityOutcome,
    SyncBusyError,
    SyncResult,
    deletion_check_interval,
    entity_ids_for,
    fetch_settings,
    is_due,
    last_run,
    run_deletion_check,
    run_sync,
    running_run,
)
from workers.validate import AfterRun, alert_for_run, entity_validator, run_validation


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
        "--restart",
        action="store_true",
        help="with --full: ignore an interrupted full sync's progress and fetch everything again",
    )
    sync.add_argument(
        "--refetch-from",
        type=date.fromisoformat,
        help="with --full: fetch again every chunk of an interrupted full sync from this date "
        "(YYYY-MM-DD), e.g. a damaged range; earlier completed chunks are kept",
    )
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
    sync.add_argument(
        "--job", help="job id: also write the output to sync_logs, for `watch` (ADR-024)"
    )

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
    deletions.add_argument("--job", help="job id: also write the output to sync_logs")

    connect = sub.add_parser(
        "connect", help="create or update a connection: origin and the entities it syncs"
    )
    connection_args(connect)
    connect.add_argument("--origin", choices=("live", "backup"), required=True)
    which = connect.add_mutually_exclusive_group(required=True)
    which.add_argument(
        "--entity",
        action="append",
        help="entity name exactly as the source shows it (repeatable)",
    )
    which.add_argument(
        "--all", action="store_true", help="every entity currently loaded in the source"
    )
    connect.add_argument(
        "--timeout-sec",
        type=float,
        help="how long one request to the source may take (this connection; else the "
        "TALLY_TIMEOUT_SEC default)",
    )
    connect.add_argument(
        "--pause-sec",
        type=float,
        help="pause between requests during a sync, to ease the load on the source (0 = none)",
    )
    connect.add_argument(
        "--part-month",
        choices=("auto", "supported", "unsupported"),
        help="whether the source answers requests for part of a month (auto: checked once "
        "when first needed)",
    )
    schedule = connect.add_mutually_exclusive_group()
    schedule.add_argument(
        "--activate", action="store_true", help="let the worker sync it on its schedule"
    )
    schedule.add_argument(
        "--pause",
        action="store_true",
        help="no scheduled syncs (e.g. backup data that doesn't change); manual syncs work",
    )

    check = sub.add_parser(
        "entity-check",
        help="are the configured entities in the source? (kinds of difference, never names)",
    )
    connection_args(check)
    check.add_argument(
        "--no-probe",
        action="store_true",
        help="skip selecting each entity in the source (read-only requests)",
    )

    watch = sub.add_parser("watch", help="follow a background sync job's output and result")
    connection_args(watch)
    watch.add_argument("--job", help="job id (default: the connection's latest job)")
    watch.add_argument("--poll-sec", type=float, default=2.0)
    watch.add_argument(
        "--grace-sec",
        type=float,
        default=90.0,
        help="how long without output and without a live run before the job counts as gone",
    )

    abandon = sub.add_parser(
        "abandon", help="mark the connection's running runs interrupted (manual recovery)"
    )
    connection_args(abandon)
    abandon.add_argument("--yes", action="store_true", help="confirmed (dev.ps1 asks first)")
    abandon.add_argument("--force", action="store_true", help="also runs that still look alive")

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


# How long `connect` waits for a lock on the connection row before giving up (MySQL).
CONNECT_LOCK_WAIT_SEC = 10


def main(argv: Sequence[str] | None = None) -> int:
    # Through `docker compose exec -T` stdout is a pipe; flush every line so progress
    # shows while a long sync runs.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(line_buffering=True)
    args = _parser().parse_args(argv)
    _terminate_raises_system_exit()
    with Session(get_engine()) as session:
        job = _start_job_log(session, args)
        code = 1
        try:
            code = _run(session, args)
            return code
        except (KeyboardInterrupt, SystemExit) as exc:
            code = exc.code if isinstance(exc, SystemExit) and isinstance(exc.code, int) else 130
            print(
                "Interrupted: the run is marked interrupted and its progress is kept. Run the "
                "sync again to continue.",
                file=sys.stderr,
            )
            return code
        except Exception as exc:
            if _show_names():
                raise  # test environment: the full traceback helps
            # Elsewhere: never SQL statements or their parameters, nor quoted values.
            print(f"error: {short_error(exc, redact=True)}", file=sys.stderr)
            return 1
        finally:
            if job is not None:
                _finish_job_log(job, code)


def _terminate_raises_system_exit() -> None:
    """`docker stop` and kill send SIGTERM: end like Ctrl+C, so the run is marked
    interrupted instead of being left 'running'."""
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(143))


def _start_job_log(session: Session, args: argparse.Namespace) -> JobLog | None:
    # Only the jobs themselves: `watch --job` reads that job's log, it must never write to it.
    if args.command not in ("sync", "check-deletions") or not args.job:
        return None
    connection = get_or_create_connection(session, args.connection, args.source)
    session.commit()
    job = JobLog(session.get_bind(), connection.id, args.job)  # type: ignore[arg-type]
    install_tee(job)
    return job


def _finish_job_log(job: JobLog, code: int) -> None:
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if isinstance(stream, Tee):
            stream.close_line()
            setattr(sys, name, stream.stream)
    job.finish(code)


def _run(session: Session, args: argparse.Namespace) -> int:
    if args.command == "watch":
        return _watch(session, args)
    if args.command == "abandon":
        return _abandon(session, args)
    if args.command == "status":
        return _status(session)
    if args.command == "summary":
        return _summary(session)
    if args.command == "trial-balance":
        if not _show_names():
            print("trial-balance prints amounts: test environment only.", file=sys.stderr)
            return 2
        return _trial_balance(session, args.entity_code)

    if args.command == "entities":
        return _list_entities(session, args)
    if args.command == "entity-check":
        return _entity_check(session, args)
    if args.command == "connect":
        return _connect(session, args)

    connection = get_or_create_connection(session, args.connection, args.source)
    if getattr(args, "origin", None):
        connection.config = {**connection.config, "origin": args.origin}
    session.commit()
    connector = connector_for(session, connection)
    if args.command in ("sync", "check-deletions") and args.entity:
        # Remember which entities this connection syncs (by key; used by the scheduler).
        found, missing = by_names(connector.list_entities(), args.entity)
        if missing:
            print(
                f"{len(missing)} of {len(args.entity)} named entities are not in the source "
                "(names must match exactly; see entity-check).",
                file=sys.stderr,
            )
            return 2
        kept = [e for e in configured(connection) if e.key not in {f.key for f in found}]
        connection.config = {
            **connection.config,
            "entities": [{"key": e.key, "name": e.name} for e in kept] + to_config(found),
        }
        session.commit()

    if args.command == "validate":
        reports = run_validation(
            session, connection, connector, args.entity, args.as_of, progress=_progress
        )
        return _print_validation(reports)

    if args.command in ("sync", "check-deletions"):
        if getattr(args, "refetch_from", None) and not args.full:
            print("--refetch-from applies to a full sync: add --full.", file=sys.stderr)
            return 2
        return _sync(session, connection, connector, args)

    found, _ = by_names(connector.list_entities(), [args.entity])
    if not found:
        print("The named entity is not in the source (see entity-check).", file=sys.stderr)
        return 2
    entity = found[0]
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


def _progress(message: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


def _sync(
    session: Session, connection: Connection, connector: object, args: argparse.Namespace
) -> int:
    """sync [--check-deletions] or check-deletions. Each entity is validated as soon as it
    is synced; the runs' statuses and the validation's are reported separately: a failed
    validation never fails the sync, and one entity's failure doesn't block the others."""
    validate = not getattr(args, "no_validate", False)
    after = AfterRun()

    def hook(only_if_changed: bool = False):  # noqa: ANN202
        if not validate:
            return None
        return entity_validator(
            session,
            connection,
            connector,  # type: ignore[arg-type]
            after,
            progress=_progress,
            only_if_changed=only_if_changed,
        )

    runs: list[SyncResult] = []
    try:
        if args.command == "sync":
            sync = run_sync(
                session,
                connection,
                connector,  # type: ignore[arg-type]
                args.entity,
                args.full,
                _period(args),
                progress=_progress,
                restart=getattr(args, "restart", False),
                after_entity=hook(),
                refetch_from=getattr(args, "refetch_from", None),
            )
            runs.append(sync)
            if args.check_deletions and sync.entity_keys:
                # Entities that synced; re-validated only if something was deleted.
                runs.append(
                    run_deletion_check(
                        session,
                        connection,
                        connector,  # type: ignore[arg-type]
                        progress=_progress,
                        entity_keys=sync.entity_keys,
                        after_entity=hook(only_if_changed=True),
                    )
                )
        else:
            runs.append(
                run_deletion_check(
                    session,
                    connection,
                    connector,  # type: ignore[arg-type]
                    args.entity,
                    progress=_progress,
                    after_entity=hook(),
                )
            )
    except SyncBusyError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    code = 0
    for run in runs:
        code |= _print_sync(run)
        alert_for_run(session, connection, run)
    if validate:
        code |= _print_validation(after.latest)
        if after.validation_error:
            print(f"Validation couldn't run: {_error(after.validation_error)}", file=sys.stderr)
            code |= 1
    parts = [f"{run.run_type} {run.status}" for run in runs]
    validation = after.validation_status if validate else "skipped"
    print(f"Result: {'; '.join(parts)}; validation {validation}")
    return code


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _watch(session: Session, args: argparse.Namespace) -> int:
    """Follows a background sync job: prints its output as it arrives and returns its exit
    code. Leaving (Ctrl+C) stops only the watching, never the job (ADR-024)."""
    connection = session.scalar(select(Connection).where(Connection.name == args.connection))
    if connection is None:
        print(f"No connection '{args.connection}'.", file=sys.stderr)
        return 2
    job = args.job or session.scalar(
        select(SyncLog.job_id)
        .where(SyncLog.connection_id == connection.id)
        .order_by(SyncLog.id.desc())
        .limit(1)
    )
    if job is None:
        print("No background sync job has been started for this connection yet.")
        return 2
    print(f"Following sync job {job} (Ctrl+C stops watching; the job carries on).", flush=True)
    last, quiet = 0, 0.0
    try:
        while True:
            session.rollback()  # a fresh snapshot: see lines committed since
            rows = session.execute(
                select(SyncLog.id, SyncLog.line)
                .where(SyncLog.job_id == job, SyncLog.id > last)
                .order_by(SyncLog.id)
            ).all()
            for row_id, line in rows:
                last = row_id
                if line.startswith(FINISHED):
                    code = int(line[len(FINISHED) :].rstrip("]") or 1)
                    print(f"Sync job finished (exit {code}).")
                    return code
                print(line, flush=True)
            if rows:
                quiet = 0.0
            else:
                quiet += args.poll_sec
                if quiet >= args.grace_sec and running_run(session, connection.id) is None:
                    print(
                        "The sync job stopped without finishing: its process is gone. Its run is "
                        "marked interrupted and its progress is kept; run the sync again to "
                        "continue.",
                        file=sys.stderr,
                    )
                    return 1
            _sleep(args.poll_sec)
    except KeyboardInterrupt:
        print(
            "Stopped watching. The sync job carries on; follow it again with: sync watch",
            file=sys.stderr,
        )
        return 0


def _abandon(session: Session, args: argparse.Namespace) -> int:
    connection = session.scalar(select(Connection).where(Connection.name == args.connection))
    if connection is None:
        print(f"No connection '{args.connection}'.", file=sys.stderr)
        return 2
    if not args.yes:
        print("abandon needs --yes (dev.ps1 asks you to confirm first).", file=sys.stderr)
        return 2
    abandoned, live = abandon_runs(session, connection.id, force=args.force)
    for run_id in abandoned:
        print(f"Run {run_id} marked interrupted; its checkpoints are kept.")
    for run_id in live:
        print(
            f"Run {run_id} still looks alive (recent heartbeat): left running. Wait for it, or "
            "add force if you're sure its process is gone.",
            file=sys.stderr,
        )
    if not abandoned and not live:
        print("No running runs for this connection.")
    return 3 if live else 0


def _show_names() -> bool:
    """Names and error messages are printed in the test environment only."""
    return get_settings().app_env == "test"


def _error(summary: str) -> str:
    """A stored 'Type: message' (already free of SQL): in full in test; elsewhere with
    quoted values removed (messages can name companies)."""
    return summary if _show_names() else redact_quoted(summary)


def _entities(names: Sequence[str]) -> str:
    return ", ".join(names) if _show_names() else f"{len(names)} entities"


def _list_entities(session: Session, args: argparse.Namespace) -> int:
    """Read-only: an existing connection's settings, or the source's defaults."""
    connection = session.scalar(select(Connection).where(Connection.name == args.connection))
    if connection is not None:
        connector = connector_for(session, connection)
    elif args.source:
        connector = registry.create_connector(args.source, registry.default_config(args.source))
    else:
        print(f"No connection '{args.connection}'; pass --source.", file=sys.stderr)
        return 2
    session.rollback()  # nothing to write; end the read transaction
    entities = connector.list_entities()
    print(f"{len(entities)} entities in the source of '{args.connection}'")
    if _show_names():
        for entity in entities:
            print(f"  {entity.name}  [{entity.key}]")
    return 0


def _connect(session: Session, args: argparse.Namespace) -> int:
    """Sets the connection's origin and exact list of entities, and, only when asked,
    whether the worker syncs it on a schedule. Refuses while a sync is running."""
    existing = session.scalar(select(Connection).where(Connection.name == args.connection))
    if existing is not None:
        running = running_run(session, existing.id)
        if running is not None:
            print(
                f"Refused: sync run {running.id} of '{existing.name}' is running (started "
                f"{running.started_at:%Y-%m-%d %H:%M:%S} UTC). Wait for it to finish "
                "(check with status), then run connect again.",
                file=sys.stderr,
            )
            return 3
    connection = existing or get_or_create_connection(session, args.connection, args.source)
    session.commit()
    available = connector_for(session, connection).list_entities()
    if args.all:
        found, missing = list(available), []
        wanted = [e.name for e in found]
    else:
        wanted = list(dict.fromkeys(args.entity))
        found, missing = by_names(available, wanted)
    if session.get_bind().dialect.name == "mysql":
        # Fail fast instead of hanging if the row is locked after all.
        session.execute(text(f"SET SESSION innodb_lock_wait_timeout = {CONNECT_LOCK_WAIT_SEC}"))
    # Store the entities found by key (and their names); names not found are not stored.
    connection.config = {**connection.config, "origin": args.origin, "entities": to_config(found)}
    if args.timeout_sec:
        connection.config = {**connection.config, "timeout_sec": args.timeout_sec}
    if args.pause_sec is not None:
        connection.config = {**connection.config, "pause_sec": args.pause_sec}
    if args.part_month:
        connection.config = {**connection.config, "part_month_requests": args.part_month}
    if args.activate:
        connection.status = "active"
    elif args.pause:
        connection.status = "paused"
    try:
        session.commit()
    except OperationalError as exc:
        session.rollback()
        print(
            f"Refused: the connection is locked ({short_error(exc, redact=True)}). A sync may "
            "have just started; check with status and run connect again when it's done.",
            file=sys.stderr,
        )
        return 3
    print(
        f"Connection '{connection.name}': origin {args.origin}, {connection.status}, "
        f"{len(wanted)} entities configured, {len(found)} found in the source "
        f"({len(available)} loaded there)"
    )
    print(f"  {_fetch_settings_line(connection)}")
    if missing:
        detail = f": {', '.join(missing)}" if _show_names() else ""
        print(
            f"  {len(missing)} not found{detail}. Names must match exactly, spaces included; "
            "run entity-check to see how they differ, or use --all (-All in dev.ps1) to take "
            "every loaded company. Only the found ones were stored.",
            file=sys.stderr,
        )
        return 2
    return 0


def _fetch_settings_line(connection: Connection) -> str:
    """The connection's effective request timeout, pause and part-month support (ADR-023)."""
    effective = fetch_settings(connection)
    default = get_settings().tally_timeout_sec
    own = connection.config.get("timeout_sec")
    if own:
        source = "set on the connection"
        if float(own) != float(default):
            source += f"; TALLY_TIMEOUT_SEC={default:g} applies only to connections without one"
    else:
        source = "TALLY_TIMEOUT_SEC default"
    return (
        f"request timeout {effective.timeout_sec:g} s ({source}); pause between requests "
        f"{effective.pause_sec:g} s; part-month requests: {effective.part_month}"
        " (change with connect --timeout-sec / --pause-sec / --part-month)"
    )


def _entity_check(session: Session, args: argparse.Namespace) -> int:
    """Read-only diagnostic: which configured entities the source has, and for those it
    doesn't, how the names differ. Kinds and counts only, never names (any environment)."""
    connection = session.scalar(select(Connection).where(Connection.name == args.connection))
    if connection is not None:
        connector = connector_for(session, connection)
    elif args.source:
        connector = registry.create_connector(args.source, registry.default_config(args.source))
    else:
        print(f"No connection '{args.connection}'; pass --source.", file=sys.stderr)
        return 2
    session.rollback()  # read-only from here
    available = connector.list_entities()
    number = {e.key: i for i, e in enumerate(available, start=1)}
    print(f"Source: {len(available)} entities loaded")
    for i, entity in enumerate(available, start=1):
        unusual = "; ".join(naming.features(entity.name)) or "nothing unusual"
        print(f"  source entity {i}: name of {len(entity.name)} characters; {unusual}")
    wanted = configured(connection) if connection is not None else []
    print(f"Connection '{args.connection}': {len(wanted)} entities configured")
    problems = 0
    for j, entry in enumerate(wanted, start=1):
        how = "by key" if entry.key else "by name only (stored before keys were)"
        match = next((e for e in available if entry.key and e.key == entry.key), None)
        if match is not None:
            kinds = naming.differences(entry.name, match.name)
            note = "name unchanged" if not kinds else "name now differs by: " + ", ".join(kinds)
            print(f"  entity {j} ({how}): FOUND as source entity {number[match.key]}; {note}")
            continue
        exact = next((e for e in available if e.name == entry.name), None)
        if exact is not None and not entry.key:
            print(f"  entity {j} ({how}): FOUND by exact name as source entity {number[exact.key]}")
            continue
        problems += 1
        closest = [
            (number[e.key], kinds)
            for e in available
            if (kinds := naming.differences(entry.name, e.name)) is not None
        ]
        if entry.key and exact is not None:
            detail = f"source entity {number[exact.key]} has the same name but another key"
        elif closest:
            detail = "; ".join(
                f"source entity {i} differs only by: {', '.join(k)}" for i, k in closest
            )
        else:
            detail = "no source entity has a similar name"
        print(f"  entity {j} ({how}): NOT FOUND; {detail}")
    if not args.no_probe and hasattr(connector, "probe_entity"):
        print("Selection check (select each entity by its listed name, then list again):")
        for i, entity in enumerate(available, start=1):
            try:
                groups = connector.probe_entity(entity)
                outcome = f"selected, {groups} groups"
            except Exception as exc:  # noqa: BLE001 - reported, not raised
                problems += 1
                outcome = f"selecting it FAILED ({short_error(exc, redact=True)})"
            after = {e.key: e.name for e in connector.list_entities()}
            changes = [
                f"source entity {number[e.key]} differs by: "
                + ", ".join(naming.differences(e.name, after[e.key]) or ["other"])
                for e in available
                if e.key in after and after[e.key] != e.name
            ]
            gone = sum(1 for e in available if e.key not in after)
            listing = "; ".join(changes) if changes else "names unchanged"
            if gone:
                listing += f"; {gone} no longer listed"
            if changes or gone:
                problems += 1
            print(f"  source entity {i}: {outcome}; afterwards {listing}")
    print(f"Result: {'no problems found' if not problems else f'{problems} problem(s) found'}")
    return 0 if not problems else 1


def _print_sync(r: SyncResult) -> int:
    print(f"Sync run {r.sync_run_id} ({r.run_type}): {r.status}  entities: {_entities(r.entities)}")
    if r.run_type == DELETION_CHECK:
        print(f"  keys listed:  {dict(sorted(r.fetched.items()))}")
        print(f"  soft-deleted: {r.deleted or 'none'}")
    else:
        print(f"  fetched:     {dict(sorted(r.fetched.items()))}")
        print(f"  raw stored:  {r.stored} new or changed, {r.unchanged} unchanged")
        print(f"  transformed: {dict(sorted(r.transformed.items()))}  failed: {r.failed}")
        for e in r.entity_results:
            print(f"  {_entity_line(e)}")
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


def _entity_line(e: EntityOutcome) -> str:
    """One entity's outcome: fetched, stored and transformed kept apart (counts only)."""
    name = f" ({e.name})" if _show_names() else ""
    if e.status == "not attempted":
        return f"{e.label}{name}: not attempted"
    chunks = ""
    if e.chunks:
        chunks = f" in {e.chunks} chunks"
        extras = []
        if e.chunks_skipped:
            extras.append(f"{e.chunks_skipped} done by an earlier attempt")
        if e.splits:
            extras.append(f"{e.splits} split")
        if e.retries:
            extras.append(f"{e.retries} retried whole with a longer timeout")
        if e.unverified:
            extras.append(f"{e.unverified} UNVERIFIED")
        if extras:
            chunks += f" ({', '.join(extras)})"
    line = (
        f"{e.label}{name}: {e.status.upper()}: fetched {e.fetched:,}{chunks}; "
        f"stored {e.stored:,} new or changed, {e.unchanged:,} unchanged; "
        f"transformed {e.transformed:,}, {e.transform_failed} failed"
    )
    if e.error:
        line += f"; error: {_error(e.error)}"
    return line


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
    for run_id in reap_stale_runs(session):
        print(f"Run {run_id} had no live process: marked interrupted (its progress is kept).")
    now = utcnow()
    connections = session.scalars(select(Connection).order_by(Connection.name)).all()
    if not connections:
        print("No connections yet.")
    for connection in connections:
        names = [entry.name for entry in configured(connection)]
        entities = _entities(names) if names else "all loaded"
        check_every = deletion_check_interval(connection)
        print(
            f"{connection.name}: {connection.status}, origin "
            f"{connection.config.get('origin', 'live')}, entities: {entities}"
        )
        print(f"  {_fetch_settings_line(connection)}")
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
        due = "due now" if connection.status == "active" else f"none ({connection.status})"
        print(f"{head} never ran; next: {due}")
        return
    finished = f"{run.finished_at:%Y-%m-%d %H:%M:%S}" if run.finished_at else "-"
    counts = f"{run.records_received} {received}"
    if failed:
        counts += f", {run.records_failed} {failed}"
    print(
        f"{head} last run {run.id} ({run.run_type}) {run.status}, started "
        f"{run.started_at:%Y-%m-%d %H:%M:%S} UTC, finished {finished}, {counts}"
    )
    if connection.status != "active":
        print(f"    next: none, the connection is {connection.status} (no scheduled runs)")
    elif run.status == "running":
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
        raw = session.execute(
            select(RawRecord.object_type, RawRecord.process_status, func.count())
            .where(RawRecord.connection_id == connection.id)
            .group_by(RawRecord.object_type, RawRecord.process_status)
            .order_by(RawRecord.object_type, RawRecord.process_status)
        ).all()
        listed = ", ".join(f"{kind} {status} {n:,}" for kind, status, n in raw) or "none"
        print(f"  raw records by type and status: {listed}")
        resumable = session.execute(
            select(
                SyncCheckpoint.source_entity_key, func.count(), func.min(SyncCheckpoint.created_at)
            )
            .where(SyncCheckpoint.connection_id == connection.id)
            .group_by(SyncCheckpoint.source_entity_key)
        ).all()
        ids = entity_ids_for(session, connection.id, [key for key, _, _ in resumable])
        for key, chunks, since in resumable:
            who = f"entity {ids[key]}" if key in ids else "an entity not yet transformed"
            print(
                f"  unfinished full sync of {who}: {chunks} chunks done since "
                f"{since:%Y-%m-%d %H:%M} UTC (sync full continues it; add restart to start over)"
            )
        print(f"  {_fetch_settings_line(connection)}")
        prefixes = connection.config.get("xml_prefixes_seen") or []
        if prefixes:
            print(
                f"  XML prefixes seen in the source's data: {', '.join(prefixes)} (custom fields, "
                "e.g. from TDL customisations; stored unchanged, not mapped yet)"
            )
        open_ranges = session.execute(
            select(
                SyncUnverifiedRange.source_entity_key,
                SyncUnverifiedRange.object_type,
                SyncUnverifiedRange.period_from,
                SyncUnverifiedRange.period_to,
                SyncUnverifiedRange.reason,
            )
            .where(
                SyncUnverifiedRange.connection_id == connection.id,
                SyncUnverifiedRange.resolved_at.is_(None),
            )
            .order_by(SyncUnverifiedRange.period_from)
        ).all()
        range_ids = entity_ids_for(session, connection.id, [r[0] for r in open_ranges])
        for key, kind, start, end, reason in open_ranges:
            who = (
                f"entity {range_ids[key]}" if key in range_ids else "an entity not yet transformed"
            )
            print(
                f"  UNVERIFIED {kind} {start}..{end} of {who}: {reason} "
                "(fetched again by the next sync full)"
            )
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
