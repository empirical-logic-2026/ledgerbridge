"""Command line for syncing sources (source-independent).

    python -m workers.cli entities --connection tally-test --source tally
    python -m workers.cli extract --connection tally-test --entity "LedgerBridge Test Co"
    python -m workers.cli sync --connection tally-test --entity "LedgerBridge Test Co" [--full]
    python -m workers.cli status
    python -m workers.cli trial-balance --entity-code LEDGERBRIDGE_TEST_CO

`extract` only stores raw records (M1); `sync` also transforms them (M3).
Output shows names, keys and counts only, except `trial-balance`, which prints balances
for the developer's own use (never paste them anywhere for client data).
"""

import argparse
import sys
from collections.abc import Sequence
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from connectors import registry
from connectors.base import Period
from core.db import get_engine
from core.models import Connection
from core.models.accounting import Entity
from core.models.base import utcnow
from core.transform import trial_balance
from workers.extract import connector_for, find_entity, get_or_create_connection, run_extract
from workers.sync import SyncBusyError, is_due, last_run, run_sync


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
        "--origin", choices=("live", "backup"), help="origin tag for this connection's data"
    )
    period_args(sync)

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
        if args.command == "sync" and args.entity:
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

        if args.command == "sync":
            try:
                result = run_sync(
                    session, connection, connector, args.entity, args.full, _period(args)
                )
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


def _print_sync(result: object) -> int:
    r = result  # SyncResult
    print(f"Sync run {r.sync_run_id} ({r.run_type}): {r.status}  entities: {', '.join(r.entities)}")
    print(f"  fetched:     {dict(sorted(r.fetched.items()))}")
    print(f"  raw stored:  {r.stored} new or changed, {r.unchanged} unchanged")
    print(f"  transformed: {dict(sorted(r.transformed.items()))}  failed: {r.failed}")
    print(f"  soft-deleted: {r.deleted or 'none'}")
    for entity, names in r.unmapped_ledgers.items():
        listed = ", ".join(names) if names else "none"
        print(f"  unmapped ledgers in {entity} ({len(names)}): {listed}")
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
        run = last_run(session, connection.id)
        entities = ", ".join(connection.config.get("entities", [])) or "all loaded"
        print(
            f"{connection.name}: {connection.status}, every {connection.sync_interval_sec}s, "
            f"origin {connection.config.get('origin', 'live')}, entities: {entities}"
        )
        if run is None:
            print("  last sync: never; next: due now")
            continue
        finished = f"{run.finished_at:%Y-%m-%d %H:%M:%S}" if run.finished_at else "-"
        print(
            f"  last sync: run {run.id} ({run.run_type}) {run.status}, "
            f"started {run.started_at:%Y-%m-%d %H:%M:%S} UTC, finished {finished}, "
            f"{run.records_received} fetched, {run.records_failed} failed"
        )
        if run.status == "running":
            print("  next: after the current run")
        elif is_due(connection, run.started_at, now):
            print("  next: due now (picked up within a minute by the worker)")
        else:
            wait = connection.sync_interval_sec - int((now - run.started_at).total_seconds())
            print(f"  next: in about {wait}s")
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
