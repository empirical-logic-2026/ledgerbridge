"""Command line for running extractions (source-independent).

    python -m workers.cli entities --connection tally-test --source tally
    python -m workers.cli extract --connection tally-test --entity "LedgerBridge Test Co"

Output shows names, keys and counts only, never accounting values.
"""

import argparse
import sys
from collections.abc import Sequence
from datetime import date

from sqlalchemy.orm import Session

from connectors import registry
from connectors.base import Period
from core.db import get_engine
from workers.extract import connector_for, find_entity, get_or_create_connection, run_extract


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

    entities = sub.add_parser("entities", help="list entities (companies) in the source")
    connection_args(entities)

    extract = sub.add_parser(
        "extract", help="full extraction of one entity into ledgerbridge_source.raw_records"
    )
    connection_args(extract)
    extract.add_argument("--entity", required=True, help="entity (company) name in the source")
    extract.add_argument("--from", dest="date_from", type=date.fromisoformat)
    extract.add_argument("--to", dest="date_to", type=date.fromisoformat)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    with Session(get_engine()) as session:
        connection = get_or_create_connection(session, args.connection, args.source)
        session.commit()
        connector = connector_for(session, connection)

        if args.command == "entities":
            entities = connector.list_entities()
            print(f"{len(entities)} entities in connection '{connection.name}':")
            for entity in entities:
                print(f"  {entity.name}  [{entity.key}]")
            return 0

        entity = find_entity(connector, args.entity)
        period = None
        if args.date_from or args.date_to:
            if not (args.date_from and args.date_to):
                print("--from and --to must be given together", file=sys.stderr)
                return 2
            period = Period(args.date_from, args.date_to)
        result = run_extract(session, connection, connector, entity, period)

    print(f"Sync run {result.sync_run_id}: {result.status}")
    for object_type, count in sorted(result.by_object_type.items()):
        print(f"  {object_type}: {count}")
    print(f"  received {result.received}, stored {result.stored}, unchanged {result.skipped}")
    if result.error:
        print(f"  error: {result.error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
