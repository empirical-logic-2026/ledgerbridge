"""Command line for syncing sources (source-independent).

    python -m workers.cli entities --connection tally-test --source tally
    python -m workers.cli extract --connection tally-test --entity "LedgerBridge Test Co"
    python -m workers.cli sync --connection tally-test --entity "LedgerBridge Test Co" [--full]
    python -m workers.cli check-deletions --connection tally-test
    python -m workers.cli status
    python -m workers.cli trial-balance --entity-code LEDGERBRIDGE_TEST_CO

`extract` only stores raw records (M1); `sync` also transforms them (M3); `check-deletions`
soft-deletes what no longer exists in the source (also run by `sync --check-deletions`).
Output shows names, keys and counts only, except `trial-balance`, which prints balances
for the developer's own use (never paste them anywhere for client data).
"""

import argparse
import sys
from collections.abc import Sequence
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from connectors import registry
from connectors.base import Period
from core.db import get_engine
from core.models import Connection, SyncRun
from core.models.accounting import Entity
from core.models.base import utcnow
from core.transform import trial_balance
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

    deletions = sub.add_parser(
        "check-deletions", help="soft-delete what no longer exists in the source"
    )
    connection_args(deletions)
    deletions.add_argument("--entity", action="append", help="entity name (repeatable)")

    sub.add_parser("status", help="each connection's last sync and when the next is due")

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
        if args.command == "trial-balance":
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

        if args.command == "entities":
            entities = connector.list_entities()
            print(f"{len(entities)} entities in connection '{connection.name}':")
            for entity in entities:
                print(f"  {entity.name}  [{entity.key}]")
            return 0

        if args.command in ("sync", "check-deletions"):
            try:
                if args.command == "sync":
                    result = run_sync(
                        session, connection, connector, args.entity, args.full, _period(args)
                    )
                    code = _print_sync(result)
                    if code or not args.check_deletions:
                        return code
                result = run_deletion_check(session, connection, connector, args.entity)
            except SyncBusyError as exc:
                print(str(exc), file=sys.stderr)
                return 3
            return _print_sync(result)

        entity = find_entity(connector, args.entity)
        extracted = run_extract(session, connection, connector, entity, _period(args))

    print(f"Sync run {extracted.sync_run_id}: {extracted.status}")
    for object_type, count in sorted(extracted.by_object_type.items()):
        print(f"  {object_type}: {count}")
    print(
        f"  received {extracted.received}, stored {extracted.stored}, unchanged {extracted.skipped}"
    )
    if extracted.error:
        print(f"  error: {extracted.error}", file=sys.stderr)
        return 1
    return 0


def _print_sync(r: SyncResult) -> int:
    print(f"Sync run {r.sync_run_id} ({r.run_type}): {r.status}  entities: {', '.join(r.entities)}")
    if r.run_type == DELETION_CHECK:
        print(f"  keys listed:  {dict(sorted(r.fetched.items()))}")
        print(f"  soft-deleted: {r.deleted or 'none'}")
    else:
        print(f"  fetched:     {dict(sorted(r.fetched.items()))}")
        print(f"  raw stored:  {r.stored} new or changed, {r.unchanged} unchanged")
        print(f"  transformed: {dict(sorted(r.transformed.items()))}  failed: {r.failed}")
    for entity, names in r.unmapped_ledgers.items():
        listed = ", ".join(names) if names else "none"
        print(f"  unmapped ledgers in {entity} ({len(names)}): {listed}")
    for warning in r.warnings:
        print(f"  warning: {warning}")
    if r.error:
        print(f"  error: {r.error}", file=sys.stderr)
        return 1
    return 0


def _status(session: Session) -> int:
    now = utcnow()
    connections = session.scalars(select(Connection).order_by(Connection.name)).all()
    if not connections:
        print("No connections yet.")
    for connection in connections:
        entities = ", ".join(connection.config.get("entities", [])) or "all loaded"
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
    return 0


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
