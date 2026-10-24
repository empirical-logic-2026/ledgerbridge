"""python -m devtools.tally_seed --company "LedgerBridge Test Co" [--create-only]

--expected-only prints the expected balances without contacting Tally. --integrated yes|no
only switches the company's "Integrate Accounts with Inventory" (for recordings with and
without it) and reads it back; nothing else is written.
"""

import argparse
import sys
from collections.abc import Sequence

from connectors.tally.connector import TallyConnector
from core.config import get_settings
from devtools.tally_seed.data import SEED, expected_balances, validate
from devtools.tally_seed.seed import (
    ImportFailedError,
    SeedRefusedError,
    TallyImporter,
    check_guards,
    read_state,
    seed,
    set_integration,
)

SHOWN = ("Rent", "Cash", "Capital")


def print_expected() -> None:
    balances = expected_balances(SEED)
    print("Expected Trial Balance after seeding (compare in TallyPrime):")
    for name in SHOWN:
        amount, side = balances[name]
        print(f"  {name:<8} {amount:>10,.2f} {side}")


def main(argv: Sequence[str] | None = None) -> int:
    args = argparse.ArgumentParser(prog="python -m devtools.tally_seed")
    args.add_argument("--company", required=True, help="exact name of the test company")
    args.add_argument("--expected-only", action="store_true", help="only print expected balances")
    args.add_argument(
        "--create-only",
        action="store_true",
        help="create missing items only; skip alterations, cancellations and deletions",
    )
    args.add_argument(
        "--integrated", choices=("yes", "no"), help="only switch the integration setting"
    )
    opts = args.parse_args(argv)

    problems = validate(SEED)
    if problems:
        print("Seed data is invalid:", *problems, sep="\n  ", file=sys.stderr)
        return 2
    if opts.expected_only:
        print_expected()
        return 0

    settings = get_settings()
    connector = TallyConnector.from_config(TallyConnector.default_config())
    try:
        check_guards(settings, opts.company, [e.name for e in connector.list_entities()])
    except SeedRefusedError as exc:
        print(f"Refused, nothing written: {exc}", file=sys.stderr)
        return 2

    if opts.integrated:
        on = opts.integrated == "yes"
        done = set_integration(
            connector.client, TallyImporter(settings.tally_url), opts.company, on
        )
        state = "confirmed" if done else "NOT confirmed by Tally"
        print(f"Integrate Accounts with Inventory: {'on' if on else 'off'} ({state})")
        return 0 if done else 1

    print(f"Seeding '{opts.company}' at {settings.tally_url}")
    try:
        report = seed(
            SEED,
            opts.company,
            reader=lambda: read_state(connector.client, opts.company),
            importer=TallyImporter(settings.tally_url),
            create_only=opts.create_only,
        )
    except ImportFailedError as exc:
        print(f"Tally rejected the import: {exc}", file=sys.stderr)
        return 1

    created = ", ".join(f"{n} {k}" for k, n in report.created.items()) or "nothing"
    print(f"Created: {created}")
    print(f"Altered: {', '.join(report.altered) or 'nothing'}")
    print(f"Cancelled: {', '.join(report.cancelled) or 'nothing'}")
    print(f"Deleted: {', '.join(report.deleted) or 'nothing'}")
    for item in report.skipped:
        print(f"Skipped: {item}")
    print_expected()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
